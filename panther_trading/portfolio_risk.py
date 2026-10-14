from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from panther_trading.brokers.base import Broker
from panther_trading.models import SignalSide, TradeSignal


@dataclass(frozen=True)
class PortfolioRiskSnapshot:
    equity: float
    open_positions: int
    total_open_risk: float
    total_open_risk_pct: float
    portfolio_cap_amount: float
    bucket_cap_amount: float
    bucket_risk: dict[str, float]
    bucket_risk_pct: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApprovedLivePortfolioRisk:
    """Aggregate-risk guard for explicitly approved live orders.

    It does not decide whether a signal is good enough to trade. It only limits
    how much additional broker-estimated stop-loss risk may be added after the
    existing strategy, approval, green-flag, and execution checks have passed.
    """

    def __init__(
        self,
        broker: Broker,
        equity: float,
        max_portfolio_risk_pct: float,
        max_exposure_bucket_risk_pct: float,
    ) -> None:
        self.broker = broker
        self.equity = float(equity)
        self.max_portfolio_risk_pct = float(max_portfolio_risk_pct)
        self.max_exposure_bucket_risk_pct = float(max_exposure_bucket_risk_pct)

    def snapshot(self) -> PortfolioRiskSnapshot:
        if not math.isfinite(self.equity) or self.equity <= 0:
            raise ValueError("Portfolio risk requires positive finite equity")
        if not math.isfinite(self.max_portfolio_risk_pct) or self.max_portfolio_risk_pct <= 0:
            raise ValueError("Portfolio risk cap must be positive")
        if not math.isfinite(self.max_exposure_bucket_risk_pct) or self.max_exposure_bucket_risk_pct <= 0:
            raise ValueError("Exposure bucket risk cap must be positive")

        total_risk = 0.0
        bucket_risk: dict[str, float] = {}
        positions = list(self.broker.open_positions())
        for position in positions:
            try:
                side = SignalSide(str(position.get("side")))
                symbol = str(position.get("symbol") or "")
                volume = float(position.get("volume") or 0.0)
                entry = float(position.get("entry") or 0.0)
                stop_loss = float(position.get("stop_loss") or 0.0)
            except (TypeError, ValueError):
                continue
            risk = self.broker.estimate_position_risk(symbol, side, volume, entry, stop_loss)
            if not math.isfinite(risk) or risk <= 0:
                continue
            total_risk += risk
            for bucket in exposure_buckets(symbol, side):
                bucket_risk[bucket] = bucket_risk.get(bucket, 0.0) + risk

        pct = lambda amount: round((amount / self.equity) * 100, 4) if self.equity > 0 else 0.0
        return PortfolioRiskSnapshot(
            equity=self.equity,
            open_positions=len(positions),
            total_open_risk=round(total_risk, 4),
            total_open_risk_pct=pct(total_risk),
            portfolio_cap_amount=round(self.equity * self.max_portfolio_risk_pct / 100, 4),
            bucket_cap_amount=round(self.equity * self.max_exposure_bucket_risk_pct / 100, 4),
            bucket_risk={key: round(value, 4) for key, value in sorted(bucket_risk.items())},
            bucket_risk_pct={key: pct(value) for key, value in sorted(bucket_risk.items())},
        )

    def available_risk_for(self, signal: TradeSignal) -> tuple[float, PortfolioRiskSnapshot, tuple[str, ...]]:
        snapshot = self.snapshot()
        remaining = snapshot.portfolio_cap_amount - snapshot.total_open_risk
        reasons: list[str] = []
        if remaining <= 0:
            reasons.append("Approved-live portfolio risk budget is fully allocated")

        for bucket in exposure_buckets(signal.symbol, signal.side):
            bucket_remaining = snapshot.bucket_cap_amount - snapshot.bucket_risk.get(bucket, 0.0)
            remaining = min(remaining, bucket_remaining)
            if bucket_remaining <= 0:
                reasons.append(f"Exposure bucket {bucket} is at its risk cap")

        return max(round(remaining, 4), 0.0), snapshot, tuple(reasons)


def exposure_buckets(symbol: str, side: SignalSide) -> tuple[str, ...]:
    """Return simple directional exposure buckets for concentration control.

    Six-letter alpha symbols (FX, metals such as XAUUSD, and similar pairs) are
    treated as base/quote pairs. Other symbols fall back to a symbol-direction
    bucket so they still receive concentration control without pretending a
    correlation model exists where Panther has no evidence.
    """
    clean = "".join(char for char in symbol.upper() if char.isalpha())
    if side not in {SignalSide.BUY, SignalSide.SELL}:
        return (f"{clean or symbol.upper()}:HOLD",)
    direction = 1 if side == SignalSide.BUY else -1
    if len(clean) >= 6:
        base = clean[:3]
        quote = clean[3:6]
        base_bucket = f"{'LONG' if direction > 0 else 'SHORT'}_{base}"
        quote_bucket = f"{'SHORT' if direction > 0 else 'LONG'}_{quote}"
        return (base_bucket, quote_bucket)
    return (f"{'LONG' if direction > 0 else 'SHORT'}_{clean or symbol.upper()}",)
