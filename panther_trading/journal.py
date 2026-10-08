from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class JournalEntry:
    id: str
    symbol: str
    side: str
    confidence: float
    entry: float
    stop_loss: float
    take_profit: float
    order_status: str
    order_message: str
    approval_status: str
    rationale: list[str]
    created_at: str
    decided_at: str | None = None
    decision_note: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TradeJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_signal(self, snapshot: dict[str, Any]) -> JournalEntry:
        signal = snapshot["signal"]
        order = snapshot["order"]
        approval_status = "blocked_by_risk" if order["status"] == "rejected" else "pending_approval"
        entry = JournalEntry(
            id=f"sig-{uuid4().hex[:12]}",
            symbol=snapshot["symbol"],
            side=signal["side"],
            confidence=float(signal["confidence"]),
            entry=float(signal["entry"]),
            stop_loss=float(signal["stop_loss"]),
            take_profit=float(signal["take_profit"]),
            order_status=order["status"],
            order_message=order["message"],
            approval_status=approval_status,
            rationale=list(signal["rationale"]),
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "mode": snapshot.get("mode"),
                "executionMode": snapshot.get("executionMode"),
                "broker": snapshot.get("broker"),
                "strategyGate": snapshot.get("strategyGate"),
                "researchSummary": (snapshot.get("research") or {}).get("summary"),
                "marketStructure": {
                    "source": (snapshot.get("marketStructure") or {}).get("source"),
                    "timeframe": (snapshot.get("marketStructure") or {}).get("timeframe"),
                },
            },
        )
        self._append(entry)
        return entry

    def latest(self, limit: int = 25) -> list[dict[str, Any]]:
        entries = self._read_all()
        return entries[-limit:][::-1]

    def decide(self, entry_id: str, decision: str, note: str | None = None) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Decision must be approved or rejected")

        entries = self._read_all()
        updated: dict[str, Any] | None = None
        for entry in entries:
            if entry["id"] == entry_id:
                if entry["approval_status"] == "blocked_by_risk" and decision == "approved":
                    raise ValueError("Risk-blocked signals cannot be approved")
                entry["approval_status"] = decision
                entry["decided_at"] = datetime.now(timezone.utc).isoformat()
                entry["decision_note"] = note
                updated = entry
                break

        if updated is None:
            raise ValueError(f"Journal entry not found: {entry_id}")

        self._write_all(entries)
        return updated

    def _append(self, entry: JournalEntry) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.__dict__, separators=(",", ":")) + "\n")

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def _write_all(self, entries: list[dict[str, Any]]) -> None:
        body = "".join(json.dumps(entry, separators=(",", ":")) + "\n" for entry in entries)
        self.path.write_text(body, encoding="utf-8")
