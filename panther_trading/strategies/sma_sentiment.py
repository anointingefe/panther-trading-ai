from __future__ import annotations

from datetime import datetime, timezone
from statistics import fmean

from panther_trading.config import StrategyConfig
from panther_trading.models import Candle, SentimentSnapshot, SignalSide, TradeSignal


class SmaSentimentStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def generate(self, symbol: str, candles: list[Candle], sentiment: SentimentSnapshot) -> TradeSignal:
        if len(candles) < self.config.slow_sma:
            return TradeSignal.hold(symbol, candles[-1].close, "Not enough candles for strategy window")

        closes = [candle.close for candle in candles]
        fast = fmean(closes[-self.config.fast_sma :])
        slow = fmean(closes[-self.config.slow_sma :])
        latest = closes[-1]
        atr = self._average_range(candles[-14:])

        trend_score = (fast - slow) / latest
        blended_score = trend_score + (sentiment.score * self.config.sentiment_weight / 100)
        confidence = min(0.95, abs(blended_score) * 160 + sentiment.confidence * 0.2)

        if blended_score > 0:
            side = SignalSide.BUY
            stop_loss = latest - atr * 1.5
            take_profit = latest + atr * 2.25
        elif blended_score < 0:
            side = SignalSide.SELL
            stop_loss = latest + atr * 1.5
            take_profit = latest - atr * 2.25
        else:
            return TradeSignal.hold(symbol, latest, "No directional edge detected")

        return TradeSignal(
            symbol=symbol,
            side=side,
            confidence=round(confidence, 4),
            entry=latest,
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            rationale=(
                f"Fast SMA {fast:.6f} vs slow SMA {slow:.6f}",
                f"Sentiment score {sentiment.score:.2f} from {', '.join(sentiment.sources)}",
                f"Blended directional score {blended_score:.6f}",
            ),
            generated_at=datetime.now(timezone.utc),
        )

    def _average_range(self, candles: list[Candle]) -> float:
        if not candles:
            return 0.001
        return fmean(candle.high - candle.low for candle in candles)
