from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from panther_trading.brokers.base import Broker
from panther_trading.data.markets import DEFAULT_MARKET_UNIVERSE
from panther_trading.models import BrokerStatus, Candle, OrderRequest, OrderResult, OrderStatus


class SimulatedBroker(Broker):
    """Deterministic broker used for safe local development and tests."""

    def __init__(self) -> None:
        self.orders: list[OrderRequest] = []

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        start = datetime.now(timezone.utc) - timedelta(minutes=15 * count)
        candles: list[Candle] = []
        price = self._base_price(symbol)
        amplitude = price * 0.0017
        drift = price * 0.000018
        spread = price * 0.00075

        for index in range(count):
            wave = math.sin(index / 7) * amplitude
            trend = index * drift
            close = price + wave + trend
            open_price = close - spread * 0.35
            high = close + spread
            low = close - spread
            candles.append(
                Candle(
                    time=start + timedelta(minutes=15 * index),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=1000 + index * 3,
                )
            )

        return candles

    def get_status(self) -> BrokerStatus:
        return BrokerStatus(
            name="PANTHER Simulated Broker",
            connected=True,
            mode="paper",
            account_login="SIM-0001",
            account_server="local-simulator",
            balance=10000.0,
            equity=10000.0,
            open_positions=len(self.orders),
            symbols_total=len(DEFAULT_MARKET_UNIVERSE),
            message="Safe paper broker active",
        )

    def list_symbols(self) -> list[str]:
        return [item.symbol for item in DEFAULT_MARKET_UNIVERSE]

    def count_open_positions(self, symbol: str | None = None) -> int:
        return len(self.orders)

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.orders.append(request)
        return OrderResult(
            status=OrderStatus.SIMULATED,
            message=f"Simulated {request.side.value} order for {request.symbol}",
            broker_order_id=f"sim-{len(self.orders)}",
        )

    def open_positions(self) -> list[dict]:
        return []

    def _base_price(self, symbol: str) -> float:
        symbol = symbol.upper()
        prices = {
            "XAUUSD": 2335.0,
            "XAGUSD": 29.5,
            "XPTUSD": 980.0,
            "XPDUSD": 1040.0,
            "USOIL": 78.0,
            "UKOIL": 82.0,
            "NATGAS": 2.75,
            "US30": 39200.0,
            "US500": 5200.0,
            "NAS100": 18400.0,
            "GER40": 18450.0,
            "UK100": 8200.0,
            "FRA40": 8050.0,
            "JPN225": 38500.0,
            "BTCUSD": 64000.0,
            "ETHUSD": 3200.0,
            "SOLUSD": 145.0,
            "XRPUSD": 0.62,
            "LTCUSD": 84.0,
            "AAPL": 225.0,
            "MSFT": 430.0,
            "NVDA": 125.0,
            "TSLA": 245.0,
            "AMZN": 185.0,
            "META": 520.0,
            "GOOGL": 170.0,
        }
        if symbol.endswith("JPY"):
            return 155.0
        if symbol.startswith("USD") and symbol not in {"USDJPY"}:
            return 18.0 if symbol in {"USDZAR", "USDMXN"} else 1.0
        return prices.get(symbol, 1.08)
