from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from panther_trading.config import ValidationConfig


@dataclass(frozen=True)
class EdgeValidationReport:
    status: str
    passed: bool
    reasons: tuple[str, ...]
    closed_trades: int
    trading_days: int
    wins: int
    losses: int
    win_rate: float
    gross_profit_r: float
    gross_loss_r: float
    profit_factor: float
    net_r: float
    max_drawdown_r: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EdgeValidationGate:
    def __init__(self, config: ValidationConfig) -> None:
        self.config = config

    def evaluate(self, positions: list[dict[str, Any]]) -> EdgeValidationReport:
        """Evaluate only completed demo positions using stop-normalized returns.

        Open positions are intentionally excluded: an unfinished trade cannot
        prove strategy edge and must never help unlock live execution.
        """
        closed = [position for position in positions if position.get("status") == "closed"]
        r_values = [self._position_r(position) for position in closed]
        wins = len([value for value in r_values if value > 0])
        losses = len([value for value in r_values if value < 0])
        closed_trades = len(r_values)
        trading_days = self._trading_days(closed)
        gross_profit = round(sum(value for value in r_values if value > 0), 4)
        gross_loss = round(abs(sum(value for value in r_values if value < 0)), 4)
        profit_factor = round(gross_profit / gross_loss, 4) if gross_loss else round(gross_profit, 4)
        net_r = round(sum(r_values), 4)
        win_rate = round(wins / closed_trades, 4) if closed_trades else 0.0
        max_drawdown = self._max_drawdown(r_values)
        reasons = self._reasons(closed_trades, trading_days, profit_factor, net_r, win_rate, max_drawdown)
        passed = not reasons
        status = "passed" if passed else "insufficient_data" if closed_trades < self.config.min_demo_trades else "failed"

        return EdgeValidationReport(
            status=status,
            passed=passed,
            reasons=tuple(reasons),
            closed_trades=closed_trades,
            trading_days=trading_days,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            gross_profit_r=gross_profit,
            gross_loss_r=gross_loss,
            profit_factor=profit_factor,
            net_r=net_r,
            max_drawdown_r=max_drawdown,
        )

    def _position_r(self, position: dict[str, Any]) -> float:
        pnl = float(position.get("pnl") or 0.0)
        entry = float(position["entry"])
        stop_loss = float(position["stop_loss"])
        volume = float(position.get("volume") or 1)
        risk = abs(entry - stop_loss) * volume
        if risk <= 0:
            return 0.0
        return round(pnl / risk, 4)

    def _trading_days(self, positions: list[dict[str, Any]]) -> int:
        days: set[str] = set()
        for position in positions:
            closed_at = position.get("closed_at")
            if not closed_at:
                continue
            try:
                days.add(datetime.fromisoformat(closed_at).date().isoformat())
            except ValueError:
                continue
        return len(days)

    def _max_drawdown(self, values: list[float]) -> float:
        peak = 0.0
        equity = 0.0
        drawdown = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        return round(drawdown, 4)

    def _reasons(
        self,
        closed_trades: int,
        trading_days: int,
        profit_factor: float,
        net_r: float,
        win_rate: float,
        max_drawdown: float,
    ) -> list[str]:
        reasons: list[str] = []
        if closed_trades < self.config.min_demo_trades:
            reasons.append(f"Needs at least {self.config.min_demo_trades} closed demo trades.")
        if trading_days < self.config.min_demo_days:
            reasons.append(f"Needs at least {self.config.min_demo_days} separate demo trading days.")
        if profit_factor < self.config.min_profit_factor:
            reasons.append(f"Profit factor must be at least {self.config.min_profit_factor}.")
        if net_r < self.config.min_net_r:
            reasons.append(f"Net R must be at least {self.config.min_net_r}.")
        if win_rate < self.config.min_win_rate:
            reasons.append(f"Win rate must be at least {self.config.min_win_rate:.0%}.")
        if max_drawdown > self.config.max_drawdown_r:
            reasons.append(f"Max drawdown must stay below {self.config.max_drawdown_r}R.")
        return reasons
