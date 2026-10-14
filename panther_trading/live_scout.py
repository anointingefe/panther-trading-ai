from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from panther_trading.adaptive_learning import AdaptiveLearningEngine
from panther_trading.brokers import create_broker
from panther_trading.brokers.base import Broker
from panther_trading.beast_mode import BeastModeStore, DEFAULT_BEAST_MODE, apply_beast_mode
from panther_trading.config import load_config
from panther_trading.data import StaticSentimentCollector
from panther_trading.demo_auto import DemoAutoTrader
from panther_trading.goals import GoalTracker
from panther_trading.models import TradeSignal
from panther_trading.portfolio_risk import ApprovedLivePortfolioRisk, exposure_buckets
from panther_trading.positions import PaperPositionBook
from panther_trading.preflight import execution_preflight
from panther_trading.risk import RiskManager
from panther_trading.strategies import SmaSentimentStrategy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_SCOUT_STATE = PROJECT_ROOT / "var/live_scout_state.json"
DEFAULT_POSITIONS = PROJECT_ROOT / "var/paper_positions.jsonl"
DEFAULT_GOALS = PROJECT_ROOT / "var/trading_goals.json"


@dataclass(frozen=True)
class LiveScoutDecision:
    ticket_id: str | None
    status: str
    symbol: str
    side: str
    confidence: float
    rank_score: float
    reason: str
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    volume: float | None = None
    edge_probability: float | None = None
    learning_quality: float | None = None
    learning_adjustment: float | None = None
    generated_at: str | None = None
    rationale: tuple[str, ...] = ()
    preflight: dict[str, Any] | None = None
    portfolio_risk: dict[str, Any] | None = None
    approval_required: bool = True


@dataclass(frozen=True)
class LiveScoutCycle:
    status: str
    started_at: str
    finished_at: str
    broker_mode: str
    scanned: int
    ready: int
    blocked: int
    decisions: tuple[LiveScoutDecision, ...]
    learning: dict[str, Any]
    history_imported: int = 0
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


class LiveScoutStore:
    def __init__(self, path: str | Path = DEFAULT_LIVE_SCOUT_STATE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "running": False,
                "lastCycle": None,
                "message": "Live scout has not run yet.",
                "learning": {},
            }
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, cycle: LiveScoutCycle, running: bool = False) -> None:
        message = (
            f"Blocked: {cycle.reasons[0]}"
            if cycle.status == "blocked" and cycle.reasons
            else f"Live scout found {cycle.ready} approval-ready setup(s) across {cycle.scanned} scanned markets."
        )
        self.path.write_text(
            json.dumps(
                {
                    "running": running,
                    "lastCycle": cycle.to_dict(),
                    "message": message,
                    "learning": cycle.learning,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def ticket(self, ticket_id: str) -> dict[str, Any] | None:
        cycle = self.state().get("lastCycle") or {}
        for decision in cycle.get("decisions") or []:
            if decision.get("ticket_id") == ticket_id and decision.get("status") == "ready":
                return decision
        return None


class LiveScoutTrader:
    """Continuous live-market analysis that never submits a real-money order.

    It mirrors the demo selection stack, adds broker-native preflight and bounded
    adaptive learning, and emits exact approval-ready trade tickets every cycle.
    """

    def __init__(
        self,
        config_path: str | Path,
        state_path: str | Path = DEFAULT_LIVE_SCOUT_STATE,
        positions_path: str | Path = DEFAULT_POSITIONS,
        goals_path: str | Path = DEFAULT_GOALS,
        beast_mode_path: str | Path = DEFAULT_BEAST_MODE,
        broker: Broker | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.positions_path = Path(positions_path)
        self.goals_path = Path(goals_path)
        self.beast_mode_path = Path(beast_mode_path)
        self._broker = broker
        self._cycle_lock = Lock()
        self.store = LiveScoutStore(self.state_path)

    def status(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        state = self.store.state()
        state["enabled"] = config.live_scout.enabled
        state["intervalSeconds"] = config.live_scout.interval_seconds
        state["approvalRequired"] = True
        state["portfolioModel"] = {
            "maxOpenPositions": config.live_scout.model_max_open_positions,
            "maxPortfolioRiskPct": config.live_scout.model_max_portfolio_risk_pct,
            "maxExposureBucketRiskPct": config.live_scout.model_max_exposure_bucket_risk_pct,
            "maxPositionsPerSymbol": config.risk.max_positions_per_symbol,
        }
        state["policy"] = (
            "Panther may scan, learn, rank, size and preflight continuously using the portfolio model. "
            "Real-money submission permissions are unchanged and explicit approval is still required."
        )
        return state

    def run_cycle(self) -> LiveScoutCycle:
        if not self._cycle_lock.acquire(blocking=False):
            now = datetime.now(timezone.utc)
            return self._blocked_cycle(now, "unknown", "A live scout scan is already in progress.")
        try:
            cycle = self._run_cycle()
            self.store.write(cycle)
            return cycle
        finally:
            self._cycle_lock.release()

    def _run_cycle(self) -> LiveScoutCycle:
        started_at = datetime.now(timezone.utc)
        config = load_config(self.config_path)
        if not config.live_scout.enabled:
            return self._blocked_cycle(started_at, "disabled", "Live scout is disabled in config.")
        try:
            broker = self._broker or create_broker("mt5")
            broker_status = broker.get_status()
        except Exception as exc:
            return self._blocked_cycle(started_at, "unavailable", f"Broker setup failed: {exc}")

        mode = str(broker_status.mode or "unknown").lower()
        allowed_modes = {item.lower() for item in config.live_scout.allowed_account_modes}
        if not broker_status.connected:
            return self._blocked_cycle(started_at, mode, "Broker is not connected.")
        if mode not in allowed_modes:
            return self._blocked_cycle(started_at, mode, f"Live scout refuses account mode: {mode}.")
        equity = broker_status.equity
        if equity is None or not math.isfinite(equity) or equity <= 0:
            return self._blocked_cycle(started_at, mode, "Broker equity is unavailable or invalid.")

        positions_book = PaperPositionBook(self.positions_path)
        imported = self._sync_history(positions_book, broker, config.live_scout.history_sync_days)
        positions = positions_book.latest(limit=5000)
        config = replace(config, risk=replace(config.risk, account_equity=float(equity)))
        config = apply_beast_mode(config, BeastModeStore(self.beast_mode_path).load().enabled, positions)
        learning_engine = AdaptiveLearningEngine()
        learning = learning_engine.profile(positions)

        helper = DemoAutoTrader(
            self.config_path,
            self.state_path,
            broker=broker,
            positions_path=self.positions_path,
            goals_path=self.goals_path,
            beast_mode_path=self.beast_mode_path,
        )
        available = set(broker.list_symbols())
        symbols = helper._symbols_to_scan(config, available)[: config.live_scout.max_symbols_per_cycle]
        goal_tracker = GoalTracker(self.goals_path)
        goal_pressure = goal_tracker.goal_pressure(positions)
        daily_pnl = goal_tracker.report(positions)["progress"]["daily"]["netPnl"]
        loss_state = helper._loss_state(config, positions)
        decisions: list[LiveScoutDecision] = []

        for symbol in symbols:
            try:
                decision = self._evaluate_symbol(
                    config,
                    broker,
                    helper,
                    learning_engine,
                    learning,
                    symbol,
                    positions,
                    loss_state,
                    goal_pressure,
                    daily_pnl,
                )
            except Exception as exc:
                decision = self._blocked(symbol, "hold", 0.0, f"Symbol skipped: {exc}")
            decisions.append(decision)

        decisions.sort(key=lambda item: (item.status != "ready", -item.rank_score, item.symbol))
        ready = len([item for item in decisions if item.status == "ready"])
        if ready > config.live_scout.max_candidates_per_cycle:
            kept = 0
            limited: list[LiveScoutDecision] = []
            for item in decisions:
                if item.status == "ready":
                    kept += 1
                    if kept > config.live_scout.max_candidates_per_cycle:
                        limited.append(replace(item, status="watch", ticket_id=None, reason="Ready setup ranked below this cycle's candidate limit"))
                        continue
                limited.append(item)
            decisions = limited
            ready = config.live_scout.max_candidates_per_cycle

        return LiveScoutCycle(
            status="active" if decisions else "idle",
            started_at=started_at.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            broker_mode=mode,
            scanned=len(decisions),
            ready=ready,
            blocked=len([item for item in decisions if item.status == "blocked"]),
            decisions=tuple(decisions),
            learning=learning,
            history_imported=imported,
        )

    def _evaluate_symbol(
        self,
        config: Any,
        broker: Broker,
        helper: DemoAutoTrader,
        learning_engine: AdaptiveLearningEngine,
        learning: dict[str, Any],
        symbol: str,
        positions: list[dict[str, Any]],
        loss_state: dict[str, dict[str, Any]],
        goal_pressure: dict[str, Any],
        daily_pnl: float,
    ) -> LiveScoutDecision:
        if goal_pressure["daily_target_met"]:
            return self._blocked(symbol, "hold", 0.0, "Daily target reached; protecting gains until tomorrow")
        if broker.count_open_positions() >= config.live_scout.model_max_open_positions:
            return self._blocked(symbol, "hold", 0.0, "Ten-position portfolio model is fully allocated")
        if broker.count_open_positions(symbol) >= config.risk.max_positions_per_symbol:
            return self._blocked(symbol, "hold", 0.0, "Maximum live positions reached for symbol")
        cooldown = helper._cooldown_reason(config, symbol, loss_state)
        if cooldown:
            return self._blocked(symbol, "hold", 0.0, cooldown)

        candles = broker.get_candles(symbol, config.app.timeframe, config.app.candles)
        volatility = helper._volatility_guard(config, candles)
        if volatility:
            return self._blocked(symbol, "hold", 0.0, volatility.replace("demo entry", "live setup"))
        signal = SmaSentimentStrategy(config.strategy).generate(
            symbol, candles, StaticSentimentCollector().collect(symbol)
        )
        if goal_pressure["weekly_target_met"] and signal.confidence < config.risk.min_confidence + 0.08:
            return self._blocked(symbol, signal.side.value, signal.confidence, "Weekly target reached; only exceptional live setups are surfaced")
        if goal_pressure["monthly_target_met"] and signal.confidence < config.risk.min_confidence + 0.10:
            return self._blocked(symbol, signal.side.value, signal.confidence, "Monthly target reached; preserve capital unless setup is exceptional")

        temporal = helper._temporal_gate(config, symbol, signal.generated_at, positions)
        if temporal:
            return self._blocked(symbol, signal.side.value, signal.confidence, temporal)
        performance = helper._symbol_performance_gate(config, symbol, positions)
        if performance:
            return self._blocked(symbol, signal.side.value, signal.confidence, performance)
        edge_probability = helper._bayesian_edge_probability(config, symbol, positions)
        signal = helper._adjust_signal_confidence(config, signal, edge_probability)

        scout_risk_config = replace(
            config.risk,
            max_open_positions=config.live_scout.model_max_open_positions,
        )
        base_risk = RiskManager(scout_risk_config).evaluate(
            signal,
            open_positions=broker.count_open_positions(),
            daily_pnl=daily_pnl,
        )
        if not base_risk.allowed:
            return self._blocked(symbol, signal.side.value, signal.confidence, base_risk.reason)

        assessment = learning_engine.assess(
            symbol,
            signal.generated_at,
            learning,
            minimum_samples=config.live_scout.learning_min_segment_samples,
        )
        if assessment.block_reason:
            return self._blocked(
                symbol,
                signal.side.value,
                signal.confidence,
                assessment.block_reason,
                rank_score=signal.confidence + assessment.rank_adjustment,
                learning_quality=assessment.quality_score,
                learning_adjustment=assessment.rank_adjustment,
            )

        portfolio_guard = ApprovedLivePortfolioRisk(
            broker,
            equity=config.risk.account_equity,
            max_portfolio_risk_pct=config.live_scout.model_max_portfolio_risk_pct,
            max_exposure_bucket_risk_pct=config.live_scout.model_max_exposure_bucket_risk_pct,
        )
        available_risk, portfolio_snapshot, portfolio_reasons = portfolio_guard.available_risk_for(signal)
        portfolio_payload = {
            **portfolio_snapshot.to_dict(),
            "availableRiskForCandidate": available_risk,
            "candidateExposureBuckets": list(exposure_buckets(signal.symbol, signal.side)),
        }
        if available_risk <= 0:
            return self._blocked(
                symbol,
                signal.side.value,
                signal.confidence,
                "; ".join(portfolio_reasons or ("No aggregate portfolio risk budget remains",)),
                rank_score=signal.confidence + assessment.rank_adjustment,
                learning_quality=assessment.quality_score,
                learning_adjustment=assessment.rank_adjustment,
                portfolio_risk=portfolio_payload,
            )

        volume = self._live_volume(config, broker, signal, goal_pressure, risk_budget=available_risk)
        if volume <= 0:
            return self._blocked(
                symbol,
                signal.side.value,
                signal.confidence,
                "No broker-valid volume fits the aggregate portfolio risk budget",
                portfolio_risk=portfolio_payload,
            )
        preflight = execution_preflight(
            broker,
            signal.symbol,
            signal.side,
            volume,
            signal.entry,
            signal.stop_loss,
            signal.take_profit,
        )
        if not preflight.get("executable"):
            reason = "; ".join(preflight.get("blockers") or ["Broker preflight rejected the setup"])
            return self._blocked(
                symbol,
                signal.side.value,
                signal.confidence,
                reason,
                rank_score=signal.confidence + assessment.rank_adjustment,
                learning_quality=assessment.quality_score,
                learning_adjustment=assessment.rank_adjustment,
                preflight=preflight,
                portfolio_risk=portfolio_payload,
            )

        generated_at = datetime.now(timezone.utc).isoformat()
        rationale = tuple(
            [
                *signal.rationale,
                f"Adaptive selection quality {assessment.quality_score:.0%}; ranking adjustment {assessment.rank_adjustment:+.3f}.",
                "Base confidence and risk floors remain unchanged; learning cannot increase configured risk.",
                (
                    f"Ten-position portfolio model passed: open stop-risk {portfolio_snapshot.total_open_risk_pct:.2f}% "
                    f"of {config.live_scout.model_max_portfolio_risk_pct:.2f}% cap; candidate respects "
                    f"{config.live_scout.model_max_exposure_bucket_risk_pct:.2f}% directional bucket cap."
                ),
                "Broker-native preflight passed. Explicit approval is required before live submission.",
            ]
        )
        return LiveScoutDecision(
            ticket_id=f"live-{uuid4().hex[:12]}",
            status="ready",
            symbol=symbol,
            side=signal.side.value,
            confidence=signal.confidence,
            rank_score=round(signal.confidence + assessment.rank_adjustment, 4),
            reason="Approval-ready live setup",
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            volume=float(preflight.get("normalized_volume") or volume),
            edge_probability=edge_probability,
            learning_quality=assessment.quality_score,
            learning_adjustment=assessment.rank_adjustment,
            generated_at=generated_at,
            rationale=rationale,
            preflight=preflight,
            portfolio_risk=portfolio_payload,
            approval_required=True,
        )

    def _live_volume(
        self,
        config: Any,
        broker: Broker,
        signal: TradeSignal,
        goal_pressure: dict[str, Any],
        risk_budget: float | None = None,
    ) -> float:
        equity = broker.get_status().equity
        if equity is None or not math.isfinite(equity) or equity <= 0:
            return 0.0
        risk_amount = equity * config.risk.max_risk_per_trade_pct / 100
        if goal_pressure["daily_progress"] < 0:
            risk_amount *= 0.5
        elif goal_pressure["weekly_progress"] >= 0.85 or goal_pressure["monthly_progress"] >= 0.85:
            risk_amount *= 0.65
        if risk_budget is not None:
            risk_amount = min(risk_amount, max(float(risk_budget), 0.0))
        return broker.calculate_position_volume(
            signal.symbol,
            signal.side,
            signal.entry,
            signal.stop_loss,
            risk_amount,
            config.execution.max_live_volume,
        )

    def _sync_history(self, positions: PaperPositionBook, broker: Broker, days: int) -> int:
        if not hasattr(broker, "get_closed_trades"):
            return 0
        before = len(positions.latest(limit=5000))
        for trade in broker.get_closed_trades(days=days):  # type: ignore[attr-defined]
            positions.import_closed_trade(trade)
        after = len(positions.latest(limit=5000))
        return max(after - before, 0)

    def _blocked(
        self,
        symbol: str,
        side: str,
        confidence: float,
        reason: str,
        rank_score: float | None = None,
        learning_quality: float | None = None,
        learning_adjustment: float | None = None,
        preflight: dict[str, Any] | None = None,
        portfolio_risk: dict[str, Any] | None = None,
    ) -> LiveScoutDecision:
        return LiveScoutDecision(
            ticket_id=None,
            status="blocked",
            symbol=symbol,
            side=side,
            confidence=confidence,
            rank_score=round(rank_score if rank_score is not None else confidence, 4),
            reason=reason,
            learning_quality=learning_quality,
            learning_adjustment=learning_adjustment,
            preflight=preflight,
            portfolio_risk=portfolio_risk,
        )

    def _blocked_cycle(self, started_at: datetime, broker_mode: str, reason: str) -> LiveScoutCycle:
        return LiveScoutCycle(
            status="blocked",
            started_at=started_at.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            broker_mode=broker_mode,
            scanned=0,
            ready=0,
            blocked=1,
            decisions=(),
            learning={},
            reasons=(reason,),
        )


class LiveScoutRunner:
    def __init__(self, trader: LiveScoutTrader, interval_seconds: int) -> None:
        self.trader = trader
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._thread = Thread(target=self._loop, name="panther-live-scout", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        return self.status()

    def status(self) -> dict[str, Any]:
        state = self.trader.status()
        state["running"] = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        return state

    def run_once(self) -> dict[str, Any]:
        cycle = self.trader.run_cycle()
        return {
            "running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
            "lastCycle": cycle.to_dict(),
            "message": (
                f"Blocked: {cycle.reasons[0]}"
                if cycle.status == "blocked" and cycle.reasons
                else f"Live scout cycle completed with {cycle.ready} approval-ready setup(s)."
            ),
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.trader.run_cycle()
            self._stop.wait(self.interval_seconds)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value
