from __future__ import annotations

from datetime import datetime, timedelta, timezone

from panther_trading.config import DemoAutoConfig
from panther_trading.exits import ExitManager
from panther_trading.models import Candle


def _candle(close: float, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(
        time=datetime.now(timezone.utc),
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=100,
    )


def _position(side: str = "buy") -> dict:
    return {
        "id": "pos-1",
        "symbol": "EURUSD",
        "side": side,
        "entry": 1.1000,
        "stop_loss": 1.0950 if side == "buy" else 1.1050,
        "take_profit": 1.1100 if side == "buy" else 1.0900,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }


def test_exit_manager_closes_when_stop_is_touched() -> None:
    decision = ExitManager(DemoAutoConfig()).evaluate_position(
        _position("buy"),
        [_candle(1.0960), _candle(1.0948, high=1.0980, low=1.0948)],
    )

    assert decision.action == "close"
    assert decision.close_price == 1.0950
    assert "Stop-loss" in decision.reason


def test_exit_manager_moves_to_breakeven_after_one_r() -> None:
    decision = ExitManager(DemoAutoConfig()).evaluate_position(
        _position("buy"),
        [_candle(1.1010), _candle(1.1052, high=1.1054, low=1.1020)],
    )

    assert decision.action == "move_to_breakeven"
    assert decision.suggested_stop_loss == 1.1000


def test_exit_manager_closes_stale_trade() -> None:
    position = _position("sell")
    position["opened_at"] = (datetime.now(timezone.utc) - timedelta(minutes=300)).isoformat()
    decision = ExitManager(DemoAutoConfig(exit_max_trade_minutes=240)).evaluate_position(
        position,
        [_candle(1.0980), _candle(1.0970)],
    )

    assert decision.action == "close"
    assert "Max trade time" in decision.reason
