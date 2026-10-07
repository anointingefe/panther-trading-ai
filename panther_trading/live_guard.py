from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from panther_trading.config import ExecutionConfig


@dataclass(frozen=True)
class LiveReadiness:
    enabled: bool
    armed: bool
    reasons: tuple[str, ...]
    checklist: tuple[str, ...]


class LiveTradingGate:
    def __init__(self, config: ExecutionConfig) -> None:
        self.config = config

    def readiness(
        self,
        broker_status: dict[str, Any],
        approval_status: str | None = None,
        requested_volume: float | None = None,
        unlock_phrase: str | None = None,
        edge_validation_status: str | None = None,
    ) -> LiveReadiness:
        reasons: list[str] = []
        checklist = [
            "Live trading must be enabled in backend config.",
            "Broker must be connected through the MT5 adapter.",
            "Account mode must be explicitly allowed.",
            "Manual approval must exist for the exact signal.",
            "Requested volume must be inside the live cap.",
            "Demo edge validation must pass.",
            "Operator must provide the live unlock phrase.",
        ]

        if not self.config.allow_live_trading:
            reasons.append("Backend config has allow_live_trading=false.")

        if broker_status.get("name") != "MetaTrader 5":
            reasons.append("Active broker is not MetaTrader 5.")

        if not broker_status.get("connected"):
            reasons.append("Broker is not connected.")

        account_mode = str(broker_status.get("mode") or "unknown").lower()
        allowed_modes = {mode.lower() for mode in self.config.allowed_live_account_modes}
        if account_mode not in allowed_modes:
            reasons.append(f"Account mode '{account_mode}' is not allowed for live execution.")

        if self.config.require_manual_approval and approval_status != "approved":
            reasons.append("Manual approval is required before execution.")

        volume = float(requested_volume if requested_volume is not None else self.config.default_volume)
        if volume <= 0:
            reasons.append("Requested volume must be greater than zero.")
        if volume > self.config.max_live_volume:
            reasons.append("Requested volume exceeds max_live_volume.")

        if edge_validation_status != "passed":
            reasons.append("Demo edge validation has not passed.")

        if unlock_phrase != self.config.live_unlock_phrase:
            reasons.append("Live unlock phrase was not provided.")

        enabled = self.config.allow_live_trading
        armed = enabled and not reasons
        return LiveReadiness(
            enabled=enabled,
            armed=armed,
            reasons=tuple(reasons),
            checklist=tuple(checklist),
        )
