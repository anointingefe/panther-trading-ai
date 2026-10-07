from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from panther_trading.models import SentimentSnapshot


class SentimentCollector(ABC):
    @abstractmethod
    def collect(self, symbol: str) -> SentimentSnapshot:
        raise NotImplementedError


class StaticSentimentCollector(SentimentCollector):
    """Placeholder collector until paid APIs are wired in."""

    def collect(self, symbol: str) -> SentimentSnapshot:
        return SentimentSnapshot(
            symbol=symbol,
            score=0.12,
            confidence=0.55,
            sources=("static-dev-sentiment",),
            collected_at=datetime.now(timezone.utc),
        )
