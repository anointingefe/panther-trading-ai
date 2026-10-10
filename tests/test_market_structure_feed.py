from panther_trading.api.snapshot import build_market_structure_snapshot


def test_market_structure_feed_returns_live_chart_payload() -> None:
    payload = build_market_structure_snapshot("config/demo.yaml", symbol="XAUUSD", timeframe="M5", count=80)

    assert payload["symbol"] == "XAUUSD"
    assert payload["timeframe"] == "M5"
    assert payload["latest"] > 0
    assert len(payload["candles"]) >= 20
    assert {"open", "high", "low", "close"}.issubset(payload["candles"][-1])
