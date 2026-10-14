from panther_trading.config import (
    AppConfig,
    BeastModeConfig,
    DemoAutoConfig,
    ExecutionConfig,
    PantherConfig,
    RiskConfig,
    ShadowExecutionConfig,
    StrategyConfig,
    ValidationConfig,
)
from panther_trading.execution_green_flag import ExecutionGreenFlag


def _config() -> PantherConfig:
    return PantherConfig(
        app=AppConfig(mode="paper", symbol="EURUSD", timeframe="M15", candles=120),
        risk=RiskConfig(10000, 0.5, 2.0, 0.7, 2),
        strategy=StrategyConfig(10, 30, 0.25),
        execution=ExecutionConfig(False, 0.01),
        demo_auto=DemoAutoConfig(),
        validation=ValidationConfig(),
        beast_mode=BeastModeConfig(),
        shadow_execution=ShadowExecutionConfig(
            min_samples=3,
            min_reconciliation_samples=2,
            min_preflight_pass_rate=1.0,
            min_quote_fresh_rate=1.0,
        ),
    )


def _sample(**overrides: object) -> dict:
    sample = {
        "broker_native": True,
        "preflight_passed": True,
        "quote_fresh": True,
        "volume_valid": True,
        "bracket_valid": True,
    }
    sample.update(overrides)
    return sample


def test_execution_green_flag_passes_clean_shadow_evidence() -> None:
    state = {
        "samples": [_sample(), _sample(), _sample()],
        "reconciliationHistory": [{"clean": True}, {"clean": True}],
    }

    report = ExecutionGreenFlag(_config()).evaluate(state)

    assert report.passed
    assert report.status == "passed"
    assert report.score == 100.0


def test_execution_green_flag_ignores_non_native_samples_and_blocks_mismatch() -> None:
    state = {
        "samples": [
            _sample(),
            _sample(broker_native=False),
            _sample(preflight_passed=False),
        ],
        "reconciliationHistory": [{"clean": True}, {"clean": False}],
    }

    report = ExecutionGreenFlag(_config()).evaluate(state)

    assert not report.passed
    assert report.native_samples == 2
    assert report.preflight_pass_rate == 0.5
    assert report.latest_reconciliation_clean is False
    assert any("reconciliation" in reason.lower() for reason in report.reasons)
