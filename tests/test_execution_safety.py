from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from panther_trading.brokers.mt5 import MT5Broker, PANTHER_MAGIC
from panther_trading.brokers.simulated import SimulatedBroker
from panther_trading.config import load_config
from panther_trading.execution import ExecutionEngine
from panther_trading.live_auto import LiveAutoTrader
from panther_trading.models import OrderRequest, OrderStatus, SignalSide, TradeSignal
from panther_trading.risk import RiskManager


class FakeMT5:
    ORDER_TYPE_BUY = POSITION_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_INVALID_FILL = 10030

    def __init__(self):
        self.info = SimpleNamespace(volume_min=0.01, volume_max=100.0, volume_step=0.01)
        self.result = SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, comment="done", order=1)
        self.profit = -200.0
        self.sent = []
        self.positions = []
        self.tick = SimpleNamespace(ask=100.5, bid=100.0)

    def symbol_info(self, symbol):
        return self.info

    def symbol_info_tick(self, symbol):
        return self.tick

    def order_calc_profit(self, *args):
        return self.profit

    def order_send(self, payload):
        self.sent.append(payload)
        return self.result

    def positions_get(self, **kwargs):
        return self.positions

    def last_error(self):
        return (1, "unavailable")


def broker():
    instance = object.__new__(MT5Broker)
    instance.mt5 = FakeMT5()
    return instance


def order(**changes):
    return replace(OrderRequest("TEST", SignalSide.BUY, 0.01, 100.5, 99.5, 102.5, "test"), **changes)


def signal(**changes):
    return replace(TradeSignal(
        "TEST", SignalSide.BUY, 0.9, 100.5, 99.5, 102.5, (), datetime.now(timezone.utc),
    ), **changes)


@pytest.mark.parametrize("requested", [0.0, -1.0, 0.001, float("nan"), float("inf")])
def test_volume_never_rounds_up_to_broker_minimum(requested):
    assert broker()._floored_volume("TEST", requested) == 0.0


@pytest.mark.parametrize("requested,expected", [(0.019, 0.01), (0.29, 0.29), (0.3, 0.3), (101.0, 100.0)])
def test_volume_floors_without_binary_rounding_loss(requested, expected):
    assert broker()._floored_volume("TEST", requested) == expected


@pytest.mark.parametrize("profit", [None, 0.0, 200.0, float("nan"), float("inf")])
def test_unknown_or_invalid_risk_never_falls_back_to_maximum_lots(profit):
    instance = broker()
    instance.mt5.profit = profit
    assert instance.calculate_position_volume("TEST", SignalSide.BUY, 100.5, 99.5, 50, 1) == 0


def test_risk_budget_below_minimum_lot_is_rejected():
    assert broker().calculate_position_volume("TEST", SignalSide.BUY, 100.5, 99.5, 1, 1) == 0


def test_missing_symbol_limits_prevent_submission():
    instance = broker()
    instance.mt5.info = None
    assert instance.place_order(order()).status == OrderStatus.REJECTED
    assert instance.mt5.sent == []


@pytest.mark.parametrize("changes", [
    {"side": SignalSide.HOLD}, {"volume": 0}, {"volume": float("nan")},
    {"stop_loss": 101}, {"take_profit": 100}, {"entry": float("inf")},
])
def test_invalid_orders_never_reach_mt5(changes):
    instance = broker()
    assert instance.place_order(order(**changes)).status == OrderStatus.REJECTED
    assert instance.mt5.sent == []


def test_moved_market_price_cannot_reverse_the_bracket():
    instance = broker()
    instance.mt5.tick = SimpleNamespace(ask=103, bid=102.8)
    assert instance.place_order(order()).status == OrderStatus.REJECTED
    assert instance.mt5.sent == []


def test_ambiguous_submission_is_not_retried_with_another_filling_mode():
    instance = broker()
    instance.mt5.result = None
    result = instance.place_order(order())
    assert result.status == OrderStatus.REJECTED
    assert "outcome unknown" in result.message
    assert len(instance.mt5.sent) == 1


def test_filling_text_does_not_override_a_different_retcode():
    instance = broker()
    instance.mt5.result = SimpleNamespace(retcode=10012, comment="timeout during filling", order=0)
    assert instance.place_order(order()).status == OrderStatus.REJECTED
    assert len(instance.mt5.sent) == 1


@pytest.mark.parametrize("code", [FakeMT5.TRADE_RETCODE_DONE_PARTIAL, FakeMT5.TRADE_RETCODE_PLACED])
def test_partial_and_placed_orders_count_as_accepted_requests(code):
    instance = broker()
    instance.mt5.result = SimpleNamespace(retcode=code, comment="pending reconciliation", order=1)
    assert instance.place_order(order()).status == OrderStatus.ACCEPTED
    assert len(instance.mt5.sent) == 1


def test_ambiguous_close_is_not_resent():
    instance = broker()
    instance.mt5.positions = [SimpleNamespace(magic=PANTHER_MAGIC, symbol="TEST", type=0, volume=0.01)]
    instance.mt5.result = None
    result = instance.close_position("1")
    assert "outcome unknown" in result.message
    assert len(instance.mt5.sent) == 1


def test_failed_position_query_is_not_reported_as_an_empty_account():
    instance = broker()
    instance.mt5.positions = None
    with pytest.raises(RuntimeError, match="positions_get"):
        instance.count_open_positions()
    with pytest.raises(RuntimeError, match="positions_get"):
        instance.open_positions()


@pytest.mark.parametrize("changes", [
    {"confidence": float("nan")}, {"confidence": float("inf")}, {"confidence": 1.1},
    {"entry": 0}, {"stop_loss": 101}, {"take_profit": 99},
    {"side": SignalSide.SELL},
])
def test_risk_manager_rejects_invalid_signal_geometry_and_numbers(changes):
    manager = RiskManager(load_config("config/demo.yaml").risk)
    assert not manager.evaluate(signal(**changes), 0).allowed


def test_execution_limit_counts_all_symbols():
    instance = SimulatedBroker()
    config = load_config("config/demo.yaml")
    for index in range(config.risk.max_open_positions):
        instance.place_order(order(symbol=f"OTHER{index}"))
    result = ExecutionEngine(instance, RiskManager(config.risk), config.execution).execute(signal())
    assert result.status == OrderStatus.REJECTED
    assert "Maximum open positions" in result.message
    assert len(instance.orders) == config.risk.max_open_positions


def test_execution_cannot_send_to_real_account_with_live_disabled():
    class RealBroker(SimulatedBroker):
        def get_status(self):
            return replace(super().get_status(), mode="real")
    instance = RealBroker()
    config = load_config("config/demo.yaml")
    result = ExecutionEngine(instance, RiskManager(config.risk), config.execution).execute(signal())
    assert result.status == OrderStatus.REJECTED
    assert instance.orders == []


def test_live_sizing_uses_broker_equity_and_never_boosts_above_risk_cap(tmp_path):
    class SizingBroker(SimulatedBroker):
        risk_amount = None

        def get_status(self):
            return replace(super().get_status(), equity=500.0)

        def calculate_position_volume(self, symbol, side, entry, stop_loss, risk_amount, max_volume):
            self.risk_amount = risk_amount
            return 0.01

    instance = SizingBroker()
    trader = LiveAutoTrader("config/demo.yaml", tmp_path / "positions.jsonl", state_path=tmp_path / "state.json", broker=instance)
    config = load_config("config/demo.yaml")
    trader._live_volume(config, instance, signal(), {"daily_progress": 0, "weekly_progress": 0, "monthly_progress": 0})
    assert instance.risk_amount == 500 * config.risk.max_risk_per_trade_pct / 100
