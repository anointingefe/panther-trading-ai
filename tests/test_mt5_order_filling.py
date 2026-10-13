from types import SimpleNamespace

from panther_trading.brokers.mt5 import MT5Broker
from panther_trading.models import OrderRequest, OrderStatus, SignalSide


class FillingModeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_INVALID_FILL = 10030

    def __init__(self) -> None:
        self.sent_modes: list[int] = []

    def symbol_info_tick(self, symbol: str):
        return SimpleNamespace(ask=100.5, bid=100.0)

    def symbol_info(self, symbol: str):
        return SimpleNamespace(volume_min=0.01, volume_max=100.0, volume_step=0.01)

    def order_send(self, payload):
        self.sent_modes.append(payload["type_filling"])
        if payload["type_filling"] != self.ORDER_FILLING_RETURN:
            return SimpleNamespace(retcode=self.TRADE_RETCODE_INVALID_FILL, comment="Unsupported filling mode", order=0)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, comment="done", order=12345)


def test_mt5_order_send_retries_supported_filling_mode() -> None:
    broker = object.__new__(MT5Broker)
    fake = FillingModeMT5()
    broker.mt5 = fake

    result = broker.place_order(
        OrderRequest(
            symbol="MSFT",
            side=SignalSide.BUY,
            volume=0.01,
            entry=100.5,
            stop_loss=99.5,
            take_profit=102.5,
            comment="PANTHER demo incubation",
        )
    )

    assert result.status == OrderStatus.ACCEPTED
    assert fake.sent_modes == [
        FillingModeMT5.ORDER_FILLING_FOK,
        FillingModeMT5.ORDER_FILLING_IOC,
        FillingModeMT5.ORDER_FILLING_RETURN,
    ]


class StockVolumeMT5(FillingModeMT5):
    def __init__(self) -> None:
        super().__init__()
        self.sent_payloads = []

    def symbol_info(self, symbol: str):
        return SimpleNamespace(volume_min=1.0, volume_max=100.0, volume_step=1.0)

    def order_send(self, payload):
        self.sent_payloads.append(payload)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, comment="done", order=9876)


def test_mt5_order_send_refuses_volume_below_symbol_minimum() -> None:
    broker = object.__new__(MT5Broker)
    fake = StockVolumeMT5()
    broker.mt5 = fake

    result = broker.place_order(
        OrderRequest(
            symbol="MSFT",
            side=SignalSide.BUY,
            volume=0.01,
            entry=100.5,
            stop_loss=99.5,
            take_profit=102.5,
            comment="PANTHER demo incubation",
        )
    )

    assert result.status == OrderStatus.REJECTED
    assert fake.sent_payloads == []
    assert "below broker minimum" in result.message


class RiskVolumeMT5(FillingModeMT5):
    def symbol_info(self, symbol: str):
        return SimpleNamespace(
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_tick_size=0.01,
            trade_tick_value=1.0,
            point=0.01,
        )

    def order_calc_profit(self, order_type, symbol, volume, entry, stop_loss):
        return -200.0


def test_mt5_calculates_position_volume_from_risk_amount() -> None:
    broker = object.__new__(MT5Broker)
    broker.mt5 = RiskVolumeMT5()

    volume = broker.calculate_position_volume(
        symbol="XAUUSD",
        side=SignalSide.BUY,
        entry=2400.0,
        stop_loss=2398.0,
        risk_amount=50.0,
        max_volume=1.0,
    )

    assert volume == 0.25
