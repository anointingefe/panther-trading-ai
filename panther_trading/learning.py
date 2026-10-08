from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EvolutionReport:
    status: str
    phase: str
    sample_size: int
    promoted_strategy: str | None
    confidence: float
    score: float
    adaptations: tuple[str, ...]
    blockers: tuple[str, ...]
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvolutionEngine:
    """Turns research and demo outcomes into controlled improvement decisions."""

    def __init__(self, minimum_closed_trades: int = 30, minimum_profit_factor: float = 1.2) -> None:
        self.minimum_closed_trades = minimum_closed_trades
        self.minimum_profit_factor = minimum_profit_factor

    def evaluate(
        self,
        research: dict[str, Any],
        positions: list[dict[str, Any]],
        journal_entries: list[dict[str, Any]],
    ) -> EvolutionReport:
        closed_positions = [position for position in positions if position.get("status") == "closed"]
        approved_cards = [
            card for card in research.get("scorecards", [])
            if card.get("status") == "approved"
        ]
        best_card = approved_cards[0] if approved_cards else None
        closed_count = len(closed_positions)
        win_count = len([position for position in closed_positions if float(position.get("pnl") or 0) > 0])
        win_rate = win_count / closed_count if closed_count else 0.0
        profit_factor = self._profit_factor(closed_positions)
        score = self._score(best_card, closed_count, profit_factor, win_rate)
        blockers = self._blockers(best_card, closed_count, profit_factor)
        adaptations = self._adaptations(best_card, journal_entries, closed_positions)
        status = "ready_to_promote" if not blockers else "learning"
        phase = "demo_evidence" if closed_count else "observation"

        return EvolutionReport(
            status=status,
            phase=phase,
            sample_size=closed_count,
            promoted_strategy=best_card.get("name") if best_card else None,
            confidence=round(min(score, 1.0), 4),
            score=round(score, 4),
            adaptations=tuple(adaptations),
            blockers=tuple(blockers),
            policy=(
                "PANTHER may rank and recommend strategy changes, but it cannot auto-promote "
                "a strategy without enough closed demo trades and passing research evidence."
            ),
        )

    def _profit_factor(self, positions: list[dict[str, Any]]) -> float:
        gross_profit = sum(float(position.get("pnl") or 0) for position in positions if float(position.get("pnl") or 0) > 0)
        gross_loss = abs(sum(float(position.get("pnl") or 0) for position in positions if float(position.get("pnl") or 0) < 0))
        if gross_loss == 0:
            return round(gross_profit, 4) if gross_profit else 0.0
        return round(gross_profit / gross_loss, 4)

    def _score(
        self,
        best_card: dict[str, Any] | None,
        closed_count: int,
        profit_factor: float,
        win_rate: float,
    ) -> float:
        research_score = 0.0
        if best_card:
            research_score = min(float(best_card.get("profit_factor") or 0) / 2.0, 0.4)
            research_score += min(max(float(best_card.get("net_r") or 0), 0.0) / 20.0, 0.25)
            research_score += min(max(float(best_card.get("out_of_sample_net_r") or 0), 0.0) / 10.0, 0.15)

        evidence_score = min(closed_count / self.minimum_closed_trades, 1.0) * 0.1
        outcome_score = min(profit_factor / 2.0, 0.1) if profit_factor else 0.0
        outcome_score += min(win_rate, 1.0) * 0.1
        return research_score + evidence_score + outcome_score

    def _blockers(
        self,
        best_card: dict[str, Any] | None,
        closed_count: int,
        profit_factor: float,
    ) -> list[str]:
        blockers: list[str] = []
        if not best_card:
            blockers.append("No approved research strategy for the selected market yet.")
        if closed_count < self.minimum_closed_trades:
            blockers.append(f"Needs at least {self.minimum_closed_trades} closed demo trades before promotion.")
        if closed_count and profit_factor < self.minimum_profit_factor:
            blockers.append(f"Demo profit factor must be at least {self.minimum_profit_factor}.")
        return blockers

    def _adaptations(
        self,
        best_card: dict[str, Any] | None,
        journal_entries: list[dict[str, Any]],
        closed_positions: list[dict[str, Any]],
    ) -> list[str]:
        adaptations = [
            "Keep live trading locked while the demo evidence set grows.",
            "Re-rank strategies after each fresh market scan and synced MT5 history batch.",
        ]
        if best_card:
            adaptations.append(f"Favor {best_card.get('name')} for incubation when risk rules allow.")
        blocked_signals = [
            entry for entry in journal_entries
            if entry.get("approval_status") == "blocked_by_risk"
        ]
        if journal_entries and len(blocked_signals) > len(journal_entries) / 2:
            adaptations.append("Most recent signals are risk-blocked, so keep confidence thresholds strict.")
        if closed_positions:
            adaptations.append("Use closed demo outcomes to compare broker reality against backtest scorecards.")
        return adaptations
