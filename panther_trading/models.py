from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SignalSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SIMULATED = "simulated"


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class SentimentSnapshot:
    symbol: str
    score: float
    confidence: float
    sources: tuple[str, ...]
    collected_at: datetime


@dataclass(frozen=True)
class BrokerStatus:
    name: str
    connected: bool
    mode: str
    account_login: str | None
    account_server: str | None
    balance: float | None
    equity: float | None
    open_positions: int
    symbols_total: int
    message: str


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    side: SignalSide
    confidence: float
    entry: float
    stop_loss: float
    take_profit: float
    rationale: tuple[str, ...]
    generated_at: datetime

    @classmethod
    def hold(cls, symbol: str, entry: float, reason: str) -> "TradeSignal":
        return cls(
            symbol=symbol,
            side=SignalSide.HOLD,
            confidence=0.0,
            entry=entry,
            stop_loss=entry,
            take_profit=entry,
            rationale=(reason,),
            generated_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: SignalSide
    volume: float
    entry: float
    stop_loss: float
    take_profit: float
    comment: str


@dataclass(frozen=True)
class OrderResult:
    status: OrderStatus
    message: str
    broker_order_id: str | None = None
