from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from panther_trading.config import PantherConfig
from panther_trading.evidence import is_demo_evidence


@dataclass(frozen=True)
class GreenFlagReport:
    status: str
    passed: bool
    score: float
    reasons: tuple[str, ...]
    checklist: tuple[str, ...]
    closed_trades: int
    recent_trades: int
    protected_trade_rate: float
    take_profit_rate: float
    recent_win_rate: float
    recent_profit_factor: float
    recent_net_r: float
    recent_max_drawdown_r: float
    consecutive_losses: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RealMoneyGreenFlag:
    """Final real-money readiness check.

    This is deliberately stricter than the normal demo edge validation. The edge
    gate can say the strategy is improving; this gate says whether the evidence
    is clean enough to even consider live funds.
    """

    def __init__(self, config: PantherConfig) -> None:
        self.config = config
        self.minimum_closed_trades = max(config.validation.min_demo_trades * 3, 100)
        self.minimum_trading_days = max(config.validation.min_demo_days, 20)
        self.minimum_recent_trades = 20
        self.minimum_recent_win_rate = max(config.validation.min_win_rate, 0.48)
        self.minimum_recent_profit_factor = max(config.validation.min_profit_factor, 1.35)
        self.minimum_recent_net_r = 3.0
        self.maximum_recent_drawdown_r = min(config.validation.max_drawdown_r, 4.0)
        self.maximum_consecutive_losses = 4
        self.minimum_protected_trade_rate = 1.0
        self.minimum_take_profit_rate = 0.98

    def evaluate(
        self,
        positions: list[dict[str, Any]],
        edge_validation: dict[str, Any],
        broker_status: dict[str, Any] | None = None,
    ) -> GreenFlagReport:
        closed = [
            position
            for position in positions
            if position.get("status") == "closed" and is_demo_evidence(position)
        ]
        closed = sorted(closed, key=self._closed_sort_key)
        recent = closed[-self.minimum_recent_trades :]
        r_values = [self._position_r(position) for position in recent]
        protected_rate = self._protected_rate(closed)
        take_profit_rate = self._take_profit_rate(closed)
        recent_win_rate = self._win_rate(r_values)
        recent_profit_factor = self._profit_factor(r_values)
        recent_net_r = round(sum(r_values), 4)
        recent_drawdown = self._max_drawdown(r_values)
        loss_streak = self._consecutive_losses(closed)
        trading_days = int(edge_validation.get("trading_days") or 0)
        reasons = self._reasons(
            edge_validation=edge_validation,
            closed_trades=len(closed),
            trading_days=trading_days,
            recent_count=len(recent),
            protected_rate=protected_rate,
            take_profit_rate=take_profit_rate,
            recent_win_rate=recent_win_rate,
            recent_profit_factor=recent_profit_factor,
            recent_net_r=recent_net_r,
            recent_drawdown=recent_drawdown,
            loss_streak=loss_streak,
            broker_status=broker_status or {},
        )
        score = self._score(
            edge_validation=edge_validation,
            closed_trades=len(closed),
            trading_days=trading_days,
            protected_rate=protected_rate,
            take_profit_rate=take_profit_rate,
            recent_win_rate=recent_win_rate,
            recent_profit_factor=recent_profit_factor,
            recent_net_r=recent_net_r,
            recent_drawdown=recent_drawdown,
            loss_streak=loss_streak,
        )
        passed = not reasons
        status = "passed" if passed else "building_evidence" if len(closed) < self.minimum_closed_trades else "blocked"
        return GreenFlagReport(
            status=status,
            passed=passed,
            score=score,
            reasons=tuple(reasons),
            checklist=tuple(self._checklist()),
            closed_trades=len(closed),
            recent_trades=len(recent),
            protected_trade_rate=protected_rate,
            take_profit_rate=take_profit_rate,
            recent_win_rate=recent_win_rate,
            recent_profit_factor=recent_profit_factor,
            recent_net_r=recent_net_r,
            recent_max_drawdown_r=recent_drawdown,
            consecutive_losses=loss_streak,
        )

    def _checklist(self) -> list[str]:
        return [
            f"At least {self.minimum_closed_trades} closed demo trades.",
            f"At least {self.minimum_trading_days} separate demo trading days.",
            "Every closed demo trade must have a stop loss recorded.",
            "Almost every closed demo trade must have a take-profit target recorded.",
            f"Last {self.minimum_recent_trades} trades must hold win rate >= {self.minimum_recent_win_rate:.0%}.",
            f"Last {self.minimum_recent_trades} trades must hold profit factor >= {self.minimum_recent_profit_factor:.2f}.",
            f"Last {self.minimum_recent_trades} trades must be at least +{self.minimum_recent_net_r:.1f}R net.",
            f"Recent drawdown must stay under {self.maximum_recent_drawdown_r:.1f}R.",
            f"Current loss streak must stay below {self.maximum_consecutive_losses + 1} losses.",
            "MT5 must be connected before the final live check can pass.",
        ]

    def _reasons(
        self,
        *,
        edge_validation: dict[str, Any],
        closed_trades: int,
        trading_days: int,
        recent_count: int,
        protected_rate: float,
        take_profit_rate: float,
        recent_win_rate: float,
        recent_profit_factor: float,
        recent_net_r: float,
        recent_drawdown: float,
        loss_streak: int,
        broker_status: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        if edge_validation.get("status") != "passed":
            reasons.append("Base demo edge validation has not passed yet.")
        if closed_trades < self.minimum_closed_trades:
            reasons.append(f"Needs at least {self.minimum_closed_trades} closed demo trades before real money.")
        if trading_days < self.minimum_trading_days:
            reasons.append(f"Needs at least {self.minimum_trading_days} separate demo trading days before real money.")
        if recent_count < self.minimum_recent_trades:
            reasons.append(f"Needs at least {self.minimum_recent_trades} recent closed trades for the final momentum check.")
        if protected_rate < self.minimum_protected_trade_rate:
            reasons.append("Every demo trade must have a recorded stop loss before live funding.")
        if take_profit_rate < self.minimum_take_profit_rate:
            reasons.append("Almost every demo trade must have a recorded take-profit target before live funding.")
        if recent_win_rate < self.minimum_recent_win_rate:
            reasons.append(f"Recent win rate must be at least {self.minimum_recent_win_rate:.0%}.")
        if recent_profit_factor < self.minimum_recent_profit_factor:
            reasons.append(f"Recent profit factor must be at least {self.minimum_recent_profit_factor:.2f}.")
        if recent_net_r < self.minimum_recent_net_r:
            reasons.append(f"Recent net result must be at least +{self.minimum_recent_net_r:.1f}R.")
        if recent_drawdown > self.maximum_recent_drawdown_r:
            reasons.append(f"Recent drawdown must stay below {self.maximum_recent_drawdown_r:.1f}R.")
        if loss_streak > self.maximum_consecutive_losses:
            reasons.append(f"Current loss streak is {loss_streak}; live funding waits until the streak is repaired.")
        if broker_status and not broker_status.get("connected"):
            reasons.append("MT5 broker is not connected for the final live check.")
        return reasons

    def _score(self, **metrics: Any) -> float:
        edge_validation = metrics["edge_validation"]
        score = 0.0
        score += min(metrics["closed_trades"] / self.minimum_closed_trades, 1.0) * 18
        score += min(metrics["trading_days"] / self.minimum_trading_days, 1.0) * 10
        score += 14 if edge_validation.get("status") == "passed" else 0
        score += metrics["protected_rate"] * 12
        score += metrics["take_profit_rate"] * 8
        score += min(metrics["recent_win_rate"] / self.minimum_recent_win_rate, 1.2) / 1.2 * 12
        score += min(metrics["recent_profit_factor"] / self.minimum_recent_profit_factor, 1.4) / 1.4 * 12
        score += min(max(metrics["recent_net_r"], 0.0) / self.minimum_recent_net_r, 1.0) * 8
        score += max(0.0, 1 - metrics["recent_drawdown"] / max(self.maximum_recent_drawdown_r, 0.01)) * 4
        score -= min(metrics["loss_streak"], 6) * 1.5
        return round(max(0.0, min(score, 100.0)), 2)

    def _closed_sort_key(self, position: dict[str, Any]) -> str:
        return str(position.get("closed_at") or position.get("opened_at") or "")

    def _position_r(self, position: dict[str, Any]) -> float:
        try:
            entry = float(position["entry"])
            stop_loss = float(position["stop_loss"])
            volume = float(position.get("volume") or 1)
            pnl = float(position.get("pnl") or 0)
        except (KeyError, TypeError, ValueError):
            return 0.0
        risk = abs(entry - stop_loss) * volume
        if risk <= 0:
            return 0.0
        return round(pnl / risk, 4)

    def _protected_rate(self, positions: list[dict[str, Any]]) -> float:
        if not positions:
            return 0.0
        protected = [position for position in positions if self._has_positive_number(position.get("stop_loss"))]
        return round(len(protected) / len(positions), 4)

    def _take_profit_rate(self, positions: list[dict[str, Any]]) -> float:
        if not positions:
            return 0.0
        targeted = [position for position in positions if self._has_positive_number(position.get("take_profit"))]
        return round(len(targeted) / len(positions), 4)

    def _has_positive_number(self, value: Any) -> bool:
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False

    def _win_rate(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return round(len([value for value in values if value > 0]) / len(values), 4)

    def _profit_factor(self, values: list[float]) -> float:
        gross_profit = sum(value for value in values if value > 0)
        gross_loss = abs(sum(value for value in values if value < 0))
        return round(gross_profit / gross_loss, 4) if gross_loss else round(gross_profit, 4)

    def _max_drawdown(self, values: list[float]) -> float:
        peak = 0.0
        equity = 0.0
        drawdown = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        return round(drawdown, 4)

    def _consecutive_losses(self, positions: list[dict[str, Any]]) -> int:
        streak = 0
        for position in reversed(positions):
            if self._position_r(position) < 0:
                streak += 1
            else:
                break
        return streak
