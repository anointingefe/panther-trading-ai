from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import fmean

from panther_trading.config import StrategyConfig
from panther_trading.models import Candle, SentimentSnapshot, SignalSide, TradeSignal


class SmaSentimentStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def generate(self, symbol: str, candles: list[Candle], sentiment: SentimentSnapshot) -> TradeSignal:
        if not candles:
            return TradeSignal.hold(symbol, 0.0, "No candles available")
        for candle in candles:
            prices = (candle.open, candle.high, candle.low, candle.close)
            if any(not math.isfinite(value) or value <= 0 for value in prices):
                return TradeSignal.hold(symbol, 0.0, "Invalid candle prices")
            if not candle.low <= min(candle.open, candle.close) <= max(candle.open, candle.close) <= candle.high:
                return TradeSignal.hold(symbol, candle.close, "Invalid candle OHLC structure")
        if any(left.time >= right.time for left, right in zip(candles, candles[1:])):
            return TradeSignal.hold(symbol, candles[-1].close, "Candle times must be strictly increasing")
        if not 1 <= self.config.fast_sma < self.config.slow_sma:
            return TradeSignal.hold(symbol, candles[-1].close, "Invalid strategy windows")
        if len(candles) < self.config.slow_sma:
            return TradeSignal.hold(symbol, candles[-1].close, "Not enough candles for strategy window")

        closes = [candle.close for candle in candles]
        recent = candles[-min(len(candles), 60) :]
        fast = fmean(closes[-self.config.fast_sma :])
        slow = fmean(closes[-self.config.slow_sma :])
        latest = closes[-1]
        atr = self._average_range(candles[-15:])
        if atr <= 0:
            return TradeSignal.hold(symbol, latest, "No measurable trading range")
        atr_pct = atr / max(abs(latest), 1e-9)
        ema_fast = self._ema(closes[-21:], 8)
        ema_slow = self._ema(closes[-55:], 21)
        momentum_5 = (latest - closes[-6]) / max(abs(latest), 1e-9) if len(closes) >= 6 else 0.0
        momentum_20 = (latest - closes[-21]) / max(abs(latest), 1e-9) if len(closes) >= 21 else 0.0
        range_high = max(candle.high for candle in recent[:-1]) if len(recent) > 1 else latest
        range_low = min(candle.low for candle in recent[:-1]) if len(recent) > 1 else latest
        breakout_buffer = max(atr * 0.08, abs(latest) * 0.00002)
        candle_bias, candle_strength, candle_note = self._latest_candle_bias(candles)
        volatility_quality = self._volatility_quality(atr_pct)

        trend_score = (fast - slow) / latest
        ema_score = (ema_fast - ema_slow) / latest
        sentiment_valid = (
            sentiment.symbol.upper() == symbol.upper()
            and math.isfinite(sentiment.score) and -1 <= sentiment.score <= 1
            and math.isfinite(sentiment.confidence) and 0 <= sentiment.confidence <= 1
        )
        sentiment_confidence = sentiment.confidence if sentiment_valid else 0.0
        sentiment_score = sentiment.score * sentiment_confidence * self.config.sentiment_weight / 100 if sentiment_valid else 0.0
        breakout_score = 0.0
        if latest > range_high + breakout_buffer:
            breakout_score = 0.003
        elif latest < range_low - breakout_buffer:
            breakout_score = -0.003
        reversal_score = self._reversal_score(latest, range_high, range_low, candle_bias, candle_strength)
        blended_score = (
            trend_score * 1.3
            + ema_score * 0.9
            + momentum_5 * 0.85
            + momentum_20 * 0.55
            + breakout_score
            + reversal_score
            + sentiment_score
        )

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

        direction = 1 if side == SignalSide.BUY else -1
        directional_scores = {
            "trend": trend_score * direction,
            "ema": ema_score * direction,
            "momentum_5": momentum_5 * direction,
            "momentum_20": momentum_20 * direction,
            "breakout": breakout_score * direction,
            "reversal": reversal_score * direction,
            "sentiment": sentiment_score * direction,
        }
        confirmations = sum(1 for score in directional_scores.values() if score > 0)
        conflicts = sum(1 for score in directional_scores.values() if score < -0.00005)
        candle_aligned = candle_bias == side.value
        if candle_aligned:
            confirmations += 1
        elif candle_bias in {"buy", "sell"}:
            conflicts += 1

        raw_edge = min(abs(blended_score) * 42, 0.24)
        confirmation_bonus = min(confirmations * 0.04, 0.24)
        candle_bonus = candle_strength * 0.07 if candle_aligned else 0.0
        volatility_bonus = volatility_quality * 0.06
        sentiment_bonus = sentiment_confidence * 0.025
        conflict_penalty = min(conflicts * 0.07, 0.24)
        confidence = 0.14 + raw_edge + confirmation_bonus + candle_bonus + volatility_bonus + sentiment_bonus - conflict_penalty
        confidence = round(min(max(confidence, 0.0), 0.94), 4)
        strategy_name = self._strategy_name(
            breakout_score * direction,
            reversal_score * direction,
            momentum_20 * direction,
            candle_aligned,
        )

        return TradeSignal(
            symbol=symbol,
            side=side,
            confidence=round(confidence, 4),
            entry=latest,
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            rationale=(
                f"Strategy profile: {strategy_name}.",
                f"Trend stack: SMA {fast:.6f}/{slow:.6f}, EMA {ema_fast:.6f}/{ema_slow:.6f}.",
                f"Momentum: 5-candle {momentum_5:+.4%}, 20-candle {momentum_20:+.4%}.",
                f"Structure: range {range_low:.6f} to {range_high:.6f}; breakout score {breakout_score * direction:+.4f}.",
                f"Candle read: {candle_note}",
                f"Evidence score: {confirmations} confirmations, {conflicts} conflicts, ATR quality {volatility_quality:.0%}.",
                f"Sentiment score {sentiment.score:.2f} from {', '.join(sentiment.sources)}.",
                f"Blended directional score {blended_score:.6f}.",
            ),
            generated_at=datetime.now(timezone.utc),
        )

    def _average_range(self, candles: list[Candle]) -> float:
        if len(candles) < 2:
            return candles[0].high - candles[0].low if candles else 0.0
        return fmean(
            max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close))
            for previous, current in zip(candles, candles[1:])
        )

    def _ema(self, values: list[float], period: int) -> float:
        if not values:
            return 0.0
        multiplier = 2 / (period + 1)
        value = values[0]
        for item in values[1:]:
            value = item * multiplier + value * (1 - multiplier)
        return value

    def _latest_candle_bias(self, candles: list[Candle]) -> tuple[str, float, str]:
        latest = candles[-1]
        body = latest.close - latest.open
        full_range = max(latest.high - latest.low, 1e-9)
        body_ratio = abs(body) / full_range
        upper_wick = latest.high - max(latest.open, latest.close)
        lower_wick = min(latest.open, latest.close) - latest.low
        if body_ratio >= 0.58:
            direction = "buy" if body > 0 else "sell"
            return direction, min(body_ratio, 1.0), f"{direction} momentum candle with {body_ratio:.0%} body dominance."
        if lower_wick >= abs(body) * 2.2 and latest.close >= latest.open:
            return "buy", 0.72, "bullish rejection wick shows buyers defended the low."
        if upper_wick >= abs(body) * 2.2 and latest.close <= latest.open:
            return "sell", 0.72, "bearish rejection wick shows sellers defended the high."
        return "neutral", max(0.0, body_ratio * 0.35), "no decisive final-candle pattern."

    def _volatility_quality(self, atr_pct: float) -> float:
        if atr_pct <= 0:
            return 0.0
        if 0.00035 <= atr_pct <= 0.006:
            return 1.0
        if atr_pct < 0.00035:
            return max(0.15, atr_pct / 0.00035)
        return max(0.2, 1 - min((atr_pct - 0.006) / 0.018, 0.8))

    def _reversal_score(
        self,
        latest: float,
        range_high: float,
        range_low: float,
        candle_bias: str,
        candle_strength: float,
    ) -> float:
        width = max(range_high - range_low, 1e-9)
        position = (latest - range_low) / width
        if position <= 0.18 and candle_bias == "buy":
            return 0.0018 * candle_strength
        if position >= 0.82 and candle_bias == "sell":
            return -0.0018 * candle_strength
        return 0.0

    def _strategy_name(
        self,
        breakout_alignment: float,
        reversal_alignment: float,
        momentum_alignment: float,
        candle_aligned: bool,
    ) -> str:
        if breakout_alignment > 0:
            return "Panther Breakout Continuation"
        if reversal_alignment > 0:
            return "Panther Trap Reversal"
        if momentum_alignment > 0 and candle_aligned:
            return "Panther Momentum Sweep"
        return "Panther Evidence Blend"
