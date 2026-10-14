from panther_trading.config import ExecutionConfig
from panther_trading.live_guard import LiveTradingGate


def test_live_gate_blocks_when_execution_green_flag_has_not_passed() -> None:
    config = ExecutionConfig(
        allow_live_trading=True,
        default_volume=0.01,
        require_manual_approval=True,
        max_live_volume=0.02,
        allowed_live_account_modes=("real",),
    )
    readiness = LiveTradingGate(config).readiness(
        broker_status={"name": "MetaTrader 5", "connected": True, "mode": "real"},
        approval_status="approved",
        requested_volume=0.01,
        unlock_phrase=config.live_unlock_phrase,
        edge_validation_status="passed",
        green_flag_status="passed",
        execution_green_flag_status="building_evidence",
    )

    assert not readiness.armed
    assert any("execution green flag" in reason.lower() for reason in readiness.reasons)


def test_live_gate_can_arm_when_all_three_evidence_gates_pass() -> None:
    config = ExecutionConfig(
        allow_live_trading=True,
        default_volume=0.01,
        require_manual_approval=True,
        max_live_volume=0.02,
        allowed_live_account_modes=("real",),
    )
    readiness = LiveTradingGate(config).readiness(
        broker_status={"name": "MetaTrader 5", "connected": True, "mode": "real"},
        approval_status="approved",
        requested_volume=0.01,
        unlock_phrase=config.live_unlock_phrase,
        edge_validation_status="passed",
        green_flag_status="passed",
        execution_green_flag_status="passed",
    )

    assert readiness.armed
