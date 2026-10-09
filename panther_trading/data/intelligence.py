from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from panther_trading.models import SentimentSnapshot


@dataclass(frozen=True)
class MarketIntelligenceItem:
    title: str
    source: str
    url: str
    polarity: float
    weight: float
    symbols: tuple[str, ...]
    fetched_at: datetime

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fetched_at"] = self.fetched_at.isoformat()
        return payload


class MarketIntelligenceCollector:
    """Collects public market context and turns it into cautious symbol evidence."""

    DEFAULT_FEEDS: tuple[tuple[str, str], ...] = (
        ("Reuters Markets", "https://www.reutersagency.com/feed/?best-topics=markets"),
        ("Investing Economic", "https://www.investing.com/rss/news_25.rss"),
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    )
    KEYWORDS: dict[str, tuple[str, ...]] = {
        "XAUUSD": ("gold", "xau", "bullion", "fed", "inflation", "dollar", "yields"),
        "XAGUSD": ("silver", "xag", "metals", "dollar", "inflation"),
        "BTCUSD": ("bitcoin", "btc", "crypto", "etf", "risk assets"),
        "ETHUSD": ("ethereum", "ether", "eth", "crypto"),
        "USOIL": ("oil", "crude", "opec", "inventory", "brent", "wti"),
        "UKOIL": ("oil", "brent", "opec", "inventory", "crude"),
        "NAS100": ("nasdaq", "technology", "ai stocks", "rates", "earnings"),
        "US500": ("s&p", "stocks", "wall street", "rates", "earnings"),
        "US30": ("dow", "stocks", "wall street", "industrials"),
        "EURUSD": ("euro", "ecb", "dollar", "fed", "eurozone"),
        "GBPUSD": ("sterling", "pound", "boe", "dollar", "uk"),
        "USDJPY": ("yen", "boj", "japan", "dollar", "yields"),
    }
    POSITIVE_WORDS = {
        "gain", "gains", "rally", "rises", "rise", "surge", "bullish", "strong",
        "beats", "growth", "eases", "optimism", "higher", "rebound",
    }
    NEGATIVE_WORDS = {
        "fall", "falls", "drop", "drops", "slump", "bearish", "weak", "miss",
        "recession", "risk", "war", "tariff", "higher yields", "inflation fears",
        "selloff", "lower",
    }

    def __init__(self, feeds: tuple[tuple[str, str], ...] | None = None, timeout: float = 1.2) -> None:
        self.feeds = self.DEFAULT_FEEDS if feeds is None else feeds
        self.timeout = timeout

    def collect(self, symbol: str, limit: int = 8) -> dict[str, Any]:
        symbol = symbol.upper()
        fetched_at = datetime.now(timezone.utc)
        items: list[MarketIntelligenceItem] = []
        errors: list[str] = []
        for source, url in self.feeds:
            try:
                items.extend(self._fetch_feed(source, url, symbol, fetched_at))
            except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as exc:
                errors.append(f"{source}: {exc}")
        if not items:
            items = self._fallback_items(symbol, fetched_at)
        ranked = sorted(items, key=lambda item: (item.weight, abs(item.polarity)), reverse=True)[:limit]
        score = self._score(ranked)
        confidence = min(0.85, 0.3 + len(ranked) * 0.055)
        return {
            "symbol": symbol,
            "score": score,
            "confidence": round(confidence, 4),
            "sources": sorted({item.source for item in ranked}),
            "items": [item.to_dict() for item in ranked],
            "errors": errors[:3],
            "collected_at": fetched_at.isoformat(),
            "policy": (
                "Uses public RSS/web sources when available. X content should be connected through an official API "
                "or user-provided links; private or logged-in feeds are not silently scraped."
            ),
        }

    def sentiment(self, symbol: str) -> SentimentSnapshot:
        report = self.collect(symbol)
        return SentimentSnapshot(
            symbol=symbol.upper(),
            score=float(report["score"]),
            confidence=float(report["confidence"]),
            sources=tuple(report["sources"] or ["market-intelligence-fallback"]),
            collected_at=datetime.now(timezone.utc),
        )

    def _fetch_feed(
        self,
        source: str,
        url: str,
        symbol: str,
        fetched_at: datetime,
    ) -> list[MarketIntelligenceItem]:
        request = urllib.request.Request(url, headers={"User-Agent": "PANTHER-Trading-AI/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read(700_000)
        root = ET.fromstring(body)
        found: list[MarketIntelligenceItem] = []
        for node in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = self._node_text(node, "title")
            link = self._node_text(node, "link") or url
            text = f"{title} {self._node_text(node, 'description')} {self._node_text(node, 'summary')}"
            symbols = self._matched_symbols(text)
            if symbol not in symbols and not self._matches_symbol(symbol, text):
                continue
            polarity = self._polarity(text)
            weight = 1.0 + min(len(symbols), 4) * 0.1
            found.append(MarketIntelligenceItem(title or "Untitled market update", source, link, polarity, weight, symbols, fetched_at))
        return found

    def _node_text(self, node: ET.Element, name: str) -> str:
        direct = node.find(name)
        namespaced = node.find(f"{{http://www.w3.org/2005/Atom}}{name}")
        value = direct.text if direct is not None else namespaced.text if namespaced is not None else ""
        if name == "link" and namespaced is not None and not value:
            value = str(namespaced.attrib.get("href", ""))
        return re.sub(r"<[^>]+>", " ", value or "").strip()

    def _matched_symbols(self, text: str) -> tuple[str, ...]:
        return tuple(symbol for symbol in self.KEYWORDS if self._matches_symbol(symbol, text))

    def _matches_symbol(self, symbol: str, text: str) -> bool:
        lower = text.lower()
        return any(keyword in lower for keyword in self.KEYWORDS.get(symbol, (symbol.lower(),)))

    def _polarity(self, text: str) -> float:
        lower = text.lower()
        positive = sum(1 for word in self.POSITIVE_WORDS if word in lower)
        negative = sum(1 for word in self.NEGATIVE_WORDS if word in lower)
        total = positive + negative
        if total == 0:
            return 0.0
        return round((positive - negative) / total, 4)

    def _score(self, items: list[MarketIntelligenceItem]) -> float:
        if not items:
            return 0.0
        weighted = sum(item.polarity * item.weight for item in items)
        total = sum(item.weight for item in items)
        return round(max(min(weighted / total, 1.0), -1.0), 4)

    def _fallback_items(self, symbol: str, fetched_at: datetime) -> list[MarketIntelligenceItem]:
        return [
            MarketIntelligenceItem(
                title=f"No fresh public feed items matched {symbol}; trade only from price action and demo proof.",
                source="market-intelligence-fallback",
                url="",
                polarity=0.0,
                weight=0.25,
                symbols=(symbol,),
                fetched_at=fetched_at,
            )
        ]
