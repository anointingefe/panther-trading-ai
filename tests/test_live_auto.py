from __future__ import annotations

from panther_trading.live_auto import LiveAutoTrader


def test_live_auto_status_exists_but_stays_locked(tmp_path) -> None:
    status = LiveAutoTrader("config/demo.yaml", tmp_path / "positions.jsonl").status()

    assert status["built"] is True
    assert status["armed"] is False
    assert status["enabled"] is False
    assert status["reasons"]
