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
