from dataclasses import replace
import json
from datetime import datetime, timezone

from panther_trading.brokers.simulated import SimulatedBroker
from panther_trading.config import load_config
from panther_trading.demo_auto import DemoAutoTrader
from panther_trading.models import SignalSide, TradeSignal


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


def test_demo_auto_blocks_symbol_after_recent_loss(tmp_path) -> None:
    positions = tmp_path / "positions.jsonl"
    positions.write_text(
        json.dumps(
            {
                "status": "closed",
                "symbol": "EURUSD",
                "pnl": -1.0,
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=SimulatedBroker(),
        positions_path=positions,
    )

    cycle = trader.run_cycle()
    decisions = {decision.symbol: decision for decision in cycle.decisions}

    assert decisions["EURUSD"].action == "blocked"
    assert "cooldown" in decisions["EURUSD"].reason


class BrokerWithSuffixedGold(SimulatedBroker):
    def list_symbols(self):
        return ["XAUUSDm"]


def test_demo_auto_resolves_broker_symbol_suffixes(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=BrokerWithSuffixedGold(),
    )

    cycle = trader.run_cycle()
    scanned_symbols = {decision.symbol for decision in cycle.decisions}

    assert "XAUUSDm" in scanned_symbols


class VolatileBroker(SimulatedBroker):
    def list_symbols(self):
        return ["EURUSD"]

    def get_candles(self, symbol: str, timeframe: str, count: int):
        candles = super().get_candles(symbol, timeframe, count)
        latest = candles[-1]
        candles[-1] = replace(latest, high=latest.close + 0.2, low=latest.close - 0.2)
        return candles


def test_demo_auto_blocks_volatility_spikes(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=VolatileBroker(),
    )

    cycle = trader.run_cycle()

    assert cycle.decisions[0].action == "blocked"
    assert "Volatility spike" in cycle.decisions[0].reason


def test_demo_auto_blocks_weak_temporal_window(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=SimulatedBroker(),
    )
    config = load_config("config/demo.yaml")
    now = datetime.now(timezone.utc)
    positions = [
        {
            "status": "closed",
            "symbol": "EURUSD",
            "pnl": -1.0,
            "opened_at": now.replace(minute=0, second=0, microsecond=0).isoformat(),
        }
        for _ in range(config.demo_auto.temporal_min_samples)
    ]

    reason = trader._temporal_gate(config, "EURUSD", now, positions)

    assert reason is not None
    assert "Temporal edge blocked" in reason


def test_demo_auto_bayesian_update_reduces_confidence_after_losses(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=SimulatedBroker(),
    )
    config = load_config("config/demo.yaml")
    positions = [
        {"status": "closed", "symbol": "EURUSD", "pnl": -1.0}
        for _ in range(3)
    ]
    signal = TradeSignal(
        symbol="EURUSD",
        side=SignalSide.BUY,
        confidence=0.8,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        rationale=("test",),
        generated_at=datetime.now(timezone.utc),
    )

    edge = trader._bayesian_edge_probability(config, "EURUSD", positions)
    adjusted = trader._adjust_signal_confidence(config, signal, edge)

    assert edge < 0.6
    assert adjusted.confidence < signal.confidence


def test_demo_auto_kelly_sizing_never_exceeds_configured_demo_volume(tmp_path) -> None:
    trader = DemoAutoTrader(
        "config/demo.yaml",
        tmp_path / "demo_auto_state.json",
        broker=SimulatedBroker(),
    )
    config = load_config("config/demo.yaml")
    signal = TradeSignal(
        symbol="EURUSD",
        side=SignalSide.BUY,
        confidence=0.9,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        rationale=("test",),
        generated_at=datetime.now(timezone.utc),
    )

    volume = trader._kelly_volume(config, signal)

    assert 0 < volume <= config.demo_auto.demo_order_volume
