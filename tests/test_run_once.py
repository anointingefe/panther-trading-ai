from pathlib import Path

from panther_trading.cli import run_once_command


def test_run_once_returns_signal_and_order() -> None:
    result = run_once_command(Path("config/demo.yaml"))

    assert result["symbol"] == "EURUSD"
    assert result["signal"].symbol == "EURUSD"
    assert result["order"].status.value in {"rejected", "simulated"}
