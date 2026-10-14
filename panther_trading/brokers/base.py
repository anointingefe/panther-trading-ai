from __future__ import annotations

from abc import ABC, abstractmethod
import math

from panther_trading.models import BrokerStatus, Candle, OrderRequest, OrderResult, OrderStatus, SignalSide


class Broker(ABC):
    @abstractmethod
    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> BrokerStatus:
        raise NotImplementedError

    @abstractmethod
    def list_symbols(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def count_open_positions(self, symbol: str | None = None) -> int:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError

    def open_positions(self) -> list[dict]:
        return []

    def close_position(self, position_id: str, reason: str = "exit_manager") -> OrderResult:
        return OrderResult(OrderStatus.REJECTED, f"Broker cannot close position {position_id}: {reason}")

    def estimate_position_risk(
        self,
        symbol: str,
        side: SignalSide,
        volume: float,
        entry: float,
        stop_loss: float,
    ) -> float:
        """Estimate money at risk if stop-loss is reached.

        Native brokers should override this with their contract/tick-value aware
        calculation. The fallback is only suitable for simple simulated brokers.
        """
        values = (volume, entry, stop_loss)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            return 0.0
        if side == SignalSide.BUY and stop_loss >= entry:
            return 0.0
        if side == SignalSide.SELL and stop_loss <= entry:
            return 0.0
        return abs(entry - stop_loss) * volume

    def calculate_position_volume(
        self,
        symbol: str,
        side: SignalSide,
        entry: float,
        stop_loss: float,
        risk_amount: float,
        max_volume: float,
    ) -> float:
        if risk_amount <= 0 or max_volume <= 0:
            return 0.0
        distance = abs(entry - stop_loss)
        if distance <= 0:
            return 0.0
        return round(min(max_volume, risk_amount / distance), 4)

    def execution_preflight(
        self,
        symbol: str,
        side: SignalSide,
        requested_volume: float,
        planned_entry: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        """Safely validate an intended order without sending it to the broker.

        Broker adapters should override this when they can inspect native quote,
        symbol, margin, and stop-level constraints. The base implementation is
        deliberately marked non-native so it can never satisfy the execution
        green flag by itself.
        """
        blockers: list[str] = []
        if side not in {SignalSide.BUY, SignalSide.SELL}:
            blockers.append("Order side is not executable.")
        if requested_volume <= 0:
            blockers.append("Calculated volume must be greater than zero.")
        bracket_valid = (
            stop_loss < planned_entry < take_profit
            if side == SignalSide.BUY
            else take_profit < planned_entry < stop_loss
        )
        if not bracket_valid:
            blockers.append("Stop-loss/take-profit bracket is invalid at the planned entry.")
        return {
            "broker_native": False,
            "executable": not blockers,
            "symbol": symbol,
            "side": side.value,
            "planned_entry": planned_entry,
            "market_price": planned_entry,
            "bid": None,
            "ask": None,
            "spread_points": None,
            "point": None,
            "quote_age_seconds": None,
            "stop_level_points": None,
            "stop_distance_points": None,
            "target_distance_points": None,
            "requested_volume": requested_volume,
            "normalized_volume": requested_volume,
            "volume_valid": requested_volume > 0,
            "bracket_valid": bracket_valid,
            "order_check_retcode": None,
            "order_check_comment": "Broker-native order_check unavailable.",
            "blockers": blockers,
        }
