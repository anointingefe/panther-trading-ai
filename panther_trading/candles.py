from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from panther_trading.models import Candle


@dataclass(frozen=True)
class CandlePattern:
    name: str
    direction: str
    strength: float
    reason: str


@dataclass(frozen=True)
class CandleBox:
    timeframe: str
    high: float
    low: float
    midpoint: float
    latest_position: str
    inside_box: bool


@dataclass(frozen=True)
class CandleIntelligenceReport:
    box: CandleBox
    lower_timeframe: str
    ema_bias: str
    vwap_bias: str
    confirmation: str
    confirmation_score: float
    patterns: tuple[CandlePattern, ...]
    notes: tuple[str, ...]


class CandleIntelligenceEngine:
    def analyze(
        self,
        higher_candles: list[Candle],
        lower_candles: list[Candle],
        higher_timeframe: str = "D1",
        lower_timeframe: str = "M5",
    ) -> CandleIntelligenceReport:
        if len(higher_candles) < 2:
            raise ValueError("Candle intelligence requires at least two higher-timeframe candles")
        if len(lower_candles) < 5:
            raise ValueError("Candle intelligence requires at least five lower-timeframe candles")

        previous_box_candle = higher_candles[-2]
        latest = lower_candles[-1]
        box = self._box(previous_box_candle, latest, higher_timeframe)
        patterns = self._patterns(lower_candles)
        ema_bias = self._ema_bias(lower_candles)
        vwap_bias = self._vwap_bias(lower_candles)
        confirmation, score = self._confirmation(patterns, ema_bias, vwap_bias, box)

        return CandleIntelligenceReport(
            box=box,
            lower_timeframe=lower_timeframe,
            ema_bias=ema_bias,
            vwap_bias=vwap_bias,
            confirmation=confirmation,
            confirmation_score=score,
            patterns=tuple(patterns),
            notes=tuple(self._notes(box, patterns, ema_bias, vwap_bias, confirmation)),
        )

    def _box(self, candle: Candle, latest: Candle, timeframe: str) -> CandleBox:
        midpoint = (candle.high + candle.low) / 2
        close = latest.close
        if close > candle.high:
            position = "above_box"
        elif close < candle.low:
            position = "below_box"
        elif close >= midpoint:
            position = "upper_half"
        else:
            position = "lower_half"
        return CandleBox(
            timeframe=timeframe,
            high=round(candle.high, 6),
            low=round(candle.low, 6),
            midpoint=round(midpoint, 6),
            latest_position=position,
            inside_box=candle.low <= close <= candle.high,
        )

    def _patterns(self, candles: list[Candle]) -> list[CandlePattern]:
        previous = candles[-2]
        latest = candles[-1]
        patterns: list[CandlePattern] = []

        body = abs(latest.close - latest.open)
        full_range = max(latest.high - latest.low, 1e-9)
        upper_wick = latest.high - max(latest.open, latest.close)
        lower_wick = min(latest.open, latest.close) - latest.low
        body_ratio = body / full_range

        if body_ratio <= 0.18:
            patterns.append(CandlePattern("doji", "neutral", round(1 - body_ratio, 4), "Small body shows indecision."))

        if body_ratio >= 0.62:
            direction = "bullish" if latest.close > latest.open else "bearish"
            patterns.append(CandlePattern("momentum", direction, round(body_ratio, 4), "Large candle body shows momentum."))

        if latest.close > latest.open and previous.close < previous.open:
            if latest.close >= previous.open and latest.open <= previous.close:
                patterns.append(CandlePattern("bullish_engulfing", "bullish", 0.82, "Bullish body engulfs prior bearish candle."))

        if latest.close < latest.open and previous.close > previous.open:
            if latest.open >= previous.close and latest.close <= previous.open:
                patterns.append(CandlePattern("bearish_engulfing", "bearish", 0.82, "Bearish body engulfs prior bullish candle."))

        if lower_wick >= body * 2 and latest.close > latest.open:
            patterns.append(CandlePattern("bullish_rejection_wick", "bullish", 0.72, "Long lower wick shows downside rejection."))

        if upper_wick >= body * 2 and latest.close < latest.open:
            patterns.append(CandlePattern("bearish_rejection_wick", "bearish", 0.72, "Long upper wick shows upside rejection."))

        if latest.high <= previous.high and latest.low >= previous.low:
            patterns.append(CandlePattern("inside_bar", "neutral", 0.55, "Candle is contained inside the previous candle."))

        return patterns or [CandlePattern("no_clear_pattern", "neutral", 0.0, "No decisive candle pattern detected.")]

    def _ema_bias(self, candles: list[Candle]) -> str:
        closes = [candle.close for candle in candles]
        fast = self._ema(closes[-12:], 6)
        slow = self._ema(closes[-26:], 13)
        if fast > slow:
            return "bullish"
        if fast < slow:
            return "bearish"
        return "neutral"

    def _vwap_bias(self, candles: list[Candle]) -> str:
        total_volume = sum(max(candle.volume, 1) for candle in candles)
        vwap = sum(((candle.high + candle.low + candle.close) / 3) * max(candle.volume, 1) for candle in candles) / total_volume
        latest_close = candles[-1].close
        if latest_close > vwap:
            return "bullish"
        if latest_close < vwap:
            return "bearish"
        return "neutral"

    def _ema(self, values: list[float], period: int) -> float:
        if not values:
            return 0.0
        multiplier = 2 / (period + 1)
        value = values[0]
        for item in values[1:]:
            value = item * multiplier + value * (1 - multiplier)
        return value

    def _confirmation(
        self,
        patterns: list[CandlePattern],
        ema_bias: str,
        vwap_bias: str,
        box: CandleBox,
    ) -> tuple[str, float]:
        bullish = sum(pattern.strength for pattern in patterns if pattern.direction == "bullish")
        bearish = sum(pattern.strength for pattern in patterns if pattern.direction == "bearish")
        if ema_bias == "bullish":
            bullish += 0.25
        if ema_bias == "bearish":
            bearish += 0.25
        if vwap_bias == "bullish":
            bullish += 0.2
        if vwap_bias == "bearish":
            bearish += 0.2
        if box.latest_position == "lower_half":
            bullish += 0.1
        if box.latest_position == "upper_half":
            bearish += 0.1

        if bullish > bearish and bullish >= 0.7:
            return "bullish", round(min(bullish / 2, 1), 4)
        if bearish > bullish and bearish >= 0.7:
            return "bearish", round(min(bearish / 2, 1), 4)
        return "wait", round(max(bullish, bearish) / 2, 4)

    def _notes(
        self,
        box: CandleBox,
        patterns: list[CandlePattern],
        ema_bias: str,
        vwap_bias: str,
        confirmation: str,
    ) -> list[str]:
        return [
            f"Previous {box.timeframe} candle box: {box.low:.6f} to {box.high:.6f}.",
            f"Latest lower-timeframe close is {box.latest_position.replace('_', ' ')}.",
            f"EMA bias is {ema_bias}; VWAP bias is {vwap_bias}.",
            f"Strongest candle pattern: {max(patterns, key=lambda item: item.strength).name}.",
            f"Candle confirmation decision: {confirmation}.",
        ]
