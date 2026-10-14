from __future__ import annotations

from datetime import datetime, timedelta, timezone

from panther_trading.config import AppConfig, BeastModeConfig, DemoAutoConfig, ExecutionConfig, PantherConfig, RiskConfig, StrategyConfig, ValidationConfig
from panther_trading.green_flag import RealMoneyGreenFlag
from panther_trading.live_guard import LiveTradingGate


def _config() -> PantherConfig:
    return PantherConfig(
        app=AppConfig(mode="paper", symbol="EURUSD", timeframe="M15", candles=120),
        risk=RiskConfig(account_equity=10000, max_risk_per_trade_pct=0.5, max_daily_loss_pct=2, min_confidence=0.6, max_open_positions=5),
        strategy=StrategyConfig(fast_sma=8, slow_sma=21, sentiment_weight=0.25),
        execution=ExecutionConfig(allow_live_trading=True, default_volume=0.01, max_live_volume=0.02, allowed_live_account_modes=("live",)),
        demo_auto=DemoAutoConfig(),
        validation=ValidationConfig(min_demo_trades=30, min_demo_days=14, min_profit_factor=1.2, min_net_r=5, min_win_rate=0.35, max_drawdown_r=6),
        beast_mode=BeastModeConfig(),
    )


def _position(index: int, r: float, *, stop_loss: float = 0.99, take_profit: float = 1.02) -> dict:
    return {
        "id": f"pos-{index}",
        "status": "closed",
        "symbol": "EURUSD",
        "side": "buy",
        "volume": 1,
        "entry": 1.0,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "closed_at": (datetime(2026, 2, 1, 10, tzinfo=timezone.utc) + timedelta(days=index)).isoformat(),
        "pnl": round(r * abs(1.0 - stop_loss), 5),
    }


def test_green_flag_blocks_before_real_money_sample_is_large_enough() -> None:
    config = _config()
    positions = [_position(index, 1.0) for index in range(35)]
    edge = {
        "status": "passed",
        "trading_days": 20,
    }

    report = RealMoneyGreenFlag(config).evaluate(positions, edge, {"name": "MetaTrader 5", "connected": True})

    assert not report.passed
    assert report.status == "building_evidence"
    assert any("100 closed demo trades" in reason for reason in report.reasons)


def test_green_flag_passes_only_clean_recent_protected_demo_evidence() -> None:
    config = _config()
    results = ([1.0] * 70) + ([-0.4] * 20) + ([1.2] * 20)
    positions = [_position(index, result) for index, result in enumerate(results, start=1)]
    edge = {
        "status": "passed",
        "trading_days": 24,
    }

    report = RealMoneyGreenFlag(config).evaluate(positions, edge, {"name": "MetaTrader 5", "connected": True})

    assert report.passed
    assert report.status == "passed"
    assert report.score >= 80
    assert report.protected_trade_rate == 1.0
    assert report.take_profit_rate == 1.0


def test_green_flag_blocks_missing_take_profit_and_recent_loss_streak() -> None:
    config = _config()
    results = ([1.0] * 96) + ([-0.8] * 5)
    positions = [
        _position(index, result, take_profit=0 if index in {12, 24, 36} else 1.02)
        for index, result in enumerate(results, start=1)
    ]
    edge = {
        "status": "passed",
        "trading_days": 22,
    }

    report = RealMoneyGreenFlag(config).evaluate(positions, edge, {"name": "MetaTrader 5", "connected": True})

    assert not report.passed
    assert report.consecutive_losses == 5
    assert any("take-profit" in reason for reason in report.reasons)
    assert any("loss streak" in reason for reason in report.reasons)


def test_green_flag_ignores_live_mt5_history() -> None:
    config = _config()
    positions = [_position(index, 1.0) for index in range(110)]
    for position in positions:
        position["metadata"] = {"source": "mt5", "comment": "PANTHER live auto"}
    edge = {
        "status": "passed",
        "trading_days": 24,
    }

    report = RealMoneyGreenFlag(config).evaluate(positions, edge, {"name": "MetaTrader 5", "connected": True})

    assert not report.passed
    assert report.status == "building_evidence"
    assert report.closed_trades == 0
    assert report.recent_trades == 0


def test_live_guard_blocks_when_green_flag_fails_even_if_edge_passes() -> None:
    config = _config()
    readiness = LiveTradingGate(config.execution).readiness(
        broker_status={"name": "MetaTrader 5", "connected": True, "mode": "live"},
        approval_status="approved",
        requested_volume=0.01,
        unlock_phrase=config.execution.live_unlock_phrase,
        edge_validation_status="passed",
        green_flag_status="building_evidence",
    )

    assert not readiness.armed
    assert any("green flag" in reason for reason in readiness.reasons)
