from __future__ import annotations

from datetime import datetime, timezone

from panther_trading.adaptive_learning import AdaptiveLearningEngine


def _closed(symbol: str, pnl: float, mode: str, hour: int = 10) -> dict:
    opened = datetime(2026, 10, 1, hour, tzinfo=timezone.utc).isoformat()
    return {
        "status": "closed",
        "symbol": symbol,
        "pnl": pnl,
        "opened_at": opened,
        "closed_at": opened,
        "metadata": {"evidence_mode": mode},
    }


def test_adaptive_learning_can_veto_repeatedly_weak_symbol() -> None:
    positions = [_closed("EURUSD", -1.0, "live") for _ in range(6)]
    engine = AdaptiveLearningEngine()
    profile = engine.profile(positions)
    assessment = engine.assess(
        "EURUSD",
        datetime(2026, 10, 2, 10, tzinfo=timezone.utc),
        profile,
        minimum_samples=6,
    )

    assert assessment.block_reason is not None
    assert assessment.rank_adjustment < 0
    assert profile["live_samples"] == 6


def test_learning_changes_ranking_but_is_bounded() -> None:
    positions = [_closed("XAUUSD", 1.0, "demo") for _ in range(20)]
    engine = AdaptiveLearningEngine()
    assessment = engine.assess(
        "XAUUSD",
        datetime(2026, 10, 2, 10, tzinfo=timezone.utc),
        engine.profile(positions),
        minimum_samples=6,
    )

    assert assessment.block_reason is None
    assert 0 < assessment.rank_adjustment <= 0.08
    assert assessment.quality_score <= 1.0
