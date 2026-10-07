from datetime import datetime, timedelta, timezone

from panther_trading.candles import CandleIntelligenceEngine
from panther_trading.models import Candle


def _candle(index: int, open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index * 5),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000 + index,
    )


def test_candle_intelligence_builds_daily_box_report() -> None:
    higher = [
        _candle(0, 1.0, 1.12, 0.98, 1.1),
        _candle(1, 1.1, 1.2, 1.0, 1.18),
        _candle(2, 1.18, 1.19, 1.08, 1.1),
    ]
    lower = [
        _candle(3, 1.05, 1.08, 1.04, 1.07),
        _candle(4, 1.07, 1.1, 1.06, 1.09),
        _candle(5, 1.09, 1.12, 1.08, 1.11),
        _candle(6, 1.11, 1.14, 1.1, 1.13),
        _candle(7, 1.12, 1.16, 1.11, 1.15),
    ]

    report = CandleIntelligenceEngine().analyze(higher, lower)

    assert report.box.timeframe == "D1"
    assert report.box.inside_box
    assert report.confirmation in {"bullish", "bearish", "wait"}
    assert report.notes


def test_candle_intelligence_detects_momentum() -> None:
    higher = [
        _candle(0, 1.0, 1.2, 0.9, 1.1),
        _candle(1, 1.1, 1.3, 1.0, 1.2),
    ]
    lower = [
        _candle(2, 1.04, 1.06, 1.03, 1.05),
        _candle(3, 1.05, 1.07, 1.04, 1.06),
        _candle(4, 1.06, 1.08, 1.05, 1.07),
        _candle(5, 1.07, 1.09, 1.06, 1.08),
        _candle(6, 1.08, 1.16, 1.07, 1.15),
    ]

    report = CandleIntelligenceEngine().analyze(higher, lower)

    assert any(pattern.name == "momentum" for pattern in report.patterns)
