from datetime import datetime, timezone

from panther_trading.config import RiskConfig
from panther_trading.models import SignalSide, TradeSignal
from panther_trading.risk import RiskManager


def test_risk_manager_blocks_low_confidence_signal() -> None:
    manager = RiskManager(
        RiskConfig(
            account_equity=10000,
            max_risk_per_trade_pct=1,
            max_daily_loss_pct=3,
            min_confidence=0.7,
            max_open_positions=3,
        )
    )
    signal = TradeSignal(
        symbol="EURUSD",
        side=SignalSide.BUY,
        confidence=0.5,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        rationale=("test",),
        generated_at=datetime.now(timezone.utc),
    )

    decision = manager.evaluate(signal, open_positions=0)

    assert not decision.allowed
    assert "confidence" in decision.reason
