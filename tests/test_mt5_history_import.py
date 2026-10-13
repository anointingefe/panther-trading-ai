from types import SimpleNamespace

from panther_trading.brokers.mt5 import MT5Broker, PANTHER_MAGIC
from panther_trading.models import SignalSide


class FakeMT5:
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1


def test_mt5_closed_trade_requires_panther_magic_and_stop_loss() -> None:
    broker = object.__new__(MT5Broker)
    broker.mt5 = FakeMT5()
    entry = SimpleNamespace(
        time=1,
        entry=FakeMT5.DEAL_ENTRY_IN,
        type=FakeMT5.DEAL_TYPE_BUY,
        order=1001,
        position_id=7001,
        magic=PANTHER_MAGIC,
        symbol="EURUSD",
        price=1.1,
        volume=0.1,
        profit=0,
        swap=0,
        commission=0,
        fee=0,
        comment="PANTHER paper trade",
    )
    exit_deal = SimpleNamespace(
        time=2,
        entry=FakeMT5.DEAL_ENTRY_OUT,
        type=FakeMT5.DEAL_TYPE_SELL,
        order=1002,
        position_id=7001,
        magic=PANTHER_MAGIC,
        symbol="EURUSD",
        price=1.115,
        volume=0.1,
        profit=15,
        swap=-1,
        commission=-0.5,
        fee=0,
        comment="PANTHER close",
    )
    orders = {
        "1001": SimpleNamespace(ticket=1001, sl=1.09, tp=1.12),
        "1002": SimpleNamespace(ticket=1002, sl=0, tp=0),
    }

    trade = broker._closed_trade_from_deals("7001", [exit_deal, entry], orders)

    assert trade is not None
    assert trade.external_id == "7001"
    assert trade.side == SignalSide.BUY
    assert trade.stop_loss == 1.09
    assert trade.take_profit == 1.12
    assert trade.pnl == 13.5


def test_mt5_closed_trade_skips_missing_stop_loss() -> None:
    broker = object.__new__(MT5Broker)
    broker.mt5 = FakeMT5()
    entry = SimpleNamespace(
        time=1,
        entry=FakeMT5.DEAL_ENTRY_IN,
        type=FakeMT5.DEAL_TYPE_BUY,
        order=1001,
        position_id=7001,
        symbol="EURUSD",
        price=1.1,
        volume=0.1,
        comment="PANTHER paper trade",
    )
    exit_deal = SimpleNamespace(
        time=2,
        entry=FakeMT5.DEAL_ENTRY_OUT,
        type=FakeMT5.DEAL_TYPE_SELL,
        order=1002,
        position_id=7001,
        symbol="EURUSD",
        price=1.115,
        volume=0.1,
        comment="PANTHER close",
    )

    trade = broker._closed_trade_from_deals(
        "7001",
        [entry, exit_deal],
        {"1001": SimpleNamespace(ticket=1001, sl=0, tp=1.12)},
    )

    assert trade is None



def history_fixture():
    broker = object.__new__(MT5Broker)
    broker.mt5 = FakeMT5()
    def deal(entry, volume, price, time, order):
        return SimpleNamespace(
            entry=entry, volume=volume, price=price, time=time, order=order,
            type=0 if entry == 0 else 1, symbol="EURUSD", profit=0,
            commission=0, swap=0, fee=0, comment="PANTHER",
        )
    orders = {"10": SimpleNamespace(sl=1.09, tp=1.14)}
    return broker, deal, orders


def test_partial_exit_is_not_a_closed_trade():
    broker, deal, orders = history_fixture()
    assert broker._closed_trade_from_deals("1", [
        deal(0, 0.1, 1.1, 1, 10), deal(1, 0.04, 1.12, 2, 11),
    ], orders) is None


def test_completed_partial_exits_use_total_volume_and_weighted_price():
    broker, deal, orders = history_fixture()
    trade = broker._closed_trade_from_deals("1", [
        deal(1, 0.06, 1.13, 3, 12), deal(0, 0.1, 1.1, 1, 10),
        deal(1, 0.04, 1.12, 2, 11),
    ], orders)
    assert trade is not None
    assert trade.volume == 0.1
    assert abs(trade.close_price - 1.126) < 1e-10
    assert trade.broker_order_id == "12"


def test_reversal_and_scale_in_are_not_misreported_as_simple_trades():
    broker, deal, orders = history_fixture()
    assert broker._closed_trade_from_deals("1", [
        deal(0, 0.1, 1.1, 1, 10), deal(2, 0.2, 1.12, 2, 11),
    ], orders) is None
    assert broker._closed_trade_from_deals("1", [
        deal(0, 0.05, 1.1, 1, 10), deal(0, 0.05, 1.11, 2, 12),
        deal(1, 0.1, 1.12, 3, 11),
    ], orders) is None


def test_nonfinite_history_is_excluded():
    broker, deal, orders = history_fixture()
    for value in [float("nan"), float("inf"), -0.1, 0.0]:
        assert broker._closed_trade_from_deals("1", [
            deal(0, 0.1, 1.1, 1, 10), deal(1, value, 1.12, 2, 11),
        ], orders) is None


def test_missing_account_mode_constants_do_not_imply_demo():
    broker, _, _ = history_fixture()
    assert broker._account_mode(None) == "unknown"


def test_history_order_query_failure_is_visible():
    import pytest
    broker, _, _ = history_fixture()
    broker.mt5.history_deals_get = lambda *args: ()
    broker.mt5.history_orders_get = lambda *args: None
    broker.mt5.last_error = lambda: (1, "offline")
    with pytest.raises(RuntimeError, match="history_orders_get"):
        broker.get_closed_trades()
