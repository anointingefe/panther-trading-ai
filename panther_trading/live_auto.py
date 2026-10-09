from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from panther_trading.brokers import create_broker
from panther_trading.config import load_config
from panther_trading.execution import ExecutionEngine
from panther_trading.live_guard import LiveTradingGate
from panther_trading.positions import PaperPositionBook
from panther_trading.risk import RiskManager
from panther_trading.validation import EdgeValidationGate


@dataclass(frozen=True)
class LiveAutoStatus:
    built: bool
    armed: bool
    enabled: bool
    message: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "built": self.built,
            "armed": self.armed,
            "enabled": self.enabled,
            "message": self.message,
            "reasons": list(self.reasons),
        }


class LiveAutoTrader:
    """Live execution path.

    This is deliberately stricter than the demo runner. It exists so the live
    path can be tested and audited, but it refuses to place orders until the
    live guard is fully armed.
    """

    def __init__(self, config_path: str | Path, positions_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self.positions_path = Path(positions_path)

    def status(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        edge = EdgeValidationGate(config.validation).evaluate(self._positions()).to_dict()
        readiness = LiveTradingGate(config.execution).readiness(
            broker_status=self._broker_status(),
            approval_status=None,
            requested_volume=config.execution.default_volume,
            edge_validation_status=edge["status"],
            unlock_phrase=None,
        )
        return LiveAutoStatus(
            built=True,
            armed=readiness.armed,
            enabled=config.execution.allow_live_trading,
            message=(
                "Live runner is built but locked by safety gates."
                if not readiness.armed
                else "Live runner can execute only explicitly approved signals."
            ),
            reasons=readiness.reasons,
        ).to_dict()

    def execute_approved_signal(
        self,
        journal_entry: dict[str, Any],
        unlock_phrase: str | None = None,
    ) -> dict[str, Any]:
        config = load_config(self.config_path)
        edge = EdgeValidationGate(config.validation).evaluate(self._positions()).to_dict()
        readiness = LiveTradingGate(config.execution).readiness(
            broker_status=self._broker_status("mt5"),
            approval_status=str(journal_entry.get("approval_status")),
            requested_volume=config.execution.default_volume,
            edge_validation_status=edge["status"],
            unlock_phrase=unlock_phrase,
        )
        if not readiness.armed:
            return {
                "status": "blocked",
                "message": "Live execution refused by guard.",
                "reasons": list(readiness.reasons),
            }

        from panther_trading.models import SignalSide, TradeSignal
        from datetime import datetime, timezone

        signal = TradeSignal(
            symbol=str(journal_entry["symbol"]),
            side=SignalSide(str(journal_entry["side"])),
            confidence=float(journal_entry["confidence"]),
            entry=float(journal_entry["entry"]),
            stop_loss=float(journal_entry["stop_loss"]),
            take_profit=float(journal_entry["take_profit"]),
            rationale=tuple(journal_entry.get("rationale") or ()),
            generated_at=datetime.now(timezone.utc),
        )
        result = ExecutionEngine(create_broker("mt5"), RiskManager(config.risk), config.execution).execute(signal)
        return {"status": result.status.value, "message": result.message, "brokerOrderId": result.broker_order_id}

    def _positions(self) -> list[dict[str, Any]]:
        return PaperPositionBook(self.positions_path).latest(limit=1000) if self.positions_path.exists() else []

    def _broker_status(self, kind: str | None = None) -> dict[str, Any]:
        try:
            broker = create_broker(kind)
            status = broker.get_status()
            return {
                "name": status.name,
                "connected": status.connected,
                "mode": status.mode,
                "account_login": status.account_login,
                "account_server": status.account_server,
                "balance": status.balance,
                "equity": status.equity,
                "open_positions": status.open_positions,
                "symbols_total": status.symbols_total,
                "message": status.message,
            }
        except Exception as exc:
            return {
                "name": kind or "Configured broker",
                "connected": False,
                "mode": "unavailable",
                "message": str(exc),
            }
