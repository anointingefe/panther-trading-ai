from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from panther_trading.brokers import create_broker
from panther_trading.brokers.base import Broker
from panther_trading.config import PantherConfig, load_config
from panther_trading.data import StaticSentimentCollector
from panther_trading.data.markets import market_universe
from panther_trading.models import OrderRequest, OrderStatus, TradeSignal
from panther_trading.risk import RiskManager
from panther_trading.strategies import SmaSentimentStrategy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POSITIONS = PROJECT_ROOT / "var/paper_positions.jsonl"


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
    ) -> None:
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.positions_path = Path(positions_path)
        self.broker_kind = broker_kind
        self._broker = broker
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def run_cycle(self) -> DemoAutoCycle:
        started_at = datetime.now(timezone.utc)
        config = load_config(self.config_path)
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

        decisions: list[DemoAutoDecision] = []
        available = set(broker.list_symbols())
        symbols = self._symbols_to_scan(config, available)
        positions = self._read_positions() if self.positions_path.exists() else []
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
        temporal = self._temporal_gate(config, symbol, signal.generated_at, positions)
        if temporal:
            return self._blocked(symbol, signal.side.value, signal.confidence, temporal)
        edge_probability = self._bayesian_edge_probability(config, symbol, positions)
        signal = self._adjust_signal_confidence(config, signal, edge_probability)
        demo_risk = replace(
            config.risk,
            max_open_positions=config.demo_auto.max_open_positions,
            max_positions_per_symbol=config.demo_auto.max_positions_per_symbol,
        )
        risk = RiskManager(demo_risk).evaluate(signal, open_positions=total_open)
        if not risk.allowed:
            return self._blocked(symbol, signal.side.value, signal.confidence, risk.reason)
        volume = self._kelly_volume(config, signal)

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
        return DemoAutoDecision(
            symbol=symbol,
            action=action,
            side=signal.side.value,
            confidence=signal.confidence,
            reason="Demo incubation order placed" if action == "placed" else result.message,
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
        if int(record.get("consecutive_losses") or 0) >= config.demo_auto.max_consecutive_symbol_losses:
            return f"Symbol locked after {record['consecutive_losses']} consecutive demo loss(es)"
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
        if win_rate < config.demo_auto.temporal_min_win_rate:
            return (
                f"Temporal edge blocked {symbol} at UTC hour {hour}; "
                f"{win_rate:.0%} win rate from {len(samples)} closed demos"
            )
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
        weight = min(max(config.demo_auto.bayes_confidence_weight, 0.0), 1.0)
        confidence = round((signal.confidence * (1 - weight)) + (edge_probability * weight), 4)
        return replace(
            signal,
            confidence=confidence,
            rationale=(
                *signal.rationale,
                f"Bayesian demo edge probability adjusted confidence to {confidence:.0%}.",
            ),
        )

    def _kelly_volume(self, config: PantherConfig, signal: TradeSignal) -> float:
        risk = abs(signal.entry - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry)
        if risk <= 0 or reward <= 0:
            return 0.0
        b = reward / risk
        p = min(max(signal.confidence, 0.0), 1.0)
        q = 1 - p
        kelly = max(((p * b) - q) / b, 0.0)
        cap = config.demo_auto.max_kelly_fraction
        if cap <= 0:
            return config.demo_auto.demo_order_volume
        scale = min(kelly, cap) / cap
        minimum = config.demo_auto.demo_order_volume * 0.25
        volume = max(config.demo_auto.demo_order_volume * scale, minimum)
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
