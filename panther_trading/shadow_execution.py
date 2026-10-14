from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from panther_trading.brokers import create_broker
from panther_trading.brokers.base import Broker
from panther_trading.config import load_config
from panther_trading.data import StaticSentimentCollector
from panther_trading.demo_auto import DemoAutoTrader
from panther_trading.goals import GoalTracker
from panther_trading.live_ledger import LivePositionLedger
from panther_trading.models import SignalSide, TradeSignal
from panther_trading.positions import PaperPositionBook
from panther_trading.preflight import execution_preflight
from panther_trading.reconciliation import BrokerReconciler
from panther_trading.risk import RiskManager
from panther_trading.strategies import SmaSentimentStrategy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHADOW_STATE = PROJECT_ROOT / "var/shadow_execution.json"
DEFAULT_LIVE_LEDGER = PROJECT_ROOT / "var/live_positions.json"
DEFAULT_POSITIONS = PROJECT_ROOT / "var/paper_positions.jsonl"
DEFAULT_GOALS = PROJECT_ROOT / "var/trading_goals.json"


@dataclass(frozen=True)
class ShadowDecision:
    symbol: str
    action: str
    side: str
    confidence: float
    reason: str
    sample_id: str | None = None
    volume: float | None = None
    market_price: float | None = None


@dataclass(frozen=True)
class ShadowCycle:
    status: str
    started_at: str
    finished_at: str
    broker_mode: str
    scanned: int
    shadowed: int
    blocked: int
    decisions: tuple[ShadowDecision, ...]
    reconciliation: dict[str, Any]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowExecutionStore:
    def __init__(self, path: str | Path = DEFAULT_SHADOW_STATE, max_samples: int = 1000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_samples = max(max_samples, 50)
        self._lock = Lock()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._load()

    def append_cycle(
        self,
        cycle: ShadowCycle,
        samples: list[dict[str, Any]],
        reconciliation: dict[str, Any],
        running: bool = False,
    ) -> None:
        with self._lock:
            state = self._load()
            existing = list(state.get("samples", []))
            existing.extend(samples)
            history = list(state.get("reconciliationHistory", []))
            history.append(reconciliation)
            payload = {
                "running": running,
                "lastCycle": cycle.to_dict(),
                "samples": existing[-self.max_samples :],
                "reconciliationHistory": history[-max(self.max_samples, 100) :],
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            self._write(payload)

    def resolve_samples(self, broker: Broker, max_observation_minutes: int) -> int:
        with self._lock:
            state = self._load()
            samples = list(state.get("samples", []))
            changed = 0
            by_symbol: dict[str, list[dict[str, Any]]] = {}
            for sample in samples:
                if sample.get("status") == "observing":
                    by_symbol.setdefault(str(sample.get("symbol") or ""), []).append(sample)

            for symbol, pending in by_symbol.items():
                try:
                    candles = broker.get_candles(symbol, "M5", 120)
                except Exception:
                    continue
                for sample in pending:
                    if self._resolve_one(sample, candles, max_observation_minutes):
                        changed += 1

            if changed:
                state["samples"] = samples[-self.max_samples :]
                state["updatedAt"] = datetime.now(timezone.utc).isoformat()
                self._write(state)
            return changed

    def _resolve_one(self, sample: dict[str, Any], candles: list[Any], max_minutes: int) -> bool:
        try:
            generated = datetime.fromisoformat(str(sample["generated_at"]))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            entry = float(sample["market_price"])
            stop = float(sample["stop_loss"])
            target = float(sample["take_profit"])
            side = str(sample["side"])
        except (KeyError, TypeError, ValueError):
            return False
        relevant = [candle for candle in candles if candle.time > generated]
        for candle in relevant:
            if side == "buy":
                hit_stop = candle.low <= stop
                hit_target = candle.high >= target
            else:
                hit_stop = candle.high >= stop
                hit_target = candle.low <= target
            if hit_stop and hit_target:
                sample.update({"status": "ambiguous", "resolved_at": candle.time.isoformat(), "outcome_r": None})
                return True
            if hit_stop:
                sample.update({"status": "lost", "resolved_at": candle.time.isoformat(), "outcome_r": -1.0})
                return True
            if hit_target:
                reward = abs(target - entry)
                risk = abs(entry - stop)
                outcome_r = round(reward / risk, 4) if risk > 0 else None
                sample.update({"status": "won", "resolved_at": candle.time.isoformat(), "outcome_r": outcome_r})
                return True

        if datetime.now(timezone.utc) - generated >= timedelta(minutes=max(max_minutes, 1)) and relevant:
            last = relevant[-1]
            risk = abs(entry - stop)
            direction = 1 if side == "buy" else -1
            outcome_r = round(((last.close - entry) * direction) / risk, 4) if risk > 0 else None
            sample.update({"status": "expired", "resolved_at": last.time.isoformat(), "outcome_r": outcome_r})
            return True
        return False

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"running": False, "lastCycle": None, "samples": [], "reconciliationHistory": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"running": False, "lastCycle": None, "samples": [], "reconciliationHistory": []}
        return payload if isinstance(payload, dict) else {"running": False, "lastCycle": None, "samples": [], "reconciliationHistory": []}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class ShadowExecutionTrader:
    """Run Panther's real broker preflight path without ever placing an order."""

    def __init__(
        self,
        config_path: str | Path,
        positions_path: str | Path = DEFAULT_POSITIONS,
        state_path: str | Path = DEFAULT_SHADOW_STATE,
        goals_path: str | Path = DEFAULT_GOALS,
        live_ledger_path: str | Path = DEFAULT_LIVE_LEDGER,
        broker: Broker | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.positions_path = Path(positions_path)
        self.state_path = Path(state_path)
        self.goals_path = Path(goals_path)
        self.live_ledger_path = Path(live_ledger_path)
        self._broker = broker
        self._lock = Lock()

    def status(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        state = ShadowExecutionStore(self.state_path, config.shadow_execution.max_samples_retained).state()
        samples = state.get("samples", [])
        return {
            "enabled": config.shadow_execution.enabled,
            "running": bool(state.get("running", False)),
            "samples": len(samples),
            "nativeSamples": len([item for item in samples if item.get("broker_native")]),
            "observing": len([item for item in samples if item.get("status") == "observing"]),
            "lastCycle": state.get("lastCycle"),
            "latestReconciliation": (state.get("reconciliationHistory") or [None])[-1],
        }

    def run_cycle(self) -> ShadowCycle:
        if not self._lock.acquire(blocking=False):
            now = datetime.now(timezone.utc).isoformat()
            return ShadowCycle("blocked", now, now, "unknown", 0, 0, 1, (), {}, ("A shadow cycle is already running.",))
        try:
            return self._run_cycle()
        finally:
            self._lock.release()

    def _run_cycle(self) -> ShadowCycle:
        started = datetime.now(timezone.utc)
        config = load_config(self.config_path)
        if not config.shadow_execution.enabled:
            return self._blocked_cycle(started, "disabled", "Shadow execution is disabled in config.")
        try:
            broker = self._broker or create_broker("mt5")
            broker_status = broker.get_status()
        except Exception as exc:
            return self._blocked_cycle(started, "unavailable", f"Broker setup failed: {exc}")
        if not broker_status.connected:
            return self._blocked_cycle(started, str(broker_status.mode), "Broker is not connected.")
        if broker_status.equity is None or not math.isfinite(broker_status.equity) or broker_status.equity <= 0:
            return self._blocked_cycle(started, str(broker_status.mode), "Broker equity is unavailable or invalid.")

        store = ShadowExecutionStore(self.state_path, config.shadow_execution.max_samples_retained)
        store.resolve_samples(broker, config.shadow_execution.max_observation_minutes)
        ledger = LivePositionLedger(self.live_ledger_path)
        reconciliation = BrokerReconciler().reconcile(ledger, broker).to_dict()

        positions = PaperPositionBook(self.positions_path).latest(limit=1000) if self.positions_path.exists() else []
        helper = DemoAutoTrader(
            self.config_path,
            self.state_path,
            broker=broker,
            positions_path=self.positions_path,
            goals_path=self.goals_path,
        )
        available = set(broker.list_symbols())
        symbols = helper._symbols_to_scan(config, available)[: config.shadow_execution.max_symbols_per_cycle]
        goal_pressure = GoalTracker(self.goals_path).goal_pressure(positions)
        decisions: list[ShadowDecision] = []
        samples: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                decision, sample = self._evaluate_symbol(config, broker, helper, symbol, positions, goal_pressure)
            except Exception as exc:
                decision, sample = self._blocked(symbol, "hold", 0.0, f"Shadow symbol skipped: {exc}"), None
            decisions.append(decision)
            if sample is not None:
                samples.append(sample)

        shadowed = len([item for item in decisions if item.action == "shadowed"])
        blocked = len(decisions) - shadowed
        cycle = ShadowCycle(
            status="active" if decisions else "idle",
            started_at=started.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            broker_mode=str(broker_status.mode),
            scanned=len(decisions),
            shadowed=shadowed,
            blocked=blocked,
            decisions=tuple(sorted(decisions, key=lambda item: (item.action != "shadowed", -item.confidence, item.symbol))),
            reconciliation=reconciliation,
        )
        store.append_cycle(cycle, samples, reconciliation)
        return cycle

    def _evaluate_symbol(
        self,
        config: Any,
        broker: Broker,
        helper: DemoAutoTrader,
        symbol: str,
        positions: list[dict[str, Any]],
        goal_pressure: dict[str, Any],
    ) -> tuple[ShadowDecision, dict[str, Any] | None]:
        candles = broker.get_candles(symbol, config.app.timeframe, config.app.candles)
        volatility = helper._volatility_guard(config, candles)
        if volatility:
            return self._blocked(symbol, "hold", 0.0, volatility), None
        signal = SmaSentimentStrategy(config.strategy).generate(symbol, candles, StaticSentimentCollector().collect(symbol))
        temporal = helper._temporal_gate(config, symbol, signal.generated_at, positions)
        if temporal:
            return self._blocked(symbol, signal.side.value, signal.confidence, temporal), None
        performance = helper._symbol_performance_gate(config, symbol, positions)
        if performance:
            return self._blocked(symbol, signal.side.value, signal.confidence, performance), None
        edge_probability = helper._bayesian_edge_probability(config, symbol, positions)
        signal = helper._adjust_signal_confidence(config, signal, edge_probability)
        daily_pnl = GoalTracker(self.goals_path).report(positions)["progress"]["daily"]["netPnl"]
        risk = RiskManager(config.risk).evaluate(signal, open_positions=broker.count_open_positions(), daily_pnl=daily_pnl)
        if not risk.allowed:
            return self._blocked(symbol, signal.side.value, signal.confidence, risk.reason), None
        if goal_pressure.get("daily_target_met"):
            return self._blocked(symbol, signal.side.value, signal.confidence, "Daily target reached; shadow path mirrors gain protection."), None

        risk_amount = float(broker.get_status().equity) * (config.risk.max_risk_per_trade_pct / 100)
        volume = broker.calculate_position_volume(
            signal.symbol,
            signal.side,
            signal.entry,
            signal.stop_loss,
            risk_amount,
            config.execution.max_live_volume,
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
        quote_age = preflight.get("quote_age_seconds")
        quote_fresh = quote_age is not None and float(quote_age) <= config.shadow_execution.max_quote_age_seconds
        blockers = list(preflight.get("blockers") or [])
        if preflight.get("broker_native") and not quote_fresh:
            blockers.append("Broker quote is stale or has no reliable timestamp.")
        stop_points = preflight.get("stop_distance_points")
        spread_points = preflight.get("spread_points")
        spread_to_stop = None
        if stop_points not in {None, 0} and spread_points is not None:
            spread_to_stop = float(spread_points) / float(stop_points)
            if spread_to_stop > config.shadow_execution.max_spread_to_stop_ratio:
                blockers.append("Spread is too large relative to the planned stop distance.")
        preflight_passed = bool(preflight.get("executable")) and not blockers
        sample_id = f"shadow-{uuid4().hex[:12]}"
        market_price = float(preflight.get("market_price") or signal.entry)
        sample = {
            "id": sample_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": signal.symbol,
            "side": signal.side.value,
            "confidence": signal.confidence,
            "planned_entry": signal.entry,
            "market_price": market_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "risk_amount": round(risk_amount, 2),
            "requested_volume": volume,
            "normalized_volume": preflight.get("normalized_volume"),
            "broker_native": bool(preflight.get("broker_native")),
            "preflight_passed": preflight_passed,
            "quote_fresh": quote_fresh,
            "quote_age_seconds": quote_age,
            "spread_points": spread_points,
            "spread_to_stop_ratio": round(spread_to_stop, 4) if spread_to_stop is not None else None,
            "volume_valid": bool(preflight.get("volume_valid")),
            "bracket_valid": bool(preflight.get("bracket_valid")),
            "order_check_retcode": preflight.get("order_check_retcode"),
            "order_check_comment": preflight.get("order_check_comment"),
            "blockers": blockers,
            "status": "observing" if preflight_passed else "blocked",
            "resolved_at": None,
            "outcome_r": None,
        }
        if not preflight_passed:
            reason = "; ".join(blockers) or "Broker-native preflight did not pass."
            return self._blocked(symbol, signal.side.value, signal.confidence, reason, sample_id, volume, market_price), sample
        return (
            ShadowDecision(
                symbol=symbol,
                action="shadowed",
                side=signal.side.value,
                confidence=signal.confidence,
                reason="Shadow order validated against broker conditions; no order was sent.",
                sample_id=sample_id,
                volume=float(preflight.get("normalized_volume") or volume),
                market_price=market_price,
            ),
            sample,
        )

    def _blocked(
        self,
        symbol: str,
        side: str,
        confidence: float,
        reason: str,
        sample_id: str | None = None,
        volume: float | None = None,
        market_price: float | None = None,
    ) -> ShadowDecision:
        return ShadowDecision(symbol, "blocked", side, confidence, reason, sample_id, volume, market_price)

    def _blocked_cycle(self, started: datetime, mode: str, reason: str) -> ShadowCycle:
        return ShadowCycle(
            status="blocked",
            started_at=started.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            broker_mode=mode,
            scanned=0,
            shadowed=0,
            blocked=1,
            decisions=(),
            reconciliation={},
            reasons=(reason,),
        )


class ShadowExecutionRunner:
    def __init__(self, trader: ShadowExecutionTrader, interval_seconds: int) -> None:
        self.trader = trader
        self.interval_seconds = max(interval_seconds, 1)
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._thread = Thread(target=self._loop, name="panther-shadow-execution", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        return self.status()

    def status(self) -> dict[str, Any]:
        payload = self.trader.status()
        payload["running"] = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        return payload

    def run_once(self) -> dict[str, Any]:
        cycle = self.trader.run_cycle()
        return {
            "running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
            "lastCycle": cycle.to_dict(),
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.trader.run_cycle()
            self._stop.wait(self.interval_seconds)
