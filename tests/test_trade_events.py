from types import SimpleNamespace as NS
from datetime import datetime, timezone

import pytest

from panther_trading.brokers.mt5 import PANTHER_MAGIC
from panther_trading.trade_events import collect_trade_events, position_events


MT5 = NS(DEAL_ENTRY_IN=0, DEAL_ENTRY_OUT=1, DEAL_ENTRY_INOUT=2,
         DEAL_ENTRY_OUT_BY=3, DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1)


def deal(ticket, entry, volume=1, profit=0, commission=0, magic=PANTHER_MAGIC, **kwargs):
    return NS(ticket=ticket, entry=entry, volume=volume, profit=profit, commission=commission,
              swap=0, fee=0, magic=magic, time=1700000000 + ticket, time_msc=(1700000000 + ticket)*1000,
              type=0 if entry == 0 else 1, price=1.1, symbol="EURUSD", position_id=42, **kwargs)


def test_partial_and_manual_exit_with_entry_and_exit_costs():
    events = position_events([deal(1, 0, commission=-2), deal(2, 1, .4, profit=4, commission=-1),
                              deal(3, 1, .6, profit=2, commission=-1, magic=0)], MT5)
    assert [event["kind"] for event in events] == ["opened", "partial_close", "closed"]
    assert events[1]["outcome"] is None
    assert events[-1]["pnl"] == 2
    assert events[-1]["outcome"] == "win"


def test_costs_can_turn_gross_win_into_net_loss():
    events = position_events([deal(1, 0, commission=-2), deal(2, 1, profit=1)], MT5)
    assert events[-1]["outcome"] == "loss"
    assert events[-1]["pnl"] == -1


def test_open_and_close_between_polls_are_both_reported():
    events = position_events([deal(2, 1), deal(1, 0)], MT5)
    assert [e["id"] for e in events] == ["deal:1", "deal:2"]
    assert events[-1]["outcome"] == "breakeven"


def test_other_trader_positions_are_excluded():
    assert position_events([deal(1, 0, magic=123), deal(2, 1)], MT5) == []


def test_mixed_ownership_and_reversals_do_not_claim_results():
    mixed = position_events([deal(1, 0), deal(2, 0, magic=0), deal(3, 1, volume=2, profit=20)], MT5)
    assert mixed[-1]["pnl"] is None
    reversed_events = position_events([deal(1, 0), deal(2, 2), deal(3, 1)], MT5)
    assert reversed_events[-1]["outcome"] is None


def test_nonfinite_costs_fail_without_inventing_result():
    with pytest.raises(RuntimeError):
        position_events([deal(1, 0), deal(2, 1, profit=float("nan"))], MT5)


def broker_stub(history, *, fail_history=False, switched=False):
    account = NS(server="test-server", login=42, trade_mode=0, currency="GBP")
    calls = []
    def account_info():
        calls.append(1)
        return NS(server="other", login=43, trade_mode=0, currency="GBP") if switched and len(calls) > 1 else account
    def get_deals(*args, **kwargs):
        return None if fail_history else history
    mt5 = NS(**vars(MT5), account_info=account_info, terminal_info=lambda: NS(connected=True), history_deals_get=get_deals)
    return NS(mt5=mt5, _account_mode=lambda mode: "demo")


def test_account_switch_aborts_response():
    with pytest.raises(RuntimeError, match="account changed"):
        collect_trade_events(broker_stub([], switched=True), None)


def test_history_error_is_not_empty_success():
    with pytest.raises(RuntimeError, match="unavailable"):
        collect_trade_events(broker_stub([], fail_history=True), None)


def test_scope_and_timestamp_are_present_on_empty_success():
    result = collect_trade_events(broker_stub([]), None)
    assert result["mode"] == "demo"
    assert result["currency"] == "GBP"
    assert len(result["scope"]) == 24
    assert result["events"] == []
    assert abs(result["asOf"] - datetime.now(timezone.utc).timestamp()) < 2


def test_invalid_cursor_rejected():
    with pytest.raises(ValueError):
        collect_trade_events(broker_stub([]), None, float("nan"))
