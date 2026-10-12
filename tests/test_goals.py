import json
from datetime import datetime, timedelta, timezone

from panther_trading.goals import GoalTracker


def test_goal_tracker_reports_daily_weekly_monthly_progress(tmp_path) -> None:
    tracker = GoalTracker(tmp_path / "goals.json")
    tracker.update({"dailyTarget": 10, "weeklyTarget": 50, "monthlyTarget": 100})
    now = datetime.now(timezone.utc)
    positions = [
        {"status": "closed", "pnl": 7.5, "closed_at": now.isoformat()},
        {"status": "closed", "pnl": -2.5, "closed_at": now.isoformat()},
        {"status": "closed", "pnl": 20, "closed_at": (now - timedelta(days=3)).isoformat()},
        {"status": "open", "pnl": 999, "closed_at": now.isoformat()},
    ]

    report = tracker.report(positions)

    assert report["targets"]["daily"] == 10
    assert report["progress"]["daily"]["netPnl"] == 5
    assert report["progress"]["daily"]["remaining"] == 5
    assert report["performance"]["closedTrades"] == 3
    assert report["performance"]["wins"] == 2
    assert report["performance"]["losses"] == 1


def test_goal_tracker_enters_protect_mode_after_daily_target(tmp_path) -> None:
    goals = tmp_path / "goals.json"
    goals.write_text(
        json.dumps(
            {
                "daily_target": 5,
                "weekly_target": 100,
                "monthly_target": 300,
                "currency": "USD",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    tracker = GoalTracker(goals)
    positions = [
        {
            "status": "closed",
            "pnl": 6,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }
    ]

    pressure = tracker.goal_pressure(positions)

    assert pressure["daily_target_met"] is True
    assert pressure["mode"] == "daily_target_met_protect_gains"
