from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from panther_trading.models import Candle, SignalSide, TradeSignal


@dataclass(frozen=True)
class DoctrinePrinciple:
    name: str
    source: str
    rule: str


@dataclass(frozen=True)
class DoctrineReport:
    score: float
    grade: str
    principles: tuple[DoctrinePrinciple, ...]
    notes: tuple[str, ...]
    blockers: tuple[str, ...]


class EliteTradingDoctrine:
    """Public trading wisdom converted into auditable execution checks."""

    def __init__(self) -> None:
        self.principles = (
            DoctrinePrinciple(
                "Defence First",
                "Paul Tudor Jones",
                "Protect capital before seeking upside; reject trades with poor risk control.",
            ),
            DoctrinePrinciple(
                "Rule-Based Trend Following",
                "Richard Dennis / Turtle Traders",
                "Trade only when entry, sizing, stop, and exit rules are explicit.",
            ),
            DoctrinePrinciple(
                "Cut Losses, Let Winners Work",
                "Ed Seykota / Market Wizards tradition",
                "Define invalidation before entry and avoid holding losers past the thesis.",
            ),
            DoctrinePrinciple(
                "Evidence Over Prediction",
                "Jim Simons / quantitative tradition",
                "Prefer measurable confluence and repeatable data over narratives.",
            ),
            DoctrinePrinciple(
                "Volatility Contraction",
                "Mark Minervini / William O'Neil growth-trading tradition",
                "Prefer entries after volatility tightens and price breaks with structure.",
            ),
        )

    def evaluate(self, signal: TradeSignal, candles: list[Candle]) -> DoctrineReport:
        if signal.side == SignalSide.HOLD:
            return DoctrineReport(
                score=0.0,
                grade="blocked",
                principles=self.principles,
                notes=("Doctrine blocks hold signals: no directional execution plan exists.",),
                blockers=("No directional edge.",),
            )

        risk = abs(signal.entry - signal.stop_loss)
        reward = abs(signal.take_profit - signal.entry)
        rr = reward / risk if risk > 0 else 0.0
        atr = self._average_range(candles[-14:])
        recent_range = self._average_range(candles[-5:])
        baseline_range = self._average_range(candles[-30:-5])
        volatility_contracting = bool(baseline_range and recent_range < baseline_range * 0.82)
        stop_reasonable = bool(risk > 0 and atr > 0 and risk <= atr * 2.2)
        trend_aligned = self._trend_aligned(signal, candles)
        explicit_exit = risk > 0 and reward > 0

        score = 0.0
        notes: list[str] = []
        blockers: list[str] = []

        if rr >= 1.4:
            score += 0.22
            notes.append(f"Asymmetric reward: risk/reward is {rr:.2f}R.")
        else:
            blockers.append(f"Risk/reward is weak at {rr:.2f}R.")

        if stop_reasonable:
            score += 0.2
            notes.append("Stop distance is inside the doctrine risk envelope.")
        else:
            blockers.append("Stop distance is too wide or invalid for the current ATR.")

        if trend_aligned:
            score += 0.2
            notes.append("Trend alignment supports the proposed direction.")
        else:
            blockers.append("Trend alignment is not clean enough.")

        if explicit_exit:
            score += 0.18
            notes.append("Entry, stop, and target are explicit before execution.")
        else:
            blockers.append("Trade has no valid pre-planned exit.")

        if volatility_contracting:
            score += 0.1
            notes.append("Recent volatility is contracting before the setup.")

        if signal.confidence >= 0.62:
            score += 0.1
            notes.append("Signal confidence clears the main execution gate.")
        elif signal.confidence >= 0.48:
            notes.append("Signal is scout-only: promising but not proven enough for full-size execution.")
        else:
            blockers.append("Confidence is below scout threshold.")

        confidence_cleared = signal.confidence >= 0.62
        grade = (
            "elite_aligned"
            if confidence_cleared and score >= 0.72 and not blockers
            else "scout_aligned"
            if score >= 0.52 and signal.confidence >= 0.48
            else "blocked"
        )
        return DoctrineReport(
            score=round(min(score, 1.0), 4),
            grade=grade,
            principles=self.principles,
            notes=tuple(notes),
            blockers=tuple(blockers),
        )

    def _average_range(self, candles: list[Candle]) -> float:
        if not candles:
            return 0.0
        return fmean(candle.high - candle.low for candle in candles)

    def _trend_aligned(self, signal: TradeSignal, candles: list[Candle]) -> bool:
        if len(candles) < 34:
            return False
        closes = [candle.close for candle in candles]
        fast = fmean(closes[-13:])
        slow = fmean(closes[-34:])
        if signal.side == SignalSide.BUY:
            return fast > slow and closes[-1] > fast
        if signal.side == SignalSide.SELL:
            return fast < slow and closes[-1] < fast
        return False
