from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TradingGoals:
    daily_target: float = 25.0
    weekly_target: float = 125.0
    monthly_target: float = 500.0
    currency: str = "USD"
    updated_at: str = ""


class GoalTracker:
    """Tracks editable trading targets against closed demo trade performance."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> TradingGoals:
        if not self.path.exists():
            return self._default_goals()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self._default_goals()
        return TradingGoals(
            daily_target=self._positive_float(raw.get("daily_target"), 25.0),
            weekly_target=self._positive_float(raw.get("weekly_target"), 125.0),
            monthly_target=self._positive_float(raw.get("monthly_target"), 500.0),
            currency=str(raw.get("currency") or "USD").upper()[:8],
            updated_at=str(raw.get("updated_at") or ""),
        )

    def update(self, payload: dict[str, Any]) -> TradingGoals:
        current = self.load()
        goals = TradingGoals(
            daily_target=self._positive_float(payload.get("daily_target", payload.get("dailyTarget")), current.daily_target),
            weekly_target=self._positive_float(payload.get("weekly_target", payload.get("weeklyTarget")), current.weekly_target),
            monthly_target=self._positive_float(payload.get("monthly_target", payload.get("monthlyTarget")), current.monthly_target),
            currency=str(payload.get("currency") or current.currency or "USD").upper()[:8],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self.path.write_text(json.dumps(asdict(goals), indent=2), encoding="utf-8")
        return goals

    def report(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        goals = self.load()
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        month_start = day_start.replace(day=1)
        closed = [position for position in positions if position.get("status") == "closed"]
        performance = self._stats(closed)
        return {
            "targets": {
                "daily": goals.daily_target,
                "weekly": goals.weekly_target,
                "monthly": goals.monthly_target,
                "currency": goals.currency,
                "updatedAt": goals.updated_at,
            },
            "progress": {
                "daily": self._period_report(closed, day_start, goals.daily_target),
                "weekly": self._period_report(closed, week_start, goals.weekly_target),
                "monthly": self._period_report(closed, month_start, goals.monthly_target),
            },
            "performance": performance,
            "goalMode": self._goal_mode(goals, closed, day_start, week_start, month_start),
        }

    def goal_pressure(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        report = self.report(positions)
        progress = report["progress"]
        daily = progress["daily"]
        weekly = progress["weekly"]
        monthly = progress["monthly"]
        return {
            "daily_target_met": daily["remaining"] <= 0,
            "weekly_target_met": weekly["remaining"] <= 0,
            "monthly_target_met": monthly["remaining"] <= 0,
            "daily_progress": daily["percent"],
            "weekly_progress": weekly["percent"],
            "monthly_progress": monthly["percent"],
            "mode": report["goalMode"],
        }

    def _period_report(self, positions: list[dict[str, Any]], start: datetime, target: float) -> dict[str, Any]:
        period_positions = [
            position
            for position in positions
            if (closed_at := self._parse_time(position.get("closed_at"))) and closed_at >= start
        ]
        stats = self._stats(period_positions)
        remaining = max(target - stats["netPnl"], 0.0)
        percent = stats["netPnl"] / target if target > 0 else 0.0
        return {
            **stats,
            "target": round(target, 2),
            "remaining": round(remaining, 2),
            "percent": round(percent, 4),
        }

    def _stats(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        pnls = [float(position.get("pnl") or 0.0) for position in positions]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        return {
            "closedTrades": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "winRate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "grossProfit": round(gross_profit, 2),
            "grossLoss": round(gross_loss, 2),
            "netPnl": round(sum(pnls), 2),
            "profitFactor": round(gross_profit / gross_loss, 4) if gross_loss else round(gross_profit, 4),
            "averageWin": round(gross_profit / len(wins), 2) if wins else 0.0,
            "averageLoss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        }

    def _goal_mode(
        self,
        goals: TradingGoals,
        positions: list[dict[str, Any]],
        day_start: datetime,
        week_start: datetime,
        month_start: datetime,
    ) -> str:
        daily = self._period_report(positions, day_start, goals.daily_target)
        weekly = self._period_report(positions, week_start, goals.weekly_target)
        monthly = self._period_report(positions, month_start, goals.monthly_target)
        if daily["remaining"] <= 0:
            return "daily_target_met_protect_gains"
        if weekly["remaining"] <= 0:
            return "weekly_target_met_reduce_risk"
        if monthly["remaining"] <= 0:
            return "monthly_target_met_preserve_capital"
        if daily["percent"] < 0:
            return "recovery_mode_cut_size"
        return "target_tracking"

    def _default_goals(self) -> TradingGoals:
        return TradingGoals(updated_at=datetime.now(timezone.utc).isoformat())

    def _positive_float(self, value: Any, fallback: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = fallback
        return round(max(number, 0.0), 2)

    def _parse_time(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
