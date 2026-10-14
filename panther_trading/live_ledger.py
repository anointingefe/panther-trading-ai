from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from panther_trading.models import OrderResult, SignalSide, TradeSignal


class LivePositionLedger:
    """Persistent record of every broker-accepted Panther live order.

    The ledger is intentionally separate from paper/demo evidence so a real
    position can never leak into the demo validation sample.
    """

    ACTIVE_STATUSES = {"accepted", "reconciled"}

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._load())

    def active(self) -> list[dict[str, Any]]:
        return [record for record in self.records() if record.get("status") in self.ACTIVE_STATUSES]

    def record_accepted(
        self,
        signal: TradeSignal,
        volume: float,
        result: OrderResult,
        comment: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = {
            "id": f"live-{uuid4().hex[:12]}",
            "broker_order_id": result.broker_order_id,
            "broker_position_id": None,
            "symbol": signal.symbol,
            "side": signal.side.value,
            "volume": float(volume),
            "entry": float(signal.entry),
            "stop_loss": float(signal.stop_loss),
            "take_profit": float(signal.take_profit),
            "status": "accepted",
            "comment": comment,
            "opened_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "closed_at": None,
        }
        with self._lock:
            records = self._load()
            records.append(record)
            self._write(records)
        return record

    def has_recent_duplicate(self, signal: TradeSignal, minutes: int = 15) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(minutes, 1))
        for record in self.active():
            if record.get("symbol") != signal.symbol or record.get("side") != signal.side.value:
                continue
            opened_at = self._parse_time(record.get("opened_at"))
            if opened_at is None or opened_at < cutoff:
                continue
            if self._same_price(record.get("stop_loss"), signal.stop_loss) and self._same_price(
                record.get("take_profit"), signal.take_profit
            ):
                return True
        return False

    def apply_reconciliation(self, report: dict[str, Any]) -> None:
        matches = {item["local_id"]: item for item in report.get("matched_open", [])}
        closed = {item["local_id"]: item for item in report.get("matched_closed", [])}
        if not matches and not closed:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            records = self._load()
            for record in records:
                local_id = record.get("id")
                if local_id in matches:
                    record["status"] = "reconciled"
                    record["broker_position_id"] = matches[local_id].get("broker_position_id")
                    record["updated_at"] = now
                elif local_id in closed:
                    record["status"] = "closed"
                    record["broker_position_id"] = closed[local_id].get("broker_position_id")
                    record["closed_at"] = closed[local_id].get("closed_at") or now
                    record["updated_at"] = now
            self._write(records)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return payload if isinstance(payload, list) else []

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(records[-2000:], indent=2), encoding="utf-8")

    def _parse_time(self, value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _same_price(self, left: Any, right: float) -> bool:
        try:
            return abs(float(left) - float(right)) <= max(abs(float(right)) * 1e-8, 1e-8)
        except (TypeError, ValueError):
            return False
