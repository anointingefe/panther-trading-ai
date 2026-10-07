from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


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

    def open_from_journal(self, entry: dict[str, Any], volume: float) -> dict[str, Any]:
        if entry.get("approval_status") != "approved":
            raise ValueError("Only approved journal entries can open demo positions")

        positions = self._read_all()
        existing = self._find_by_journal_id(positions, str(entry["id"]))
        if existing:
            return existing

        position = PaperPosition(
            id=f"pos-{uuid4().hex[:12]}",
            journal_entry_id=str(entry["id"]),
            symbol=str(entry["symbol"]),
            side=str(entry["side"]),
            volume=float(volume),
            entry=float(entry["entry"]),
            stop_loss=float(entry["stop_loss"]),
            take_profit=float(entry["take_profit"]),
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
