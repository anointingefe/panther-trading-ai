from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyTrustDecision:
    allowed: bool
    status: str
    reason: str
    selected_strategy: str | None


class StrategyTrustGate:
    def evaluate(self, research: dict[str, Any]) -> StrategyTrustDecision:
        scorecards = research.get("scorecards", [])
        approved = [card for card in scorecards if card.get("status") == "approved"]
        if not approved:
            best = scorecards[0] if scorecards else None
            best_name = best.get("name") if best else None
            return StrategyTrustDecision(
                allowed=False,
                status="blocked",
                reason="No strategy is approved by the research lab for this market condition.",
                selected_strategy=best_name,
            )

        selected = max(approved, key=lambda card: (card.get("profit_factor", 0), card.get("net_r", 0)))
        return StrategyTrustDecision(
            allowed=True,
            status="approved",
            reason=f"Strategy approved: {selected['name']} passed research thresholds.",
            selected_strategy=str(selected["name"]),
        )
