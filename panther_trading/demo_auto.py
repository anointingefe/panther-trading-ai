from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from panther_trading.brokers import create_broker
from panther_trading.brokers.base import Broker
from panther_trading.config import PantherConfig, load_config
from panther_trading.data import StaticSentimentCollector
from panther_trading.data.markets import market_universe
from panther_trading.models import OrderRequest, OrderResult, OrderStatus, SignalSide
from panther_trading.risk import RiskManager
from panther_trading.strategies import SmaSentimentStrategy


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
    ) -> None:
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.broker_kind = broker_kind
        self._broker = broker
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def run_cycle(self) -> DemoAutoCycle:
        started_at = datetime.now(timezone.utc)
        config = load_config(self.config_path)
        broker = self._broker or create_broker(self.broker_kind)
        status = broker.get_status()
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

        decisions: list[DemoAutoDecision] = []
        available = set(broker.list_symbols())
        symbols = self._symbols_to_scan(config, available)
        for symbol in symbols:
            decisions.append(self._evaluate_symbol(config, broker, symbol))
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
        selected = [symbol for symbol in configured if symbol in available]
        seen = set(selected)
        broker_only = sorted(symbol for symbol in available if symbol not in seen and self._is_tradeable_symbol(symbol))
        selected.extend(broker_only)
        return selected[: config.demo_auto.max_symbols_per_cycle]

    def _is_tradeable_symbol(self, symbol: str) -> bool:
        clean = symbol.strip()
        if not clean or len(clean) > 24:
            return False
        return any(char.isalpha() for char in clean)

    def _evaluate_symbol(self, config: PantherConfig, broker: Broker, symbol: str) -> DemoAutoDecision:
        total_open = broker.count_open_positions()
        symbol_open = broker.count_open_positions(symbol)
        if total_open >= config.risk.max_open_positions:
            return self._blocked(symbol, "hold", 0.0, "Maximum total demo positions reached")
        if symbol_open >= config.risk.max_positions_per_symbol:
            return self._blocked(symbol, "hold", 0.0, "Maximum demo positions reached for symbol")

        candles = broker.get_candles(symbol, config.app.timeframe, config.app.candles)
        sentiment = StaticSentimentCollector().collect(symbol)
        signal = SmaSentimentStrategy(config.strategy).generate(symbol, candles, sentiment)
        risk = RiskManager(config.risk).evaluate(signal, open_positions=total_open)
        if not risk.allowed:
            return self._blocked(symbol, signal.side.value, signal.confidence, risk.reason)

        result = broker.place_order(
            OrderRequest(
                symbol=symbol,
                side=signal.side,
                volume=config.demo_auto.demo_order_volume,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                comment="PANTHER demo incubation",
            )
        )
        action = "placed" if result.status in {OrderStatus.ACCEPTED, OrderStatus.SIMULATED} else "blocked"
        return DemoAutoDecision(
            symbol=symbol,
            action=action,
            side=signal.side.value,
            confidence=signal.confidence,
            reason="Demo incubation order placed" if action == "placed" else result.message,
            order_status=result.status.value,
            order_message=result.message,
            broker_order_id=result.broker_order_id,
        )

    def _blocked(self, symbol: str, side: str, confidence: float, reason: str) -> DemoAutoDecision:
        return DemoAutoDecision(
            symbol=symbol,
            action="blocked",
            side=side,
            confidence=confidence,
            reason=reason,
        )

    def _write_state(self, cycle: DemoAutoCycle, running: bool = False) -> None:
        payload = {
            "running": running,
            "lastCycle": cycle.to_dict(),
            "message": f"Last cycle placed {cycle.placed} demo orders across {cycle.scanned} scanned markets.",
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
        return {"running": False, "lastCycle": cycle.to_dict(), "message": "Manual demo cycle completed."}

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.trader.run_cycle()
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
