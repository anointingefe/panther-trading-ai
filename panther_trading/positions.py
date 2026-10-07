from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from panther_trading.models import ClosedTrade


@dataclass(frozen=True)
class PaperPosition:
    id: str
    journal_entry_id: str
    symbol: str
    side: str
    volume: float
    entry: float
    stop_loss: float
    take_profit: float
    status: str
    opened_at: str
    closed_at: str | None = None
    close_reason: str | None = None
    close_price: float | None = None
    pnl: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PaperPositionBook:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def open_from_journal(
        self,
        entry: dict[str, Any],
        volume: float,
        max_open_positions: int | None = None,
        max_positions_per_symbol: int | None = None,
    ) -> dict[str, Any]:
        if entry.get("approval_status") != "approved":
            raise ValueError("Only approved journal entries can open demo positions")
        if volume <= 0:
            raise ValueError("Demo position volume must be greater than zero")

        side = str(entry["side"])
        entry_price = float(entry["entry"])
        stop_loss = float(entry["stop_loss"])
        take_profit = float(entry["take_profit"])
        if side == "buy" and not stop_loss < entry_price < take_profit:
            raise ValueError("Buy orders require stop-loss < entry < take-profit")
        if side == "sell" and not take_profit < entry_price < stop_loss:
            raise ValueError("Sell orders require take-profit < entry < stop-loss")

        positions = self._read_all()
        existing = self._find_by_journal_id(positions, str(entry["id"]))
        if existing:
            return existing
        open_positions = [position for position in positions if position["status"] == "open"]
        if max_open_positions is not None and len(open_positions) >= max_open_positions:
            raise ValueError("Maximum open demo positions reached")
        symbol = str(entry["symbol"])
        symbol_positions = [position for position in open_positions if position["symbol"] == symbol]
        if max_positions_per_symbol is not None and len(symbol_positions) >= max_positions_per_symbol:
            raise ValueError(f"Maximum open positions reached for {symbol}")

        position = PaperPosition(
            id=f"pos-{uuid4().hex[:12]}",
            journal_entry_id=str(entry["id"]),
            symbol=symbol,
            side=side,
            volume=float(volume),
            entry=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="open",
            opened_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "confidence": entry.get("confidence"),
                "order_status": entry.get("order_status"),
                "order_message": entry.get("order_message"),
            },
        )
        payload = position.__dict__
        positions.append(payload)
        self._write_all(positions)
        return payload

    def close(self, position_id: str, reason: str = "manual_stop", close_price: float | None = None) -> dict[str, Any]:
        positions = self._read_all()
        updated: dict[str, Any] | None = None
        for position in positions:
            if position["id"] == position_id:
                if position["status"] == "closed":
                    updated = position
                    break
                price = float(close_price if close_price is not None else position["entry"])
                position["status"] = "closed"
                position["closed_at"] = datetime.now(timezone.utc).isoformat()
                position["close_reason"] = reason
                position["close_price"] = price
                position["pnl"] = self._estimate_pnl(position, price)
                updated = position
                break

        if updated is None:
            raise ValueError(f"Position not found: {position_id}")

        self._write_all(positions)
        return updated

    def close_all(self, reason: str = "emergency_stop") -> list[dict[str, Any]]:
        closed: list[dict[str, Any]] = []
        for position in self.open_positions():
            closed.append(self.close(position["id"], reason=reason))
        return closed

    def import_closed_trade(self, trade: ClosedTrade) -> dict[str, Any]:
        if trade.volume <= 0:
            raise ValueError("Closed trade volume must be greater than zero")
        if trade.stop_loss == trade.entry:
            raise ValueError("Closed trade must include a usable stop-loss")
        side = trade.side.value
        if side == "buy" and trade.stop_loss >= trade.entry:
            raise ValueError("Imported buy trades require stop-loss below entry")
        if side == "sell" and trade.stop_loss <= trade.entry:
            raise ValueError("Imported sell trades require stop-loss above entry")

        positions = self._read_all()
        existing = self._find_by_external_id(positions, trade.source, trade.external_id)
        if existing:
            return existing

        position = PaperPosition(
            id=f"pos-{uuid4().hex[:12]}",
            journal_entry_id=f"{trade.source}:{trade.external_id}",
            symbol=trade.symbol,
            side=side,
            volume=float(trade.volume),
            entry=float(trade.entry),
            stop_loss=float(trade.stop_loss),
            take_profit=float(trade.take_profit),
            status="closed",
            opened_at=trade.opened_at.isoformat(),
            closed_at=trade.closed_at.isoformat(),
            close_reason=f"{trade.source}_history_import",
            close_price=float(trade.close_price),
            pnl=float(trade.pnl),
            metadata={
                "source": trade.source,
                "external_id": trade.external_id,
                "broker_order_id": trade.broker_order_id,
                "comment": trade.comment,
                "verified": True,
            },
        )
        payload = position.__dict__
        positions.append(payload)
        self._write_all(positions)
        return payload

    def open_positions(self) -> list[dict[str, Any]]:
        return [position for position in self.latest(limit=500) if position["status"] == "open"]

    def latest(self, limit: int = 25) -> list[dict[str, Any]]:
        positions = self._read_all()
        return positions[-limit:][::-1]

    def _find_by_journal_id(self, positions: list[dict[str, Any]], journal_entry_id: str) -> dict[str, Any] | None:
        for position in positions:
            if position["journal_entry_id"] == journal_entry_id:
                return position
        return None

    def _find_by_external_id(
        self, positions: list[dict[str, Any]], source: str, external_id: str
    ) -> dict[str, Any] | None:
        for position in positions:
            metadata = position.get("metadata") or {}
            if metadata.get("source") == source and metadata.get("external_id") == external_id:
                return position
        return None

    def _estimate_pnl(self, position: dict[str, Any], close_price: float) -> float:
        entry = float(position["entry"])
        volume = float(position["volume"])
        direction = 1 if position["side"] == "buy" else -1
        return round((close_price - entry) * direction * volume, 6)

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        positions = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                positions.append(json.loads(line))
        return positions

    def _write_all(self, positions: list[dict[str, Any]]) -> None:
        body = "".join(json.dumps(position, separators=(",", ":")) + "\n" for position in positions)
        self.path.write_text(body, encoding="utf-8")
