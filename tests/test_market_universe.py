from panther_trading.api.snapshot import build_dashboard_snapshot
from panther_trading.brokers.simulated import SimulatedBroker
from panther_trading.data.markets import market_universe


def test_market_universe_includes_common_mt5_groups() -> None:
    groups = {item["group"] for item in market_universe()}

    assert "Forex Majors" in groups
    assert "Metals" in groups
    assert "Indices" in groups
    assert "Crypto" in groups


def test_snapshot_accepts_selected_symbol() -> None:
    snapshot = build_dashboard_snapshot("config/demo.yaml", symbol="xauusd")

    assert snapshot["symbol"] == "XAUUSD"
    assert snapshot["signal"]["symbol"] == "XAUUSD"
    assert snapshot["marketStructure"]["symbol"] == "XAUUSD"
    assert snapshot["marketStructure"]["closes"]


def test_snapshot_watchlist_includes_gold_research_market() -> None:
    snapshot = build_dashboard_snapshot("config/demo.yaml", symbol="eurusd")

    assert any(item["symbol"] == "XAUUSD" for item in snapshot["watchlist"])


def test_simulated_broker_uses_asset_specific_price_ranges() -> None:
    broker = SimulatedBroker()
    gold = broker.get_candles("XAUUSD", "M15", 5)[-1].close
    bitcoin = broker.get_candles("BTCUSD", "M15", 5)[-1].close

    assert gold > 1000
    assert bitcoin > 10000
