from panther_trading.api.snapshot import broker_status, build_dashboard_snapshot
from panther_trading.brokers import create_broker


def test_default_broker_is_simulated() -> None:
    broker = create_broker()
    status = broker.get_status()

    assert status.connected
    assert status.mode == "paper"
    assert status.symbols_total >= 40


def test_broker_status_is_safe_when_mt5_is_unavailable() -> None:
    status = broker_status("mt5")

    assert status["connected"] in {False, True}
    assert "message" in status


def test_dashboard_snapshot_includes_broker_guard() -> None:
    snapshot = build_dashboard_snapshot("config/demo.yaml", symbol="EURUSD")

    assert snapshot["broker"]["mode"] == "paper"
    assert snapshot["broker"]["symbols_total"] >= 40


def test_dashboard_snapshot_locks_live_mode_by_default() -> None:
    snapshot = build_dashboard_snapshot("config/demo.yaml", symbol="EURUSD")

    assert snapshot["executionMode"]["active"] == "demo"
    assert snapshot["executionMode"]["liveEnabled"] is False
    assert "locked" in snapshot["executionMode"]["liveLockedReason"].lower()


def test_dashboard_snapshot_includes_strategy_gate() -> None:
    snapshot = build_dashboard_snapshot("config/demo.yaml", symbol="EURUSD", record=False)

    assert snapshot["strategyGate"]["status"] in {"approved", "blocked"}
    assert "reason" in snapshot["strategyGate"]
