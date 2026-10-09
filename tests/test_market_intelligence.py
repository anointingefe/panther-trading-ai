from __future__ import annotations

from datetime import datetime, timezone

from panther_trading.data.intelligence import MarketIntelligenceCollector, MarketIntelligenceItem


def test_market_intelligence_scores_weighted_items() -> None:
    collector = MarketIntelligenceCollector(feeds=())
    items = [
        MarketIntelligenceItem("Gold gains as dollar falls", "test", "", 1.0, 2.0, ("XAUUSD",), datetime.now(timezone.utc)),
        MarketIntelligenceItem("Yields rise against bullion", "test", "", -0.5, 1.0, ("XAUUSD",), datetime.now(timezone.utc)),
    ]

    assert collector._score(items) == 0.5


def test_market_intelligence_fallback_is_neutral() -> None:
    report = MarketIntelligenceCollector(feeds=()).collect("BTCUSD")

    assert report["symbol"] == "BTCUSD"
    assert report["score"] == 0
    assert report["items"][0]["source"] == "market-intelligence-fallback"
