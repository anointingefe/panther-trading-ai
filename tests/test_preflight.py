from types import SimpleNamespace

from panther_trading.models import SignalSide
from panther_trading.preflight import execution_preflight


class FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_TRADE_MODE_DISABLED = 0
    SYMBOL_TRADE_MODE_CLOSEONLY = 4

    def __init__(self) -> None:
        self.order_send_calls = 0

    def symbol_info(self, symbol: str):
        return SimpleNamespace(point=0.0001, trade_stops_level=5, trade_mode=1)

    def symbol_info_tick(self, symbol: str):
        import time

        return SimpleNamespace(bid=1.1000, ask=1.1002, time_msc=int(time.time() * 1000))

    def order_check(self, request: dict):
        return SimpleNamespace(retcode=0, comment="Done")

    def order_send(self, request: dict):
        self.order_send_calls += 1
        raise AssertionError("Shadow preflight must never call order_send")

    def last_error(self):
        return (0, "ok")


class FakeBroker:
    def __init__(self) -> None:
        self.mt5 = FakeMT5()

    def _normalized_volume(self, symbol: str, requested: float) -> float:
        return requested


def test_mt5_preflight_checks_real_quote_without_sending_order() -> None:
    broker = FakeBroker()

    report = execution_preflight(
        broker,
        "EURUSD",
        SignalSide.BUY,
        0.01,
        1.1001,
        1.0990,
        1.1020,
    )

    assert report["broker_native"] is True
    assert report["executable"] is True
    assert report["bracket_valid"] is True
    assert report["volume_valid"] is True
    assert report["spread_points"] == 2.0
    assert broker.mt5.order_send_calls == 0
