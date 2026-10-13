from dataclasses import replace
from datetime import datetime, timedelta, timezone

from panther_trading.config import load_config
from panther_trading.data.sentiment import StaticSentimentCollector
from panther_trading.models import Candle, SignalSide
from panther_trading.strategies import SmaSentimentStrategy


def strategy():
    return SmaSentimentStrategy(load_config("config/demo.yaml").strategy)


def candles():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(start + timedelta(minutes=15 * index), 100 + index, 102 + index, 99 + index, 101 + index, 1000)
        for index in range(60)
    ]


def test_missing_sentiment_contributes_no_direction_or_confidence():
    sentiment = StaticSentimentCollector().collect("TEST")
    assert sentiment.score == 0
    assert sentiment.confidence == 0
    assert sentiment.sources == ("sentiment-unavailable",)


def test_empty_candles_produce_hold_not_index_error():
    result = strategy().generate("TEST", [], StaticSentimentCollector().collect("TEST"))
    assert result.side == SignalSide.HOLD


def test_invalid_ohlc_cannot_generate_a_trade():
    data = candles()
    data[-1] = replace(data[-1], low=data[-1].high + 1)
    assert strategy().generate("TEST", data, StaticSentimentCollector().collect("TEST")).side == SignalSide.HOLD


def test_duplicate_bar_times_cannot_generate_a_trade():
    data = candles()
    data[-1] = replace(data[-1], time=data[-2].time)
    assert strategy().generate("TEST", data, StaticSentimentCollector().collect("TEST")).side == SignalSide.HOLD


def test_nonfinite_candles_cannot_generate_a_trade():
    data = candles()
    data[-1] = replace(data[-1], close=float("nan"))
    assert strategy().generate("TEST", data, StaticSentimentCollector().collect("TEST")).side == SignalSide.HOLD


def test_true_range_includes_price_gaps():
    time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    data = [
        Candle(time, 100, 101, 99, 100, 1000),
        Candle(time + timedelta(minutes=15), 111, 115, 110, 112, 1000),
    ]
    assert strategy()._average_range(data) == 15


def test_zero_range_returns_hold():
    data = [replace(candle, open=100, high=100, low=100, close=100) for candle in candles()]
    assert strategy().generate("TEST", data, StaticSentimentCollector().collect("TEST")).side == SignalSide.HOLD


def test_sentiment_with_zero_confidence_cannot_bias_a_signal():
    neutral = StaticSentimentCollector().collect("TEST")
    baseline = strategy().generate("TEST", candles(), neutral)
    untrusted = strategy().generate("TEST", candles(), replace(neutral, score=1.0))
    assert (untrusted.side, untrusted.confidence) == (baseline.side, baseline.confidence)
