from __future__ import annotations

from dataclasses import dataclass

from panther_trading.config import RiskConfig
from panther_trading.models import SignalSide, TradeSignal


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    def evaluate(self, signal: TradeSignal, open_positions: int, daily_pnl: float = 0.0) -> RiskDecision:
        if signal.side == SignalSide.HOLD:
            return RiskDecision(False, "Signal is hold")
        if signal.confidence < self.config.min_confidence:
            return RiskDecision(False, "Signal confidence is below minimum")
        if open_positions >= self.config.max_open_positions:
            return RiskDecision(False, "Maximum open positions reached")

        max_daily_loss = self.config.account_equity * (self.config.max_daily_loss_pct / 100)
        if daily_pnl <= -max_daily_loss:
            return RiskDecision(False, "Daily loss limit reached")

        trade_risk = abs(signal.entry - signal.stop_loss)
        if trade_risk <= 0:
            return RiskDecision(False, "Invalid stop-loss distance")

        return RiskDecision(True, "Risk checks passed")
