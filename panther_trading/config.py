from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AppConfig:
    mode: str
    symbol: str
    timeframe: str
    candles: int


@dataclass(frozen=True)
class RiskConfig:
    account_equity: float
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    min_confidence: float
    max_open_positions: int


@dataclass(frozen=True)
class StrategyConfig:
    fast_sma: int
    slow_sma: int
    sentiment_weight: float


@dataclass(frozen=True)
class ExecutionConfig:
    allow_live_trading: bool
    default_volume: float
    require_manual_approval: bool = True
    max_live_volume: float = 0.1
    allowed_live_account_modes: tuple[str, ...] = ("demo",)
    live_unlock_phrase: str = "PANTHER_LIVE_APPROVED"


@dataclass(frozen=True)
class PantherConfig:
    app: AppConfig
    risk: RiskConfig
    strategy: StrategyConfig
    execution: ExecutionConfig


def load_config(path: str | Path) -> PantherConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    execution = _section(raw, "execution")
    allowed_modes = execution.get("allowed_live_account_modes", ("demo",))
    execution["allowed_live_account_modes"] = tuple(allowed_modes)
    return PantherConfig(
        app=AppConfig(**_section(raw, "app")),
        risk=RiskConfig(**_section(raw, "risk")),
        strategy=StrategyConfig(**_section(raw, "strategy")),
        execution=ExecutionConfig(**execution),
    )


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"Missing config section: {name}")
    return value
