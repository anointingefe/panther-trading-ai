from panther_trading.config import ValidationConfig
from panther_trading.validation import EdgeValidationGate


def _position(index: int, pnl: float, closed_at: str | None = None) -> dict:
    return {
        "id": f"pos-{index}",
        "status": "closed",
        "symbol": "EURUSD",
        "side": "buy",
        "volume": 1,
        "entry": 1.0,
        "stop_loss": 0.99,
        "take_profit": 1.02,
        "closed_at": closed_at or f"2026-01-{index % 28 + 1:02d}T10:00:00+00:00",
        "pnl": pnl,
    }


def test_edge_validation_blocks_insufficient_demo_history() -> None:
    report = EdgeValidationGate(ValidationConfig()).evaluate([])

    assert not report.passed
    assert report.status == "insufficient_data"
    assert any("closed demo trades" in reason for reason in report.reasons)


def test_edge_validation_passes_strong_demo_history() -> None:
    config = ValidationConfig(
        min_demo_trades=4,
        min_demo_days=2,
        min_profit_factor=1.2,
        min_net_r=2,
        min_win_rate=0.5,
        max_drawdown_r=3,
    )
    positions = [
        _position(1, 0.02),
        _position(2, 0.015),
        _position(3, -0.005),
        _position(4, 0.02),
    ]

    report = EdgeValidationGate(config).evaluate(positions)

    assert report.passed
    assert report.status == "passed"
    assert report.net_r >= 2
    assert report.profit_factor >= 1.2
