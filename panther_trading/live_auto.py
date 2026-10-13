from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from panther_trading.brokers import create_broker
from panther_trading.brokers.base import Broker
from panther_trading.beast_mode import BeastModeStore, DEFAULT_BEAST_MODE, apply_beast_mode
from panther_trading.config import load_config
from panther_trading.data import StaticSentimentCollector
from panther_trading.demo_auto import DemoAutoTrader
from panther_trading.execution import ExecutionEngine
from panther_trading.goals import GoalTracker
from panther_trading.live_guard import LiveTradingGate
from panther_trading.models import OrderRequest, OrderStatus, SignalSide, TradeSignal
from panther_trading.positions import PaperPositionBook
from panther_trading.risk import RiskManager
from panther_trading.strategies import SmaSentimentStrategy
from panther_trading.validation import EdgeValidationGate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOALS = PROJECT_ROOT / "var/trading_goals.json"
DEFAULT_LIVE_AUTO = PROJECT_ROOT / "var/live_auto_state.json"


@dataclass(frozen=True)
class LiveAutoStatus:
    built: bool
    armed: bool
    enabled: bool
    message: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "built": self.built,
            "armed": self.armed,
            "enabled": self.enabled,
            "message": self.message,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LiveAutoDecision:
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
class LiveAutoCycle:
    status: str
    started_at: str
    finished_at: str
    broker_mode: str
    scanned: int
    placed: int
    blocked: int
    decisions: tuple[LiveAutoDecision, ...]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


class LiveAutoTrader:
    """Live execution path.

    This is deliberately stricter than the demo runner. It exists so the live
    path can be tested and audited, but it refuses to place orders until the
    live guard is fully armed.
    """

    def __init__(
        self,
        config_path: str | Path,
        positions_path: str | Path,
        state_path: str | Path = DEFAULT_LIVE_AUTO,
        goals_path: str | Path = DEFAULT_GOALS,
        beast_mode_path: str | Path = DEFAULT_BEAST_MODE,
        broker: Broker | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.positions_path = Path(positions_path)
        self.state_path = Path(state_path)
        self.goals_path = Path(goals_path)
        self.beast_mode_path = Path(beast_mode_path)
        self._broker = broker
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        config = apply_beast_mode(config, BeastModeStore(self.beast_mode_path).load().enabled, self._positions())
        edge = EdgeValidationGate(config.validation).evaluate(self._positions()).to_dict()
        readiness = LiveTradingGate(config.execution).readiness(
            broker_status=self._broker_status(),
            approval_status=None,
            requested_volume=config.execution.default_volume,
            edge_validation_status=edge["status"],
            unlock_phrase=None,
        )
        payload = LiveAutoStatus(
            built=True,
            armed=readiness.armed,
            enabled=config.execution.allow_live_trading,
            message=(
                "Live runner is built but locked by safety gates."
                if not readiness.armed
                else "Live runner can execute only explicitly approved signals."
            ),
            reasons=readiness.reasons,
        ).to_dict()
        latest = self.latest_state()
        payload["running"] = bool(latest.get("running", False))
        payload["lastCycle"] = latest.get("lastCycle")
        return payload

    def latest_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "running": False,
                "lastCycle": None,
                "message": "Live auto runner has not run yet.",
            }
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def run_cycle(self, unlock_phrase: str | None = None) -> LiveAutoCycle:
        started_at = datetime.now(timezone.utc)
        config = load_config(self.config_path)
        positions = self._positions()
        config = apply_beast_mode(config, BeastModeStore(self.beast_mode_path).load().enabled, positions)
        edge = EdgeValidationGate(config.validation).evaluate(positions).to_dict()
        try:
            broker = self._broker or create_broker("mt5")
            broker_status = self._broker_status_from_broker(broker)
        except Exception as exc:
            cycle = self._blocked_cycle(started_at, "unavailable", f"Broker setup failed: {exc}")
            self._write_state(cycle)
            return cycle

        equity = broker_status.get("equity")
        if equity is None or not math.isfinite(equity) or equity <= 0:
            cycle = self._blocked_cycle(started_at, str(broker_status.get("mode") or "unknown"), "Broker equity is unavailable or invalid.")
            self._write_state(cycle)
            return cycle
        config = replace(config, risk=replace(config.risk, account_equity=equity))
        requested_volume = min(config.demo_auto.demo_order_volume, config.execution.max_live_volume)
        readiness = LiveTradingGate(config.execution).readiness(
            broker_status=broker_status,
            approval_status=None,
            requested_volume=requested_volume,
            edge_validation_status=edge["status"],
            unlock_phrase=unlock_phrase,
        )
        if not readiness.armed:
            cycle = self._blocked_cycle(started_at, str(broker_status.get("mode") or "unknown"), " ".join(readiness.reasons))
            self._write_state(cycle)
            return cycle

        helper = DemoAutoTrader(
            self.config_path,
            self.state_path,
            broker=broker,
            positions_path=self.positions_path,
            goals_path=self.goals_path,
            beast_mode_path=self.beast_mode_path,
        )
        available = set(broker.list_symbols())
        symbols = helper._symbols_to_scan(config, available)
        goal_pressure = GoalTracker(self.goals_path).goal_pressure(positions)
        decisions: list[LiveAutoDecision] = []
        placed_this_cycle = 0
        for symbol in symbols:
            if placed_this_cycle >= config.risk.max_open_positions:
                decisions.append(self._blocked(symbol, "hold", 0.0, "Maximum live orders for this cycle reached"))
                continue
            try:
                decision = self._evaluate_symbol(config, broker, helper, symbol, goal_pressure, positions)
            except Exception as exc:
                decision = self._blocked(symbol, "hold", 0.0, f"Symbol skipped: {exc}")
            if decision.action == "placed":
                placed_this_cycle += 1
            decisions.append(decision)

        decisions = sorted(decisions, key=lambda decision: (decision.action != "placed", -decision.confidence, decision.symbol))
        placed = len([decision for decision in decisions if decision.action == "placed"])
        cycle = LiveAutoCycle(
            status="active" if decisions else "idle",
            started_at=started_at.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            broker_mode=str(broker_status.get("mode") or "unknown"),
            scanned=len(decisions),
            placed=placed,
            blocked=len(decisions) - placed,
            decisions=tuple(decisions),
        )
        self._write_state(cycle)
        return cycle

    def execute_approved_signal(
        self,
        journal_entry: dict[str, Any],
        unlock_phrase: str | None = None,
    ) -> dict[str, Any]:
        config = load_config(self.config_path)
        positions = self._positions()
        config = apply_beast_mode(config, BeastModeStore(self.beast_mode_path).load().enabled, positions)
        edge = EdgeValidationGate(config.validation).evaluate(positions).to_dict()
        readiness = LiveTradingGate(config.execution).readiness(
            broker_status=self._broker_status("mt5"),
            approval_status=str(journal_entry.get("approval_status")),
            requested_volume=config.execution.default_volume,
            edge_validation_status=edge["status"],
            unlock_phrase=unlock_phrase,
        )
        if not readiness.armed:
            return {
                "status": "blocked",
                "message": "Live execution refused by guard.",
                "reasons": list(readiness.reasons),
            }

        signal = TradeSignal(
            symbol=str(journal_entry["symbol"]),
            side=SignalSide(str(journal_entry["side"])),
            confidence=float(journal_entry["confidence"]),
            entry=float(journal_entry["entry"]),
            stop_loss=float(journal_entry["stop_loss"]),
            take_profit=float(journal_entry["take_profit"]),
            rationale=tuple(journal_entry.get("rationale") or ()),
            generated_at=datetime.now(timezone.utc),
        )
        broker = self._broker or create_broker("mt5")
        equity = broker.get_status().equity
        if equity is None or not math.isfinite(equity) or equity <= 0:
            return {"status": "blocked", "message": "Broker equity is unavailable or invalid.", "brokerOrderId": None}
        config = replace(config, risk=replace(config.risk, account_equity=equity))
        risk_amount = equity * (config.risk.max_risk_per_trade_pct / 100)
        volume = broker.calculate_position_volume(
            signal.symbol,
            signal.side,
            signal.entry,
            signal.stop_loss,
            risk_amount,
            config.execution.max_live_volume,
        )
        if volume <= 0:
            return {"status": "blocked", "message": "Live execution refused: calculated volume is zero.", "brokerOrderId": None}
        result = ExecutionEngine(broker, RiskManager(config.risk), config.execution).execute(signal, volume=volume)
        return {"status": result.status.value, "message": result.message, "brokerOrderId": result.broker_order_id}

    def _evaluate_symbol(
        self,
        config: Any,
        broker: Broker,
        helper: DemoAutoTrader,
        symbol: str,
        goal_pressure: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> LiveAutoDecision:
        if goal_pressure["daily_target_met"]:
            return self._blocked(symbol, "hold", 0.0, "Daily target reached; live auto is protecting gains")
        if broker.count_open_positions() >= config.risk.max_open_positions:
            return self._blocked(symbol, "hold", 0.0, "Maximum total live positions reached")
        if broker.count_open_positions(symbol) >= config.risk.max_positions_per_symbol:
            return self._blocked(symbol, "hold", 0.0, "Maximum live positions reached for symbol")

        cooldown = helper._cooldown_reason(config, symbol, helper._loss_state(config, positions))
        if cooldown:
            return self._blocked(symbol, "hold", 0.0, cooldown)
        candles = broker.get_candles(symbol, config.app.timeframe, config.app.candles)
        volatility = helper._volatility_guard(config, candles)
        if volatility:
            return self._blocked(symbol, "hold", 0.0, volatility)
        signal = SmaSentimentStrategy(config.strategy).generate(symbol, candles, StaticSentimentCollector().collect(symbol))
        temporal = helper._temporal_gate(config, symbol, signal.generated_at, positions)
        if temporal:
            return self._blocked(symbol, signal.side.value, signal.confidence, temporal)
        performance = helper._symbol_performance_gate(config, symbol, positions)
        if performance:
            return self._blocked(symbol, signal.side.value, signal.confidence, performance)
        edge_probability = helper._bayesian_edge_probability(config, symbol, positions)
        signal = helper._adjust_signal_confidence(config, signal, edge_probability)
        risk = RiskManager(config.risk).evaluate(
            signal,
            open_positions=broker.count_open_positions(),
            daily_pnl=GoalTracker(self.goals_path).report(positions)["progress"]["daily"]["netPnl"],
        )
        if not risk.allowed:
            return self._blocked(symbol, signal.side.value, signal.confidence, risk.reason, edge_probability=edge_probability)

        volume = self._live_volume(config, broker, signal, goal_pressure)
        if volume <= 0:
            return self._blocked(symbol, signal.side.value, signal.confidence, "Calculated live volume is zero", edge_probability=edge_probability)

        result = broker.place_order(
            OrderRequest(
                symbol=symbol,
                side=signal.side,
                volume=volume,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                comment="PANTHER live auto",
            )
        )
        action = "placed" if result.status == OrderStatus.ACCEPTED else "blocked"
        return LiveAutoDecision(
            symbol=symbol,
            action=action,
            side=signal.side.value,
            confidence=signal.confidence,
            reason="Live auto order placed" if action == "placed" else result.message,
            order_status=result.status.value,
            order_message=result.message,
            broker_order_id=result.broker_order_id,
            volume=volume,
            edge_probability=edge_probability,
        )

    def _live_volume(
        self,
        config: Any,
        broker: Broker,
        signal: TradeSignal,
        goal_pressure: dict[str, Any],
    ) -> float:
        equity = broker.get_status().equity
        if equity is None or not math.isfinite(equity) or equity <= 0:
            return 0.0
        risk_amount = equity * (config.risk.max_risk_per_trade_pct / 100)
        if goal_pressure["daily_progress"] < 0:
            risk_amount *= 0.5
        elif goal_pressure["weekly_progress"] >= 0.85 or goal_pressure["monthly_progress"] >= 0.85:
            risk_amount *= 0.65
        return broker.calculate_position_volume(
            signal.symbol,
            signal.side,
            signal.entry,
            signal.stop_loss,
            risk_amount,
            config.execution.max_live_volume,
        )

    def _positions(self) -> list[dict[str, Any]]:
        return PaperPositionBook(self.positions_path).latest(limit=1000) if self.positions_path.exists() else []

    def _blocked_cycle(self, started_at: datetime, broker_mode: str, reason: str) -> LiveAutoCycle:
        return LiveAutoCycle(
            status="blocked",
            started_at=started_at.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            broker_mode=broker_mode,
            scanned=0,
            placed=0,
            blocked=1,
            decisions=(),
            reasons=(reason,),
        )

    def _blocked(
        self,
        symbol: str,
        side: str,
        confidence: float,
        reason: str,
        edge_probability: float | None = None,
    ) -> LiveAutoDecision:
        return LiveAutoDecision(
            symbol=symbol,
            action="blocked",
            side=side,
            confidence=confidence,
            reason=reason,
            edge_probability=edge_probability,
        )

    def _broker_status(self, kind: str | None = None) -> dict[str, Any]:
        try:
            broker = self._broker or create_broker(kind or "mt5")
            return self._broker_status_from_broker(broker)
        except Exception as exc:
            return {
                "name": kind or "Configured broker",
                "connected": False,
                "mode": "unavailable",
                "message": str(exc),
            }

    def _broker_status_from_broker(self, broker: Broker) -> dict[str, Any]:
        status = broker.get_status()
        return {
            "name": status.name,
            "connected": status.connected,
            "mode": status.mode,
            "account_login": status.account_login,
            "account_server": status.account_server,
            "balance": status.balance,
            "equity": status.equity,
            "open_positions": status.open_positions,
            "symbols_total": status.symbols_total,
            "message": status.message,
        }

    def _write_state(self, cycle: LiveAutoCycle, running: bool = False) -> None:
        message = (
            f"Blocked: {cycle.reasons[0]}"
            if cycle.status == "blocked" and cycle.reasons
            else f"Last live cycle placed {cycle.placed} order(s) across {cycle.scanned} scanned markets."
        )
        self.state_path.write_text(
            json.dumps({"running": running, "lastCycle": cycle.to_dict(), "message": message}, indent=2),
            encoding="utf-8",
        )


class LiveAutoRunner:
    def __init__(self, trader: LiveAutoTrader, interval_seconds: int) -> None:
        self.trader = trader
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._unlock_phrase: str | None = None

    def start(self, unlock_phrase: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._unlock_phrase = unlock_phrase
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._thread = Thread(target=self._loop, name="panther-live-auto", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        return self.status()

    def status(self) -> dict[str, Any]:
        state = self.trader.status()
        state["running"] = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        return state

    def run_once(self, unlock_phrase: str | None = None) -> dict[str, Any]:
        cycle = self.trader.run_cycle(unlock_phrase=unlock_phrase)
        message = (
            f"Blocked: {cycle.reasons[0]}"
            if cycle.status == "blocked" and cycle.reasons
            else "Manual live cycle completed."
        )
        return {"running": False, "lastCycle": cycle.to_dict(), "message": message}

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.trader.run_cycle(unlock_phrase=self._unlock_phrase)
            time.sleep(self.interval_seconds)


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
