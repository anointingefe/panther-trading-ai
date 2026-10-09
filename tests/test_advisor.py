from __future__ import annotations

from datetime import datetime, timezone

from panther_trading.advisor import MarketTrapDetector, PositionSizingManager
from panther_trading.config import (
    AppConfig,
    DemoAutoConfig,
    ExecutionConfig,
    PantherConfig,
    RiskConfig,
    StrategyConfig,
    ValidationConfig,
)
from panther_trading.models import Candle, SignalSide, TradeSignal


def _config() -> PantherConfig:
    return PantherConfig(
        app=AppConfig(mode="paper", symbol="EURUSD", timeframe="M15", candles=120),
        risk=RiskConfig(
            account_equity=10000,
            max_risk_per_trade_pct=1.0,
            max_daily_loss_pct=3.0,
            min_confidence=0.62,
            max_open_positions=3,
        ),
        strategy=StrategyConfig(fast_sma=10, slow_sma=30, sentiment_weight=0.25),
        execution=ExecutionConfig(allow_live_trading=False, default_volume=0.01),
        demo_auto=DemoAutoConfig(),
        validation=ValidationConfig(),
    )


def _signal() -> TradeSignal:
    return TradeSignal(
        symbol="EURUSD",
        side=SignalSide.BUY,
        confidence=0.7,
        entry=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        rationale=(),
        generated_at=datetime.now(timezone.utc),
    )


def test_position_sizing_reduces_after_three_losses() -> None:
    closed = [
        {"status": "closed", "pnl": -1},
        {"status": "closed", "pnl": -1},
        {"status": "closed", "pnl": -1},
    ]

    plan = PositionSizingManager().plan(_config(), _signal(), closed)

    assert plan["sizing_multiplier"] == 0.5
    assert plan["adjusted_risk_pct"] == 0.5
    assert plan["max_simultaneous_trades"] == 3


def test_trap_detector_flags_macro_conflict() -> None:
    candles = [
        Candle(datetime.now(timezone.utc), 1.1, 1.101, 1.099, 1.1, 100 + index)
        for index in range(30)
    ]

    report = MarketTrapDetector().analyze(
        "EURUSD",
        SignalSide.BUY,
        candles,
        {"score": -0.5},
    )

    assert report["verdict"] == "caution"
    assert "conflicts" in report["reasonsNotToEnter"][0]
