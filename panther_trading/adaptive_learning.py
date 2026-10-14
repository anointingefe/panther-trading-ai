from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_EVIDENCE_WEIGHTS = {
    "live": 1.0,
    "demo": 0.75,
    "contest": 0.75,
    "paper": 0.5,
}


@dataclass(frozen=True)
class SegmentAssessment:
    symbol: str
    utc_hour: int
    rank_adjustment: float
    quality_score: float
    block_reason: str | None
    symbol_samples: int
    hour_samples: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "utc_hour": self.utc_hour,
            "rank_adjustment": self.rank_adjustment,
            "quality_score": self.quality_score,
            "block_reason": self.block_reason,
            "symbol_samples": self.symbol_samples,
            "hour_samples": self.hour_samples,
        }


class AdaptiveLearningEngine:
    """Build bounded live-selection memory from verified closed outcomes.

    Learning may rank or veto a setup after enough evidence. It never lowers the
    configured confidence floor, raises a risk cap, or increases position size.
    """

    def profile(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        closed = [item for item in positions if item.get("status") == "closed"]
        eligible = [item for item in closed if self._weight(item) > 0]
        by_symbol = self._group(eligible, lambda item: self._symbol(item))
        by_hour = self._group(eligible, lambda item: str(self._hour(item)))
        symbol_rows = [self._row(key, values) for key, values in by_symbol.items() if key]
        hour_rows = [self._row(key, values) for key, values in by_hour.items() if key != "None"]
        symbol_rows.sort(key=lambda row: (row["score"], row["weighted_samples"]), reverse=True)
        hour_rows.sort(key=lambda row: (row["score"], row["weighted_samples"]), reverse=True)
        live_samples = len([item for item in eligible if self._mode(item) == "live"])
        demo_samples = len(eligible) - live_samples
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sample_size": len(eligible),
            "live_samples": live_samples,
            "non_live_samples": demo_samples,
            "symbols": symbol_rows,
            "utc_hours": hour_rows,
            "leaders": symbol_rows[:5],
            "weak": sorted(symbol_rows, key=lambda row: row["score"])[:5],
            "policy": (
                "Closed outcomes may change candidate ranking or veto repeatedly weak segments. "
                "Learning cannot lower the base confidence floor, increase live risk, or bypass approval."
            ),
        }

    def assess(
        self,
        symbol: str,
        signal_time: datetime,
        profile: dict[str, Any],
        minimum_samples: int = 6,
    ) -> SegmentAssessment:
        symbol_key = self._symbol_key(symbol)
        hour = signal_time.astimezone(timezone.utc).hour
        symbol_row = self._find(profile.get("symbols") or [], symbol_key)
        hour_row = self._find(profile.get("utc_hours") or [], str(hour))
        adjustment = 0.0
        block_reason = None

        if symbol_row and symbol_row["samples"] >= minimum_samples:
            adjustment += (float(symbol_row["win_rate"]) - 0.5) * 0.10
            if float(symbol_row["win_rate"]) < 0.35:
                block_reason = (
                    f"Adaptive memory vetoed {symbol}: {symbol_row['win_rate']:.0%} win rate "
                    f"from {symbol_row['samples']} closed outcomes."
                )
        if hour_row and hour_row["samples"] >= minimum_samples:
            adjustment += (float(hour_row["win_rate"]) - 0.5) * 0.05
            if block_reason is None and float(hour_row["win_rate"]) < 0.30:
                block_reason = (
                    f"Adaptive memory vetoed UTC hour {hour}: {hour_row['win_rate']:.0%} win rate "
                    f"from {hour_row['samples']} closed outcomes."
                )

        adjustment = round(max(min(adjustment, 0.08), -0.08), 4)
        return SegmentAssessment(
            symbol=symbol,
            utc_hour=hour,
            rank_adjustment=adjustment,
            quality_score=round(max(min(0.5 + adjustment, 1.0), 0.0), 4),
            block_reason=block_reason,
            symbol_samples=int(symbol_row["samples"]) if symbol_row else 0,
            hour_samples=int(hour_row["samples"]) if hour_row else 0,
        )

    def _group(self, items: list[dict[str, Any]], key_fn: Any) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            key = key_fn(item)
            grouped.setdefault(str(key), []).append(item)
        return grouped

    def _row(self, key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        weighted_samples = sum(self._weight(item) for item in items)
        weighted_wins = sum(self._weight(item) for item in items if float(item.get("pnl") or 0.0) > 0)
        weighted_losses = sum(self._weight(item) for item in items if float(item.get("pnl") or 0.0) < 0)
        denominator = weighted_wins + weighted_losses
        win_rate = weighted_wins / denominator if denominator else 0.0
        score = (win_rate - 0.5) * min(weighted_samples / 10.0, 1.0)
        return {
            "key": key,
            "samples": len(items),
            "weighted_samples": round(weighted_samples, 3),
            "wins": len([item for item in items if float(item.get("pnl") or 0.0) > 0]),
            "losses": len([item for item in items if float(item.get("pnl") or 0.0) < 0]),
            "win_rate": round(win_rate, 4),
            "score": round(score, 4),
        }

    def _find(self, rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
        return next((row for row in rows if str(row.get("key")) == key), None)

    def _mode(self, item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        return str(metadata.get("evidence_mode") or "").lower()

    def _weight(self, item: dict[str, Any]) -> float:
        return _EVIDENCE_WEIGHTS.get(self._mode(item), 0.0)

    def _symbol(self, item: dict[str, Any]) -> str:
        return self._symbol_key(str(item.get("symbol") or ""))

    def _symbol_key(self, symbol: str) -> str:
        return "".join(char for char in symbol.upper() if char.isalnum())

    def _hour(self, item: dict[str, Any]) -> int | None:
        value = item.get("opened_at") or item.get("closed_at")
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).hour
