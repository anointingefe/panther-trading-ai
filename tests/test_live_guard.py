from panther_trading.config import ExecutionConfig
from panther_trading.live_guard import LiveTradingGate


def _mt5_demo_status() -> dict:
    return {
        "name": "MetaTrader 5",
        "connected": True,
        "mode": "demo",
    }


def test_live_guard_stays_locked_when_config_disables_live() -> None:
    guard = LiveTradingGate(ExecutionConfig(allow_live_trading=False, default_volume=0.1))

    readiness = guard.readiness(
        broker_status=_mt5_demo_status(),
        approval_status="approved",
        requested_volume=0.1,
        unlock_phrase="PANTHER_LIVE_APPROVED",
        edge_validation_status="passed",
    )

    assert not readiness.enabled
    assert not readiness.armed
    assert "allow_live_trading=false" in readiness.reasons[0]


def test_live_guard_requires_mt5_broker() -> None:
    guard = LiveTradingGate(ExecutionConfig(allow_live_trading=True, default_volume=0.1))

    readiness = guard.readiness(
        broker_status={"name": "PANTHER Simulated Broker", "connected": True, "mode": "paper"},
        approval_status="approved",
        requested_volume=0.1,
        unlock_phrase="PANTHER_LIVE_APPROVED",
        edge_validation_status="passed",
    )

    assert not readiness.armed
    assert any("MetaTrader 5" in reason for reason in readiness.reasons)


def test_live_guard_can_arm_when_all_conditions_pass() -> None:
    guard = LiveTradingGate(ExecutionConfig(allow_live_trading=True, default_volume=0.1))

    readiness = guard.readiness(
        broker_status=_mt5_demo_status(),
        approval_status="approved",
        requested_volume=0.1,
        unlock_phrase="PANTHER_LIVE_APPROVED",
        edge_validation_status="passed",
    )

    assert readiness.enabled
    assert readiness.armed
    assert readiness.reasons == ()


def test_live_guard_blocks_oversized_live_volume() -> None:
    guard = LiveTradingGate(
        ExecutionConfig(
            allow_live_trading=True,
            default_volume=0.1,
            max_live_volume=0.05,
        )
    )

    readiness = guard.readiness(
        broker_status=_mt5_demo_status(),
        approval_status="approved",
        requested_volume=0.1,
        unlock_phrase="PANTHER_LIVE_APPROVED",
        edge_validation_status="passed",
    )

    assert not readiness.armed
    assert any("max_live_volume" in reason for reason in readiness.reasons)


def test_live_guard_requires_demo_edge_validation() -> None:
    guard = LiveTradingGate(ExecutionConfig(allow_live_trading=True, default_volume=0.1))

    readiness = guard.readiness(
        broker_status=_mt5_demo_status(),
        approval_status="approved",
        requested_volume=0.1,
        unlock_phrase="PANTHER_LIVE_APPROVED",
        edge_validation_status="failed",
    )

    assert not readiness.armed
    assert any("edge validation" in reason for reason in readiness.reasons)
