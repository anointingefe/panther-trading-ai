from datetime import datetime, timezone

from panther_trading.beast_mode import BeastModeStore, apply_beast_mode
from panther_trading.api.server import _bool_flag
from panther_trading.config import load_config


def test_beast_mode_off_preserves_existing_config() -> None:
    config = load_config("config/demo.yaml")

    assert apply_beast_mode(config, False) == config


def test_beast_mode_profile_increases_aggression_inside_caps(tmp_path) -> None:
    config = load_config("config/demo.yaml")
    store = BeastModeStore(tmp_path / "beast_mode.json")
    state = store.update(True)
    effective = apply_beast_mode(config, state.enabled)

    assert effective.risk.min_confidence < config.risk.min_confidence
    assert effective.risk.max_risk_per_trade_pct <= config.beast_mode.max_risk_per_trade_pct_cap
    assert effective.demo_auto.demo_order_volume > config.demo_auto.demo_order_volume
    assert effective.demo_auto.max_orders_per_cycle > config.demo_auto.max_orders_per_cycle
    assert effective.execution.max_live_volume <= config.beast_mode.max_live_volume_cap


def test_beast_mode_pauses_after_daily_loss(tmp_path) -> None:
    config = load_config("config/demo.yaml")
    store = BeastModeStore(tmp_path / "beast_mode.json")
    store.update(True)
    positions = [
        {
            "status": "closed",
            "pnl": -5,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }
    ]

    status = store.status(config, positions)
    effective = apply_beast_mode(config, status["enabled"], positions)

    assert status["enabled"] is True
    assert status["active"] is False
    assert "protecting capital" in status["disabledReason"]
    assert effective.risk.min_confidence == config.risk.min_confidence


def test_beast_mode_api_bool_parser_does_not_treat_false_string_as_true() -> None:
    assert _bool_flag("false") is False
    assert _bool_flag("true") is True
