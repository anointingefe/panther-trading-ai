from __future__ import annotations

from abc import ABC, abstractmethod

from panther_trading.models import BrokerStatus, Candle, OrderRequest, OrderResult, OrderStatus


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
