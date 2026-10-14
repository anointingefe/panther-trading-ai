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
    max_positions_per_symbol: int = 1


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
class DemoAutoConfig:
    enabled: bool = False
    interval_seconds: int = 300
    max_symbols_per_cycle: int = 96
    max_orders_per_cycle: int = 12
    max_open_positions: int = 12
    max_positions_per_symbol: int = 1
    demo_order_volume: float = 0.01
    scout_min_confidence: float = 0.48
    scout_volume_multiplier: float = 0.35
    allowed_account_modes: tuple[str, ...] = ("demo", "contest", "paper")
    loss_cooldown_hours: int = 6
    max_consecutive_symbol_losses: int = 1
    volatility_spike_multiplier: float = 2.5
    temporal_min_samples: int = 8
    temporal_min_win_rate: float = 0.65
    bayes_prior_wins: float = 3.0
    bayes_prior_losses: float = 2.0
    bayes_confidence_weight: float = 0.35
    symbol_min_closed_trades: int = 6
    symbol_min_win_rate: float = 0.55
    symbol_min_net_pnl: float = 0.0
    symbol_min_edge_probability: float = 0.55
    max_kelly_fraction: float = 0.005
    exit_max_trade_minutes: int = 240
    exit_breakeven_at_r: float = 1.0
    exit_trail_at_r: float = 1.5


@dataclass(frozen=True)
class LiveScoutConfig:
    enabled: bool = True
    interval_seconds: int = 30
    max_symbols_per_cycle: int = 96
    max_candidates_per_cycle: int = 12
    history_sync_days: int = 30
    learning_min_segment_samples: int = 6
    ticket_max_age_seconds: int = 120
    allowed_account_modes: tuple[str, ...] = ("demo", "contest", "real")


@dataclass(frozen=True)
class ValidationConfig:
    min_demo_trades: int = 30
    min_demo_days: int = 14
    min_profit_factor: float = 1.2
    min_net_r: float = 5.0
    min_win_rate: float = 0.35
    max_drawdown_r: float = 6.0


@dataclass(frozen=True)
class BeastModeConfig:
    enabled: bool = False
    demo_order_multiplier: float = 1.0
    live_risk_multiplier: float = 1.0
    live_volume_multiplier: float = 1.0
    confidence_floor_delta: float = 0.0
    scout_floor_delta: float = 0.0
    extra_orders_per_cycle: int = 0
    extra_open_positions: int = 0
    max_risk_per_trade_pct_cap: float = 1.0
    max_live_volume_cap: float = 0.02
    disable_after_daily_loss: bool = True


@dataclass(frozen=True)
class ShadowExecutionConfig:
    enabled: bool = True
    interval_seconds: int = 30
    max_symbols_per_cycle: int = 48
    max_samples_retained: int = 1000
    max_observation_minutes: int = 240
    min_samples: int = 50
    min_reconciliation_samples: int = 20
    min_preflight_pass_rate: float = 0.99
    min_quote_fresh_rate: float = 0.99
    max_quote_age_seconds: float = 10.0
    max_spread_to_stop_ratio: float = 0.25
    max_reconciliation_mismatches: int = 0


@dataclass(frozen=True)
class PantherConfig:
    app: AppConfig
    risk: RiskConfig
    strategy: StrategyConfig
    execution: ExecutionConfig
    demo_auto: DemoAutoConfig
    live_scout: LiveScoutConfig
    validation: ValidationConfig
    beast_mode: BeastModeConfig
    shadow_execution: ShadowExecutionConfig = ShadowExecutionConfig()


def load_config(path: str | Path) -> PantherConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    execution = _section(raw, "execution")
    allowed_modes = execution.get("allowed_live_account_modes", ("demo",))
    execution["allowed_live_account_modes"] = tuple(allowed_modes)
    demo_auto = raw.get("demo_auto", {})
    demo_auto_modes = demo_auto.get("allowed_account_modes", ("demo", "contest", "paper"))
    demo_auto["allowed_account_modes"] = tuple(demo_auto_modes)
    live_scout = raw.get("live_scout", {})
    live_scout_modes = live_scout.get("allowed_account_modes", ("demo", "contest", "real"))
    live_scout["allowed_account_modes"] = tuple(live_scout_modes)
    return PantherConfig(
        app=AppConfig(**_section(raw, "app")),
        risk=RiskConfig(**_section(raw, "risk")),
        strategy=StrategyConfig(**_section(raw, "strategy")),
        execution=ExecutionConfig(**execution),
        demo_auto=DemoAutoConfig(**demo_auto),
        live_scout=LiveScoutConfig(**live_scout),
        validation=ValidationConfig(**raw.get("validation", {})),
        beast_mode=BeastModeConfig(**raw.get("beast_mode", {})),
        shadow_execution=ShadowExecutionConfig(**raw.get("shadow_execution", {})),
    )


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"Missing config section: {name}")
    return value
