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
