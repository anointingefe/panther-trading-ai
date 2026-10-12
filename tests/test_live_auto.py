from __future__ import annotations

from panther_trading.live_auto import LiveAutoRunner, LiveAutoTrader


def test_live_auto_status_exists_but_stays_locked(tmp_path) -> None:
    status = LiveAutoTrader("config/demo.yaml", tmp_path / "positions.jsonl").status()

    assert status["built"] is True
    assert status["armed"] is False
    assert status["enabled"] is False
    assert status["reasons"]


def test_live_auto_cycle_blocks_before_live_is_enabled(tmp_path) -> None:
    trader = LiveAutoTrader(
        "config/demo.yaml",
        tmp_path / "positions.jsonl",
        tmp_path / "live_auto_state.json",
        tmp_path / "goals.json",
    )

    cycle = trader.run_cycle(unlock_phrase="wrong")
    state = trader.latest_state()

    assert cycle.status == "blocked"
    assert cycle.placed == 0
    assert state["message"].startswith("Blocked:")


def test_live_auto_runner_status_reports_built_system(tmp_path) -> None:
    trader = LiveAutoTrader(
        "config/demo.yaml",
        tmp_path / "positions.jsonl",
        tmp_path / "live_auto_state.json",
        tmp_path / "goals.json",
    )
    runner = LiveAutoRunner(trader, interval_seconds=999)

    status = runner.status()

    assert status["built"] is True
    assert status["running"] is False
