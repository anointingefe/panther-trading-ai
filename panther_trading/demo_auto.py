from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from panther_trading.brokers import create_broker
from panther_trading.brokers.base import Broker
from panther_trading.beast_mode import BeastModeStore, DEFAULT_BEAST_MODE, apply_beast_mode
from panther_trading.config import PantherConfig, load_config
from panther_trading.data import StaticSentimentCollector
from panther_trading.data.markets import market_universe
from panther_trading.goals import GoalTracker
from panther_trading.models import OrderRequest, OrderStatus, TradeSignal
from panther_trading.risk import RiskManager
from panther_trading.strategies import SmaSentimentStrategy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POSITIONS = PROJECT_ROOT / "var/paper_positions.jsonl"
DEFAULT_GOALS = PROJECT_ROOT / "var/trading_goals.json"


@dataclass(frozen=True)
class DemoAutoDecision:
    symbol: str
    action: str
    side: str
    confidence: float
    reason: str
    order_status: str | None = None
    order_message: str | None = None
    broker_order_id: str | None = None
    volume: float | None = None
    edge_probability: float | None = None


@dataclass(frozen=True)
class DemoAutoCycle:
    status: str
    started_at: str
    finished_at: str
    broker_mode: str
    scanned: int
    placed: int
    blocked: int
    decisions: tuple[DemoAutoDecision, ...]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


class DemoAutoTrader:
    """Demo-only proving engine.

    This class can place MT5 orders only when the connected account reports a
    demo-like mode. It is intentionally separate from the live guard.
    """

    def __init__(
        self,
        config_path: str | Path,
        state_path: str | Path,
        broker_kind: str = "mt5",
        broker: Broker | None = None,
        positions_path: str | Path = DEFAULT_POSITIONS,
        goals_path: str | Path = DEFAULT_GOALS,
        beast_mode_path: str | Path = DEFAULT_BEAST_MODE,
    ) -> None:
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.positions_path = Path(positions_path)
        self.goals_path = Path(goals_path)
        self.beast_mode_path = Path(beast_mode_path)
        self.broker_kind = broker_kind
        self._broker = broker
        self._cycle_lock = Lock()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def run_cycle(self) -> DemoAutoCycle:
        if not self._cycle_lock.acquire(blocking=False):
            now = datetime.now(timezone.utc).isoformat()
            return DemoAutoCycle(
                status="blocked", started_at=now, finished_at=now,
                broker_mode="unknown", scanned=0, placed=0, blocked=1,
                decisions=(), reasons=("A demo scan is already in progress.",),
            )
        try:
            return self._run_cycle()
        finally:
            self._cycle_lock.release()

    def _run_cycle(self) -> DemoAutoCycle:
        started_at = datetime.now(timezone.utc)
        config = load_config(self.config_path)
        positions = self._read_positions() if self.positions_path.exists() else []
        beast_state = BeastModeStore(self.beast_mode_path).load()
        config = apply_beast_mode(config, beast_state.enabled, positions)
        try:
            broker = self._broker or create_broker(self.broker_kind)
            status = broker.get_status()
        except Exception as exc:
            cycle = DemoAutoCycle(
                status="blocked",
                started_at=started_at.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                broker_mode="unavailable",
                scanned=0,
                placed=0,
                blocked=1,
                decisions=(),
                reasons=(f"Broker setup failed: {exc}",),
            )
            self._write_state(cycle)
            return cycle
        mode = str(status.mode).lower()
        if mode not in config.demo_auto.allowed_account_modes:
            cycle = DemoAutoCycle(
                status="blocked",
                started_at=started_at.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                broker_mode=mode,
                scanned=0,
                placed=0,
                blocked=1,
                decisions=(),
                reasons=(f"Demo auto refuses account mode: {mode}.",),
            )
            self._write_state(cycle)
            return cycle
        if not status.connected:
            cycle = DemoAutoCycle(
                status="blocked",
                started_at=started_at.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                broker_mode=mode,
                scanned=0,
                placed=0,
                blocked=1,
                decisions=(),
                reasons=("Broker is not connected.",),
            )
            self._write_state(cycle)
            return cycle

        if status.equity is None or not math.isfinite(status.equity) or status.equity <= 0:
            cycle = DemoAutoCycle(
                status="blocked",
                started_at=started_at.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                broker_mode=mode, scanned=0, placed=0, blocked=1, decisions=(),
                reasons=("Broker equity is unavailable or invalid.",),
            )
            self._write_state(cycle)
            return cycle
        config = replace(config, risk=replace(config.risk, account_equity=status.equity))
        decisions: list[DemoAutoDecision] = []
        available = set(broker.list_symbols())
        symbols = self._symbols_to_scan(config, available)
        loss_state = self._loss_state(config, positions)
        placed_this_cycle = 0
        for symbol in symbols:
            try:
                decision = self._evaluate_symbol(config, broker, symbol, loss_state, placed_this_cycle)
                if decision.action == "placed":
                    placed_this_cycle += 1
                decisions.append(decision)
            except Exception as exc:
                decisions.append(self._blocked(symbol, "hold", 0.0, f"Symbol skipped: {exc}"))
        decisions = sorted(
            decisions,
            key=lambda decision: (decision.action != "placed", -decision.confidence, decision.symbol),
        )

        placed = len([decision for decision in decisions if decision.action == "placed"])
        blocked = len(decisions) - placed
        cycle = DemoAutoCycle(
            status="active" if decisions else "idle",
            started_at=started_at.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            broker_mode=mode,
            scanned=len(decisions),
            placed=placed,
            blocked=blocked,
            decisions=tuple(decisions),
        )
        self._write_state(cycle)
        return cycle

    def latest_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "running": False,
                "lastCycle": None,
                "message": "Demo auto runner has not run yet.",
            }
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _symbols_to_scan(self, config: PantherConfig, available: set[str]) -> list[str]:
        configured = [item["symbol"] for item in market_universe()]
        selected = [
            resolved
            for symbol in configured
            if (resolved := self._resolve_symbol_alias(symbol, available)) is not None
        ]
        seen = set(selected)
        broker_only = sorted(symbol for symbol in available if symbol not in seen and self._is_tradeable_symbol(symbol))
        selected.extend(broker_only)
        return selected[: config.demo_auto.max_symbols_per_cycle]

    def _resolve_symbol_alias(self, configured: str, available: set[str]) -> str | None:
        if configured in available:
            return configured
        configured_key = self._symbol_key(configured)
        matches = sorted(
            symbol for symbol in available
            if self._symbol_key(symbol).startswith(configured_key)
        )
        return matches[0] if matches else None

    def _symbol_key(self, symbol: str) -> str:
        return "".join(char for char in symbol.upper() if char.isalnum())

    def _is_tradeable_symbol(self, symbol: str) -> bool:
        clean = symbol.strip()
        if not clean or len(clean) > 24:
            return False
        return any(char.isalpha() for char in clean)

    def _evaluate_symbol(
        self,
        config: PantherConfig,
        broker: Broker,
        symbol: str,
        loss_state: dict[str, dict[str, Any]],
        placed_this_cycle: int,
    ) -> DemoAutoDecision:
        if placed_this_cycle >= config.demo_auto.max_orders_per_cycle:
            return self._blocked(symbol, "hold", 0.0, "Maximum demo orders for this cycle reached")
        total_open = broker.count_open_positions()
        symbol_open = broker.count_open_positions(symbol)
        if total_open >= config.demo_auto.max_open_positions:
            return self._blocked(symbol, "hold", 0.0, "Maximum total demo positions reached")
        if symbol_open >= config.demo_auto.max_positions_per_symbol:
            return self._blocked(symbol, "hold", 0.0, "Maximum demo positions reached for symbol")
        cooldown = self._cooldown_reason(config, symbol, loss_state)
        if cooldown:
            return self._blocked(symbol, "hold", 0.0, cooldown)

        candles = broker.get_candles(symbol, config.app.timeframe, config.app.candles)
        volatility = self._volatility_guard(config, candles)
        if volatility:
            return self._blocked(symbol, "hold", 0.0, volatility)
        sentiment = StaticSentimentCollector().collect(symbol)
        signal = SmaSentimentStrategy(config.strategy).generate(symbol, candles, sentiment)
        positions = self._read_positions() if self.positions_path.exists() else []
        goal_pressure = GoalTracker(self.goals_path).goal_pressure(positions)
        if goal_pressure["daily_target_met"]:
            return self._blocked(symbol, signal.side.value, signal.confidence, "Daily target reached; protecting gains until tomorrow")
        if goal_pressure["weekly_target_met"] and signal.confidence < config.risk.min_confidence + 0.08:
            return self._blocked(symbol, signal.side.value, signal.confidence, "Weekly target reached; only exceptional setups may add risk")
        if goal_pressure["monthly_target_met"] and signal.confidence < config.risk.min_confidence + 0.1:
            return self._blocked(symbol, signal.side.value, signal.confidence, "Monthly target reached; preserve capital unless setup is exceptional")
        temporal = self._temporal_gate(config, symbol, signal.generated_at, positions)
        if temporal:
            return self._blocked(symbol, signal.side.value, signal.confidence, temporal)
        performance = self._symbol_performance_gate(config, symbol, positions)
        if performance:
            return self._blocked(symbol, signal.side.value, signal.confidence, performance)
        edge_probability = self._bayesian_edge_probability(config, symbol, positions)
        signal = self._adjust_signal_confidence(config, signal, edge_probability)
        demo_risk = replace(
            config.risk,
            max_open_positions=config.demo_auto.max_open_positions,
            max_positions_per_symbol=config.demo_auto.max_positions_per_symbol,
        )
        scout_mode = signal.confidence < config.risk.min_confidence
        if scout_mode and signal.confidence >= config.demo_auto.scout_min_confidence:
            demo_risk = replace(demo_risk, min_confidence=config.demo_auto.scout_min_confidence)
            signal = replace(
                signal,
                rationale=(
                    *signal.rationale,
                    "Demo scout mode: sub-threshold setup is incubation-only and must stay out of live trading.",
                ),
            )
        daily_pnl = GoalTracker(self.goals_path).report(positions)["progress"]["daily"]["netPnl"]
        risk = RiskManager(demo_risk).evaluate(signal, open_positions=total_open, daily_pnl=daily_pnl)
        if not risk.allowed:
            return self._blocked(symbol, signal.side.value, signal.confidence, risk.reason)
        volume = self._kelly_volume(config, signal)
        if scout_mode:
            volume = round(max(volume * config.demo_auto.scout_volume_multiplier, 0.001), 4)
        volume = self._goal_adjusted_volume(config, signal, volume, goal_pressure, scout_mode)
        risk_amount = config.risk.account_equity * config.risk.max_risk_per_trade_pct / 100
        volume = broker.calculate_position_volume(
            symbol, signal.side, signal.entry, signal.stop_loss, risk_amount, volume,
        )
        if not math.isfinite(volume) or volume <= 0:
            return self._blocked(symbol, signal.side.value, signal.confidence, "No valid volume fits the trade risk budget")

        result = broker.place_order(
            OrderRequest(
                symbol=symbol,
                side=signal.side,
                volume=volume,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                comment="PANTHER demo incubation",
            )
        )
        action = "placed" if result.status in {OrderStatus.ACCEPTED, OrderStatus.SIMULATED} else "blocked"
        goal_mode = str(goal_pressure["mode"]).replace("_", " ")
        return DemoAutoDecision(
            symbol=symbol,
            action=action,
            side=signal.side.value,
            confidence=signal.confidence,
            reason=(
                f"Demo scout incubation order placed; {goal_mode}"
                if action == "placed" and scout_mode
                else f"Demo incubation order placed; {goal_mode}"
                if action == "placed"
                else result.message
            ),
            order_status=result.status.value,
            order_message=result.message,
            broker_order_id=result.broker_order_id,
            volume=volume,
            edge_probability=edge_probability,
        )

    def _blocked(self, symbol: str, side: str, confidence: float, reason: str) -> DemoAutoDecision:
        return DemoAutoDecision(
            symbol=symbol,
            action="blocked",
            side=side,
            confidence=confidence,
            reason=reason,
        )

    def _loss_state(self, config: PantherConfig, positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=config.demo_auto.loss_cooldown_hours)
        state: dict[str, dict[str, Any]] = {}
        for position in sorted(positions, key=lambda item: str(item.get("closed_at") or ""), reverse=True):
            if position.get("status") != "closed":
                continue
            symbol = str(position.get("symbol") or "").upper()
            record = state.setdefault(symbol, {"recent_loss": False, "consecutive_losses": 0, "latest_closed_at": None})
            if float(position.get("pnl") or 0.0) >= 0:
                record["streak_closed"] = True
                continue
            closed_at = self._parse_time(position.get("closed_at"))
            if closed_at and closed_at >= cutoff:
                record["recent_loss"] = True
                if record["latest_closed_at"] is None:
                    record["latest_closed_at"] = closed_at.isoformat()
            if not record.get("streak_closed"):
                record["consecutive_losses"] = int(record["consecutive_losses"]) + 1
        return state

    def _cooldown_reason(
        self,
        config: PantherConfig,
        symbol: str,
        loss_state: dict[str, dict[str, Any]],
    ) -> str | None:
        record = loss_state.get(symbol.upper())
        if not record:
            return None
        if record.get("recent_loss"):
            return (
                f"Post-loss cooldown active for {symbol}; waiting "
                f"{config.demo_auto.loss_cooldown_hours}h after latest demo loss"
            )
        return None

    def _volatility_guard(self, config: PantherConfig, candles: list[Any]) -> str | None:
        if len(candles) < 25:
            return None
        recent = candles[-1].high - candles[-1].low
        baseline = sum(candle.high - candle.low for candle in candles[-21:-1]) / 20
        if baseline <= 0:
            return None
        if recent > baseline * config.demo_auto.volatility_spike_multiplier:
            return "Volatility spike guard blocked demo entry"
        return None

    def _temporal_gate(
        self,
        config: PantherConfig,
        symbol: str,
        signal_time: datetime,
        positions: list[dict[str, Any]],
    ) -> str | None:
        hour = signal_time.astimezone(timezone.utc).hour
        samples = [
            position for position in positions
            if self._same_symbol(position, symbol)
            and position.get("status") == "closed"
            and self._position_hour(position) == hour
        ]
        if len(samples) < config.demo_auto.temporal_min_samples:
            return None
        wins = len([position for position in samples if float(position.get("pnl") or 0.0) > 0])
        win_rate = wins / len(samples)
        net_pnl = sum(float(position.get("pnl") or 0.0) for position in samples)
        if net_pnl < 0 and win_rate < config.demo_auto.temporal_min_win_rate:
            return (
                f"Temporal edge blocked {symbol} at UTC hour {hour}; "
                f"{win_rate:.0%} win rate from {len(samples)} closed demos"
            )
        return None

    def _symbol_performance_gate(
        self,
        config: PantherConfig,
        symbol: str,
        positions: list[dict[str, Any]],
    ) -> str | None:
        closed = [
            position for position in positions
            if self._same_symbol(position, symbol) and position.get("status") == "closed"
        ]
        if len(closed) < config.demo_auto.symbol_min_closed_trades:
            return None
        net_pnl = sum(float(position.get("pnl") or 0.0) for position in closed)
        if not math.isfinite(net_pnl):
            return f"Symbol performance data is invalid for {symbol}"
        if net_pnl < config.demo_auto.symbol_min_net_pnl:
            return f"Symbol performance gate blocked {symbol}; net P/L {net_pnl:.2f} is below required {config.demo_auto.symbol_min_net_pnl:.2f}"
        return None

    def _bayesian_edge_probability(
        self,
        config: PantherConfig,
        symbol: str,
        positions: list[dict[str, Any]],
    ) -> float:
        closed = [
            position for position in positions
            if self._same_symbol(position, symbol) and position.get("status") == "closed"
        ]
        wins = len([position for position in closed if float(position.get("pnl") or 0.0) > 0])
        losses = len([position for position in closed if float(position.get("pnl") or 0.0) < 0])
        alpha = config.demo_auto.bayes_prior_wins + wins
        beta = config.demo_auto.bayes_prior_losses + losses
        return round(alpha / (alpha + beta), 4)

    def _adjust_signal_confidence(
        self,
        config: PantherConfig,
        signal: TradeSignal,
        edge_probability: float,
    ) -> TradeSignal:
        return replace(
            signal,
            rationale=(
                *signal.rationale,
                f"Historical smoothed win frequency {edge_probability:.0%}; not a calibrated forecast or technical score.",
            ),
        )

    def _kelly_volume(self, config: PantherConfig, signal: TradeSignal) -> float:
        """Compatibility name; heuristic signal scores are not valid Kelly odds."""
        return config.demo_auto.demo_order_volume

    def _goal_adjusted_volume(
        self,
        config: PantherConfig,
        signal: TradeSignal,
        volume: float,
        goal_pressure: dict[str, Any],
        scout_mode: bool,
    ) -> float:
        if volume <= 0:
            return 0.0
        if goal_pressure["daily_progress"] < 0:
            return round(max(volume * 0.5, 0.001), 4)
        if scout_mode:
            return round(min(volume, config.demo_auto.demo_order_volume * config.demo_auto.scout_volume_multiplier), 4)
        if signal.confidence >= config.risk.min_confidence + 0.15 and goal_pressure["daily_progress"] < 0.8:
            return round(min(volume * 1.15, config.demo_auto.demo_order_volume), 4)
        if goal_pressure["weekly_progress"] >= 0.85 or goal_pressure["monthly_progress"] >= 0.85:
            return round(max(volume * 0.65, 0.001), 4)
        return round(min(volume, config.demo_auto.demo_order_volume), 4)

    def _read_positions(self) -> list[dict[str, Any]]:
        positions = []
        for line in self.positions_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                positions.append(json.loads(line))
        return positions

    def _parse_time(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _position_hour(self, position: dict[str, Any]) -> int | None:
        parsed = self._parse_time(position.get("opened_at") or position.get("closed_at"))
        return parsed.astimezone(timezone.utc).hour if parsed else None

    def _same_symbol(self, position: dict[str, Any], symbol: str) -> bool:
        position_key = self._symbol_key(str(position.get("symbol") or ""))
        symbol_key = self._symbol_key(symbol)
        return position_key == symbol_key or position_key.startswith(symbol_key) or symbol_key.startswith(position_key)

    def _write_state(self, cycle: DemoAutoCycle, running: bool = False) -> None:
        if cycle.status == "blocked" and cycle.reasons:
            message = f"Blocked: {cycle.reasons[0]}"
        else:
            message = f"Last cycle placed {cycle.placed} demo orders across {cycle.scanned} scanned markets."
        payload = {
            "running": running,
            "lastCycle": cycle.to_dict(),
            "message": message,
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class DemoAutoRunner:
    def __init__(self, trader: DemoAutoTrader, interval_seconds: int) -> None:
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
            self._thread = Thread(target=self._loop, name="panther-demo-auto", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        return self.status()

    def status(self) -> dict[str, Any]:
        state = self.trader.latest_state()
        state["running"] = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        return state

    def run_once(self) -> dict[str, Any]:
        cycle = self.trader.run_cycle()
        message = (
            f"Blocked: {cycle.reasons[0]}"
            if cycle.status == "blocked" and cycle.reasons
            else "Manual demo cycle completed."
        )
        return {"running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()), "lastCycle": cycle.to_dict(), "message": message}

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
