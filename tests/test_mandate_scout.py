from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from panther_trading.config import load_config
from panther_trading.mandate_scout import BalancedMandateLiveScoutTrader
from panther_trading.models import SignalSide, TradeSignal


def _trader(tmp_path) -> BalancedMandateLiveScoutTrader:
    return BalancedMandateLiveScoutTrader(
        "config/demo.yaml",
        state_path=tmp_path / "live_scout.json",
        positions_path=tmp_path / "positions.jsonl",
        goals_path=tmp_path / "goals.json",
        beast_mode_path=tmp_path / "beast.json",
    )


def test_balanced_mandate_uses_compromise_thresholds(tmp_path) -> None:
    trader = _trader(tmp_path)
    config = load_config("config/demo.yaml")
    recent = {"degraded": False}

    effective = trader._effective_thresholds(config, recent)

    assert effective == {
        "confidence": 0.78,
        "edgeProbability": 0.62,
        "learningQuality": 0.65,
    }
    assert config.live_scout.model_max_open_positions == 10
    assert config.live_scout.model_max_portfolio_risk_pct == 2.5
    assert config.live_scout.model_max_exposure_bucket_risk_pct == 1.25
    assert config.live_scout.mandate_max_risk_per_trade_pct == 0.40
    assert config.live_scout.mandate_daily_loss_stop_pct == 2.0
    assert config.execution.allow_live_trading is False
    assert config.execution.require_manual_approval is True


def test_degraded_recent_performance_tightens_thresholds(tmp_path) -> None:
    trader = _trader(tmp_path)
    config = load_config("config/demo.yaml")
    positions = []
    for index in range(8):
        positions.append(
            {
                "status": "closed",
                "closed_at": f"2026-10-{index + 1:02d}T12:00:00+00:00",
                "pnl": 1.0 if index < 3 else -1.0,
                "metadata": {"evidence_mode": "demo"},
            }
        )

    recent = trader._recent_performance(
        positions,
        window=config.live_scout.mandate_recent_window_trades,
        minimum_samples=config.live_scout.mandate_adaptive_min_samples,
        degraded_win_rate=config.live_scout.mandate_degraded_win_rate,
    )
    effective = trader._effective_thresholds(config, recent)

    assert recent["degraded"] is True
    assert recent["winRate"] == 0.375
    assert effective == {
        "confidence": 0.82,
        "edgeProbability": 0.65,
        "learningQuality": 0.70,
    }


def test_mandate_learning_quality_uses_symbol_and_hour_evidence(tmp_path) -> None:
    trader = _trader(tmp_path)
    profile = {
        "symbols": [{"key": "EURUSD", "samples": 10, "win_rate": 0.72}],
        "utc_hours": [{"key": "10", "samples": 8, "win_rate": 0.60}],
    }

    quality = trader._mandate_learning_quality(
        profile,
        "EURUSD",
        datetime(2026, 10, 14, 10, 30, tzinfo=timezone.utc),
        minimum_samples=6,
    )

    assert quality == 0.68


def test_daily_loss_breaker_blocks_new_mandate_candidates(tmp_path) -> None:
    trader = _trader(tmp_path)
    config = load_config("config/demo.yaml")

    decision = trader._evaluate_symbol(
        config,
        broker=None,
        helper=None,
        learning_engine=None,
        learning={},
        symbol="EURUSD",
        positions=[],
        loss_state={},
        goal_pressure={},
        daily_pnl=-200.0,
    )

    assert decision.status == "blocked"
    assert "daily loss breaker reached" in decision.reason.lower()
    assert decision.portfolio_risk["mandate"]["breaker"] == "daily_loss_stop"


class _RiskCaptureBroker:
    def __init__(self) -> None:
        self.last_risk_amount = None

    def get_status(self):
        return SimpleNamespace(equity=10000.0)

    def calculate_position_volume(
        self,
        symbol,
        side,
        entry,
        stop_loss,
        risk_amount,
        max_volume,
    ):
        self.last_risk_amount = risk_amount
        return 0.01


def test_mandate_position_sizing_caps_risk_at_point_four_percent(tmp_path) -> None:
    trader = _trader(tmp_path)
    config = load_config("config/demo.yaml")
    broker = _RiskCaptureBroker()
    signal = TradeSignal(
        symbol="EURUSD",
        side=SignalSide.BUY,
        confidence=0.90,
        entry=1.10,
        stop_loss=1.09,
        take_profit=1.12,
        rationale=("test",),
        generated_at=datetime.now(timezone.utc),
    )

    volume = trader._live_volume(
        config,
        broker,
        signal,
        {"daily_progress": 0.1, "weekly_progress": 0.2, "monthly_progress": 0.2},
    )

    assert volume == 0.01
    assert broker.last_risk_amount == 40.0
