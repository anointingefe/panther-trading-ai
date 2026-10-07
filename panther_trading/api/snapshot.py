from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from panther_trading.cli import run_once_command
from panther_trading.brokers import create_broker
from panther_trading.candles import CandleIntelligenceEngine
from panther_trading.config import load_config
from panther_trading.data.markets import default_watchlist, market_universe
from panther_trading.journal import TradeJournal
from panther_trading.live_guard import LiveTradingGate
from panther_trading.models import OrderResult, OrderStatus
from panther_trading.positions import PaperPositionBook
from panther_trading.research import StrategyResearchLab, StrategyTrustGate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL = PROJECT_ROOT / "var/trade_journal.jsonl"
DEFAULT_POSITIONS = PROJECT_ROOT / "var/paper_positions.jsonl"


def build_dashboard_snapshot(
    config_path: str | Path = "config/demo.yaml",
    symbol: str | None = None,
    record: bool = True,
) -> dict[str, Any]:
    active_symbol = symbol.upper() if symbol else None
    result = run_once_command(Path(config_path), symbol=active_symbol)
    config = load_config(config_path)
    signal = result["signal"]
    order = result["order"]
    active_symbol = active_symbol or result["symbol"]
    simulator = create_broker("simulated")
    broker = broker_status()
    live_readiness = LiveTradingGate(config.execution).readiness(
        broker_status=broker,
        approval_status=None,
        requested_volume=config.execution.default_volume,
    )
    research = StrategyResearchLab(simulator).run(
        active_symbol,
        timeframe=config.app.timeframe,
        candles=max(config.app.candles, 220),
    )
    candle_intelligence = CandleIntelligenceEngine().analyze(
        higher_candles=simulator.get_candles(active_symbol, "D1", 3),
        lower_candles=simulator.get_candles(active_symbol, "M5", 80),
        higher_timeframe="D1",
        lower_timeframe="M5",
    )
    strategy_gate = StrategyTrustGate().evaluate(research)
    if order.status != OrderStatus.REJECTED and not strategy_gate.allowed:
        order = OrderResult(OrderStatus.REJECTED, strategy_gate.reason)

    snapshot = {
        "mode": "Paper",
        "systemStatus": "Risk Guard Active",
        "executionMode": {
            "active": "demo",
            "liveEnabled": config.execution.allow_live_trading,
            "liveLockedReason": _live_lock_reason(config.execution.allow_live_trading),
        },
        "liveReadiness": {
            "enabled": live_readiness.enabled,
            "armed": live_readiness.armed,
            "reasons": list(live_readiness.reasons),
            "checklist": list(live_readiness.checklist),
        },
        "symbol": active_symbol,
        "latestClose": result["latest_close"],
        "signal": _jsonable(signal),
        "order": _jsonable(order),
        "strategyGate": {
            "allowed": strategy_gate.allowed,
            "status": strategy_gate.status,
            "reason": strategy_gate.reason,
            "selectedStrategy": strategy_gate.selected_strategy,
        },
        "candleIntelligence": _jsonable(candle_intelligence),
        "sentiment": _jsonable(result["sentiment"]),
        "broker": broker,
        "positions": PaperPositionBook(DEFAULT_POSITIONS).open_positions(),
        "research": research,
        "markets": market_universe(),
        "metrics": {
            "equity": 10000,
            "dailyPnl": 0,
            "winRate": 0,
            "riskUsed": 0,
        },
        "watchlist": _build_watchlist(signal),
        "activity": [
            "Collected latest market candles",
            f"Candle confirmation: {candle_intelligence.confirmation} at {candle_intelligence.confirmation_score:.0%}",
            "Blended technical and sentiment score",
            f"Strategy gate: {strategy_gate.reason}",
            f"Risk decision: {order.message}",
        ],
    }
    if record:
        entry = TradeJournal(DEFAULT_JOURNAL).record_signal(snapshot)
        snapshot["journalEntry"] = entry.__dict__
    return snapshot


def _live_lock_reason(allow_live_trading: bool) -> str | None:
    if allow_live_trading:
        return None
    return "Live trading is locked in backend config. Demo mode only."


def broker_status(kind: str | None = None) -> dict[str, Any]:
    try:
        broker = create_broker(kind)
        status = broker.get_status()
        symbols = broker.list_symbols()
        return {
            **_jsonable(status),
            "symbols_sample": symbols[:24],
        }
    except Exception as exc:
        return {
            "name": kind or "Configured broker",
            "connected": False,
            "mode": "unavailable",
            "account_login": None,
            "account_server": None,
            "balance": None,
            "equity": None,
            "open_positions": 0,
            "symbols_total": 0,
            "message": str(exc),
            "symbols_sample": [],
        }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def _build_watchlist(signal: Any) -> list[dict[str, Any]]:
    biases = ("WAIT", "WATCH", "BUY", "SELL")
    watchlist: list[dict[str, Any]] = []
    for index, item in enumerate(default_watchlist(14)):
        if index == 0:
            bias = signal.side.value.upper()
            confidence = signal.confidence
        else:
            bias = biases[index % len(biases)]
            confidence = round(0.28 + (index % 7) * 0.085, 2)
        watchlist.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "group": item.group,
                "bias": bias,
                "confidence": min(confidence, 0.91),
            }
        )
    return watchlist
