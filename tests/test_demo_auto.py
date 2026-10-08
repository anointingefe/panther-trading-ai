from dataclasses import replace

from panther_trading.brokers.simulated import SimulatedBroker
from panther_trading.demo_auto import DemoAutoTrader


class RealModeBroker(SimulatedBroker):
    def get_status(self):
        return replace(super().get_status(), mode="real")


def test_demo_auto_refuses_real_account_mode(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=RealModeBroker(),
    )

    cycle = trader.run_cycle()

    assert cycle.status == "blocked"
    assert cycle.scanned == 0
    assert cycle.placed == 0
    assert "real" in cycle.reasons[0]


def test_demo_auto_scans_demo_safe_broker_and_writes_state(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=SimulatedBroker(),
    )

    cycle = trader.run_cycle()
    state = trader.latest_state()

    assert cycle.broker_mode == "paper"
    assert cycle.scanned > 0
    assert state["lastCycle"]["scanned"] == cycle.scanned
    assert state["message"]


class BrokerWithExtraSymbols(SimulatedBroker):
    def list_symbols(self):
        return ["EURUSD", "BROKERX", "SYNTHETIC.TEST", "X" * 25, "12345"]


def test_demo_auto_scans_broker_only_symbols_with_safe_filter(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=BrokerWithExtraSymbols(),
    )

    cycle = trader.run_cycle()
    scanned_symbols = {decision.symbol for decision in cycle.decisions}

    assert "EURUSD" in scanned_symbols
    assert "BROKERX" in scanned_symbols
    assert "SYNTHETIC.TEST" in scanned_symbols
    assert "X" * 25 not in scanned_symbols
    assert "12345" not in scanned_symbols


class BrokerWithBrokenSymbol(SimulatedBroker):
    def list_symbols(self):
        return ["EURUSD", "BROKEN"]

    def get_candles(self, symbol: str, timeframe: str, count: int):
        if symbol == "BROKEN":
            raise RuntimeError("no rates for symbol")
        return super().get_candles(symbol, timeframe, count)


def test_demo_auto_symbol_failure_does_not_break_cycle(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=BrokerWithBrokenSymbol(),
    )

    cycle = trader.run_cycle()
    decisions = {decision.symbol: decision for decision in cycle.decisions}

    assert cycle.scanned == 2
    assert decisions["BROKEN"].action == "blocked"
    assert "no rates for symbol" in decisions["BROKEN"].reason
