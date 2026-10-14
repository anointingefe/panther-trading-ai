from __future__ import annotations

from datetime import datetime, timezone

from panther_trading.brokers.base import Broker
from panther_trading.models import BrokerStatus, Candle, OrderRequest, OrderResult, OrderStatus, SignalSide, TradeSignal
from panther_trading.portfolio_risk import ApprovedLivePortfolioRisk, exposure_buckets


class RiskBroker(Broker):
    def __init__(self, positions: list[dict]) -> None:
        self._positions = positions

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        return []

    def get_status(self) -> BrokerStatus:
        return BrokerStatus("test", True, "demo", "1", "test", 10000, 10000, len(self._positions), 10, "ok")

    def list_symbols(self) -> list[str]:
        return []

    def count_open_positions(self, symbol: str | None = None) -> int:
        if symbol is None:
            return len(self._positions)
        return len([position for position in self._positions if position.get("symbol") == symbol])

    def place_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(OrderStatus.REJECTED, "unused")

    def open_positions(self) -> list[dict]:
        return list(self._positions)

    def estimate_position_risk(
        self,
        symbol: str,
        side: SignalSide,
        volume: float,
        entry: float,
        stop_loss: float,
    ) -> float:
        return abs(entry - stop_loss) * volume * 100000


def _signal(symbol: str, side: SignalSide) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        side=side,
        confidence=0.9,
        entry=1.10,
        stop_loss=1.09 if side == SignalSide.BUY else 1.11,
        take_profit=1.12 if side == SignalSide.BUY else 1.08,
        rationale=("test",),
        generated_at=datetime.now(timezone.utc),
    )


def test_exposure_buckets_capture_shared_currency_direction() -> None:
    assert exposure_buckets("EURUSD", SignalSide.BUY) == ("LONG_EUR", "SHORT_USD")
    assert exposure_buckets("GBPUSD", SignalSide.BUY) == ("LONG_GBP", "SHORT_USD")
    assert exposure_buckets("USDJPY", SignalSide.SELL) == ("SHORT_USD", "LONG_JPY")


def test_correlated_bucket_reduces_remaining_candidate_risk() -> None:
    broker = RiskBroker(
        [
            {
                "symbol": "EURUSD",
                "side": "buy",
                "volume": 0.01,
                "entry": 1.10,
                "stop_loss": 1.09,
            }
        ]
    )
    guard = ApprovedLivePortfolioRisk(
        broker,
        equity=10000,
        max_portfolio_risk_pct=3.0,
        max_exposure_bucket_risk_pct=1.5,
    )

    available, snapshot, reasons = guard.available_risk_for(_signal("GBPUSD", SignalSide.BUY))

    assert snapshot.total_open_risk == 10.0
    assert snapshot.bucket_risk["SHORT_USD"] == 10.0
    assert available == 140.0
    assert reasons == ()


def test_portfolio_cap_blocks_when_stop_risk_is_fully_allocated() -> None:
    broker = RiskBroker(
        [
            {
                "symbol": "EURUSD",
                "side": "buy",
                "volume": 0.30,
                "entry": 1.10,
                "stop_loss": 1.09,
            }
        ]
    )
    guard = ApprovedLivePortfolioRisk(
        broker,
        equity=10000,
        max_portfolio_risk_pct=3.0,
        max_exposure_bucket_risk_pct=3.0,
    )

    available, snapshot, reasons = guard.available_risk_for(_signal("AUDJPY", SignalSide.BUY))

    assert snapshot.total_open_risk == 300.0
    assert available == 0.0
    assert "Approved-live portfolio risk budget is fully allocated" in reasons
