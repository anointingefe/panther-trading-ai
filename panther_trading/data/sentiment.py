from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from panther_trading.models import SentimentSnapshot


class SentimentCollector(ABC):
    @abstractmethod
    def collect(self, symbol: str) -> SentimentSnapshot:
        raise NotImplementedError


class StaticSentimentCollector(SentimentCollector):
    """Neutral missing-data placeholder, never evidence of market sentiment."""

    def collect(self, symbol: str) -> SentimentSnapshot:
        return SentimentSnapshot(
            symbol=symbol,
            score=0.0,
            confidence=0.0,
            sources=("sentiment-unavailable",),
            collected_at=datetime.now(timezone.utc),
        )
