from __future__ import annotations

from dataclasses import dataclass
import math

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
        if signal.side not in {SignalSide.BUY, SignalSide.SELL}:
            return RiskDecision(False, "Invalid signal side")
        if not math.isfinite(signal.confidence) or not 0 <= signal.confidence <= 1:
            return RiskDecision(False, "Invalid signal confidence")
        if any(not math.isfinite(value) or value <= 0 for value in (signal.entry, signal.stop_loss, signal.take_profit)):
            return RiskDecision(False, "Signal prices must be finite and positive")
        if signal.side == SignalSide.BUY and not signal.stop_loss < signal.entry < signal.take_profit:
            return RiskDecision(False, "Invalid buy stop-loss/take-profit direction")
        if signal.side == SignalSide.SELL and not signal.take_profit < signal.entry < signal.stop_loss:
            return RiskDecision(False, "Invalid sell stop-loss/take-profit direction")
        limits = (self.config.account_equity, self.config.max_daily_loss_pct, self.config.max_risk_per_trade_pct)
        if any(not math.isfinite(value) or value <= 0 for value in limits):
            return RiskDecision(False, "Invalid account or risk configuration")
        if not math.isfinite(self.config.min_confidence) or not 0 <= self.config.min_confidence <= 1:
            return RiskDecision(False, "Invalid minimum confidence configuration")
        if not math.isfinite(daily_pnl) or open_positions < 0:
            return RiskDecision(False, "Invalid portfolio state")
        if signal.confidence < self.config.min_confidence:
            return RiskDecision(
                False,
                f"Signal confidence {signal.confidence:.0%} is below minimum {self.config.min_confidence:.0%}",
            )
        if open_positions >= self.config.max_open_positions:
            return RiskDecision(False, "Maximum open positions reached")

        max_daily_loss = self.config.account_equity * (self.config.max_daily_loss_pct / 100)
        if daily_pnl <= -max_daily_loss:
            return RiskDecision(False, "Daily loss limit reached")

        trade_risk = abs(signal.entry - signal.stop_loss)
        if trade_risk <= 0:
            return RiskDecision(False, "Invalid stop-loss distance")

        return RiskDecision(True, "Risk checks passed")
