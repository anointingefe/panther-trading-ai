from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from panther_trading.live_ledger import LivePositionLedger


@dataclass(frozen=True)
class ReconciliationReport:
    checked_at: str
    clean: bool
    broker_open_count: int
    local_active_count: int
    matched_open: tuple[dict[str, Any], ...]
    matched_closed: tuple[dict[str, Any], ...]
    orphan_broker_positions: tuple[dict[str, Any], ...]
    missing_on_broker: tuple[dict[str, Any], ...]
    duplicate_order_ids: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def mismatch_count(self) -> int:
        return (
            len(self.orphan_broker_positions)
            + len(self.missing_on_broker)
            + len(self.duplicate_order_ids)
            + len(self.errors)
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mismatch_count"] = self.mismatch_count
        return payload


class BrokerReconciler:
    """Compare Panther's live ledger against broker truth before more risk is added."""

    def reconcile(self, ledger: LivePositionLedger, broker: Any) -> ReconciliationReport:
        errors: list[str] = []
        try:
            broker_open = [
                position
                for position in broker.open_positions()
                if self._is_live_panther_position(position)
            ]
        except Exception as exc:
            broker_open = []
            errors.append(f"Open-position reconciliation failed: {exc}")

        closed_history: list[Any] = []
        if hasattr(broker, "get_closed_trades"):
            try:
                closed_history = [
                    trade
                    for trade in broker.get_closed_trades(days=30)
                    if self._is_live_closed_trade(trade)
                ]
            except Exception as exc:
                errors.append(f"Closed-history reconciliation failed: {exc}")

        local_active = ledger.active()
        duplicate_order_ids = self._duplicate_order_ids(local_active)
        unmatched_broker = list(broker_open)
        matched_open: list[dict[str, Any]] = []
        matched_closed: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []

        for local in local_active:
            open_match = self._pop_open_match(local, unmatched_broker)
            if open_match is not None:
                matched_open.append(
                    {
                        "local_id": local.get("id"),
                        "broker_order_id": local.get("broker_order_id"),
                        "broker_position_id": open_match.get("id") or open_match.get("ticket"),
                        "symbol": local.get("symbol"),
                    }
                )
                continue

            closed_match = self._closed_match(local, closed_history)
            if closed_match is not None:
                matched_closed.append(
                    {
                        "local_id": local.get("id"),
                        "broker_order_id": local.get("broker_order_id"),
                        "broker_position_id": getattr(closed_match, "external_id", None),
                        "symbol": local.get("symbol"),
                        "closed_at": self._iso(getattr(closed_match, "closed_at", None)),
                    }
                )
                continue
            missing.append(self._safe_local(local))

        orphans = [self._safe_broker(position) for position in unmatched_broker]
        clean = not (orphans or missing or duplicate_order_ids or errors)
        report = ReconciliationReport(
            checked_at=datetime.now(timezone.utc).isoformat(),
            clean=clean,
            broker_open_count=len(broker_open),
            local_active_count=len(local_active),
            matched_open=tuple(matched_open),
            matched_closed=tuple(matched_closed),
            orphan_broker_positions=tuple(orphans),
            missing_on_broker=tuple(missing),
            duplicate_order_ids=tuple(duplicate_order_ids),
            errors=tuple(errors),
        )
        ledger.apply_reconciliation(report.to_dict())
        return report

    def _is_live_panther_position(self, position: dict[str, Any]) -> bool:
        metadata = position.get("metadata") or {}
        comment = str(metadata.get("comment") or position.get("comment") or "").lower()
        return "panther live" in comment

    def _is_live_closed_trade(self, trade: Any) -> bool:
        return "panther live" in str(getattr(trade, "comment", "") or "").lower()

    def _duplicate_order_ids(self, records: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for record in records:
            order_id = str(record.get("broker_order_id") or "").strip()
            if not order_id:
                continue
            if order_id in seen:
                duplicates.add(order_id)
            seen.add(order_id)
        return sorted(duplicates)

    def _pop_open_match(self, local: dict[str, Any], broker_positions: list[dict[str, Any]]) -> dict[str, Any] | None:
        order_id = str(local.get("broker_order_id") or "")
        if order_id:
            for index, broker_position in enumerate(broker_positions):
                identifiers = {
                    str(broker_position.get("id") or ""),
                    str(broker_position.get("ticket") or ""),
                    str(broker_position.get("broker_order_id") or ""),
                    str((broker_position.get("metadata") or {}).get("broker_order_id") or ""),
                }
                if order_id in identifiers:
                    return broker_positions.pop(index)

        candidates = [
            (index, broker_position)
            for index, broker_position in enumerate(broker_positions)
            if self._same_shape(local, broker_position)
        ]
        if len(candidates) == 1:
            index, match = candidates[0]
            broker_positions.pop(index)
            return match
        return None

    def _closed_match(self, local: dict[str, Any], closed_history: list[Any]) -> Any | None:
        order_id = str(local.get("broker_order_id") or "")
        for trade in closed_history:
            if order_id and order_id == str(getattr(trade, "broker_order_id", "") or ""):
                return trade
            if (
                str(getattr(trade, "symbol", "")) == str(local.get("symbol") or "")
                and str(getattr(getattr(trade, "side", None), "value", getattr(trade, "side", "")))
                == str(local.get("side") or "")
                and self._same_number(getattr(trade, "volume", None), local.get("volume"))
            ):
                return trade
        return None

    def _same_shape(self, local: dict[str, Any], broker_position: dict[str, Any]) -> bool:
        return (
            str(local.get("symbol") or "") == str(broker_position.get("symbol") or "")
            and str(local.get("side") or "") == str(broker_position.get("side") or "")
            and self._same_number(local.get("volume"), broker_position.get("volume"))
        )

    def _same_number(self, left: Any, right: Any) -> bool:
        try:
            return abs(float(left) - float(right)) <= 1e-8
        except (TypeError, ValueError):
            return False

    def _safe_local(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record.get("id"),
            "broker_order_id": record.get("broker_order_id"),
            "symbol": record.get("symbol"),
            "side": record.get("side"),
            "volume": record.get("volume"),
        }

    def _safe_broker(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record.get("id") or record.get("ticket"),
            "symbol": record.get("symbol"),
            "side": record.get("side"),
            "volume": record.get("volume"),
        }

    def _iso(self, value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)
