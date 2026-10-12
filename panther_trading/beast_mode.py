from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from panther_trading.config import PantherConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BEAST_MODE = PROJECT_ROOT / "var/beast_mode.json"


@dataclass(frozen=True)
class BeastModeState:
    enabled: bool = False
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BeastModeStore:
    def __init__(self, path: str | Path = DEFAULT_BEAST_MODE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> BeastModeState:
        if not self.path.exists():
            return BeastModeState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return BeastModeState()
        return BeastModeState(
            enabled=bool(payload.get("enabled", False)),
            updated_at=str(payload.get("updated_at") or payload.get("updatedAt") or ""),
        )

    def update(self, enabled: bool) -> BeastModeState:
        state = BeastModeState(enabled=bool(enabled), updated_at=datetime.now(timezone.utc).isoformat())
        self.path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        return state

    def status(self, config: PantherConfig, positions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        state = self.load()
        effective = apply_beast_mode(config, state.enabled)
        disabled_reason = _daily_loss_reason(config, positions or []) if state.enabled else None
        return {
            "enabled": state.enabled,
            "active": state.enabled and disabled_reason is None,
            "updatedAt": state.updated_at,
            "disabledReason": disabled_reason,
            "profile": {
                "minConfidence": effective.risk.min_confidence,
                "riskPerTradePct": effective.risk.max_risk_per_trade_pct,
                "demoOrderVolume": effective.demo_auto.demo_order_volume,
                "demoOrdersPerCycle": effective.demo_auto.max_orders_per_cycle,
                "maxOpenPositions": effective.demo_auto.max_open_positions,
                "maxLiveVolume": effective.execution.max_live_volume,
                "hardRiskCapPct": config.beast_mode.max_risk_per_trade_pct_cap,
            },
            "warning": (
                "Beast mode increases risk and trade frequency. It still obeys stop-loss, "
                "daily-loss, broker, live unlock, and volume caps."
            ),
        }


def apply_beast_mode(config: PantherConfig, enabled: bool, positions: list[dict[str, Any]] | None = None) -> PantherConfig:
    if not enabled or _daily_loss_reason(config, positions or []):
        return config
    beast = config.beast_mode
    risk = replace(
        config.risk,
        max_risk_per_trade_pct=min(
            config.risk.max_risk_per_trade_pct * beast.live_risk_multiplier,
            beast.max_risk_per_trade_pct_cap,
        ),
        min_confidence=max(0.01, config.risk.min_confidence - beast.confidence_floor_delta),
        max_open_positions=config.risk.max_open_positions + beast.extra_open_positions,
    )
    demo_auto = replace(
        config.demo_auto,
        max_orders_per_cycle=config.demo_auto.max_orders_per_cycle + beast.extra_orders_per_cycle,
        max_open_positions=config.demo_auto.max_open_positions + beast.extra_open_positions,
        demo_order_volume=round(config.demo_auto.demo_order_volume * beast.demo_order_multiplier, 4),
        scout_min_confidence=max(0.01, config.demo_auto.scout_min_confidence - beast.scout_floor_delta),
        max_kelly_fraction=config.demo_auto.max_kelly_fraction * beast.demo_order_multiplier,
    )
    execution = replace(
        config.execution,
        max_live_volume=min(
            config.execution.max_live_volume * beast.live_volume_multiplier,
            beast.max_live_volume_cap,
        ),
    )
    return replace(config, risk=risk, demo_auto=demo_auto, execution=execution)


def _daily_loss_reason(config: PantherConfig, positions: list[dict[str, Any]]) -> str | None:
    if not config.beast_mode.disable_after_daily_loss:
        return None
    today = datetime.now(timezone.utc).date()
    pnl = 0.0
    for position in positions:
        if position.get("status") != "closed":
            continue
        closed_at = str(position.get("closed_at") or "")
        if not closed_at.startswith(today.isoformat()):
            continue
        pnl += float(position.get("pnl") or 0.0)
    return "Disabled after today's realized loss; Panther is protecting capital." if pnl < 0 else None
