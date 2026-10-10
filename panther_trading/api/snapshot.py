from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from panther_trading.advisor import (
    CustomStrategyBuilder,
    DailyOpportunityScanner,
    MarketTrapDetector,
    NewsToTradesTranslator,
    PortfolioRiskAnalyzer,
    PositionSizingManager,
)
from panther_trading.brokers import create_broker
from panther_trading.candles import CandleIntelligenceEngine
from panther_trading.config import load_config
from panther_trading.data import MarketIntelligenceCollector, StaticSentimentCollector
from panther_trading.data.markets import default_watchlist, market_universe
from panther_trading.demo_auto import DemoAutoTrader
from panther_trading.execution import ExecutionEngine
from panther_trading.exits import ExitManager
from panther_trading.journal import TradeJournal
from panther_trading.learning import EvolutionEngine
from panther_trading.live_guard import LiveTradingGate
from panther_trading.live_auto import LiveAutoTrader
from panther_trading.models import Candle, OrderResult, OrderStatus
from panther_trading.positions import PaperPositionBook
from panther_trading.risk import RiskManager
from panther_trading.research import StrategyResearchLab, StrategyTrustGate
from panther_trading.strategies import SmaSentimentStrategy
from panther_trading.validation import EdgeValidationGate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL = PROJECT_ROOT / "var/trade_journal.jsonl"
DEFAULT_POSITIONS = PROJECT_ROOT / "var/paper_positions.jsonl"
DEFAULT_DEMO_AUTO = PROJECT_ROOT / "var/demo_auto_state.json"


def build_dashboard_snapshot(
    config_path: str | Path = "config/demo.yaml",
    symbol: str | None = None,
    record: bool = True,
) -> dict[str, Any]:
    active_symbol = symbol.upper() if symbol else None
    config = load_config(config_path)
    simulator = create_broker("simulated")
    market_broker, market_source, market_error = _market_data_broker(simulator)
    active_symbol = active_symbol or config.app.symbol
    candles, signal_source, signal_error = _safe_candles(
        market_broker,
        simulator,
        active_symbol,
        config.app.timeframe,
        config.app.candles,
        market_source,
    )
    market_intelligence = MarketIntelligenceCollector().collect(active_symbol)
    sentiment = _sentiment_from_intelligence(active_symbol, market_intelligence)
    signal = SmaSentimentStrategy(config.strategy).generate(active_symbol, candles, sentiment)
    order = ExecutionEngine(simulator, RiskManager(config.risk), config.execution).execute(signal)
    broker = broker_status()
    positions = PaperPositionBook(DEFAULT_POSITIONS)
    position_history = positions.latest(limit=1000)
    edge_validation = EdgeValidationGate(config.validation).evaluate(position_history)
    live_readiness = LiveTradingGate(config.execution).readiness(
        broker_status=broker,
        approval_status=None,
        requested_volume=config.execution.default_volume,
        edge_validation_status=edge_validation.status,
    )
    research, research_source, research_error = _safe_research(
        market_broker if signal_source == market_source else simulator,
        simulator,
        active_symbol,
        config.app.timeframe,
        max(config.app.candles, 220),
        market_source if signal_source == market_source else "simulated",
    )
    higher_candles, higher_source, higher_error = _safe_candles(market_broker, simulator, active_symbol, "D1", 3, market_source)
    lower_candles, lower_source, lower_error = _safe_candles(market_broker, simulator, active_symbol, "M5", 80, market_source)
    candle_intelligence = CandleIntelligenceEngine().analyze(
        higher_candles=higher_candles,
        lower_candles=lower_candles,
        higher_timeframe="D1",
        lower_timeframe="M5",
    )
    strategy_gate = StrategyTrustGate().evaluate(research)
    if order.status != OrderStatus.REJECTED and not strategy_gate.allowed:
        order = OrderResult(OrderStatus.REJECTED, strategy_gate.reason)
    journal = TradeJournal(DEFAULT_JOURNAL)
    learning = EvolutionEngine(
        minimum_closed_trades=config.validation.min_demo_trades,
        minimum_profit_factor=config.validation.min_profit_factor,
    ).evaluate(research, position_history, journal.latest(limit=1000))
    exit_review = _exit_review(config, market_broker, simulator, positions.open_positions(), market_source)
    advisor_suite = _advisor_suite(
        config,
        market_broker,
        simulator,
        active_symbol,
        signal,
        candles,
        market_intelligence,
        position_history,
        edge_validation.to_dict(),
    )

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
        "latestClose": candles[-1].close,
        "signal": _jsonable(signal),
        "order": _jsonable(order),
        "strategyGate": {
            "allowed": strategy_gate.allowed,
            "status": strategy_gate.status,
            "reason": strategy_gate.reason,
            "selectedStrategy": strategy_gate.selected_strategy,
        },
        "candleIntelligence": _jsonable(candle_intelligence),
        "marketStructure": _market_structure(active_symbol, config.app.timeframe, candles, signal_source),
        "sentiment": _jsonable(sentiment),
        "broker": broker,
        "positions": positions.open_positions(),
        "edgeValidation": edge_validation.to_dict(),
        "learning": learning.to_dict(),
        "exitReview": exit_review,
        "marketIntelligence": market_intelligence,
        "advisorSuite": advisor_suite,
        "demoAuto": DemoAutoTrader(config_path, DEFAULT_DEMO_AUTO).latest_state(),
        "liveAuto": LiveAutoTrader(config_path, DEFAULT_POSITIONS).status(),
        "demoLimits": {
            "maxOpenPositions": config.demo_auto.max_open_positions,
            "maxOrdersPerCycle": config.demo_auto.max_orders_per_cycle,
            "maxPositionsPerSymbol": config.demo_auto.max_positions_per_symbol,
            "maxSymbolsPerCycle": config.demo_auto.max_symbols_per_cycle,
            "coreRiskMaxOpenPositions": config.risk.max_open_positions,
        },
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
            f"Collected {signal_source.upper()} market candles",
            *(
                [
                    f"Market data fallback: {item}"
                    for item in (market_error, signal_error, research_error, higher_error, lower_error)
                    if item
                ]
            ),
            f"Research source: {research_source.upper()}",
            f"Candle confirmation: {candle_intelligence.confirmation} at {candle_intelligence.confirmation_score:.0%}",
            f"Market intelligence score: {market_intelligence['score']:+.2f}",
            f"Exit manager reviewed {exit_review['reviewed']} open trade(s)",
            f"Opportunity scanner ranked {len(advisor_suite['opportunities'])} setup(s)",
            "Blended technical and sentiment score",
            f"Strategy gate: {strategy_gate.reason}",
            f"Risk decision: {order.message}",
        ],
    }
    if record:
        entry = journal.record_signal(snapshot)
        snapshot["journalEntry"] = entry.__dict__
    return snapshot


def build_market_structure_snapshot(
    config_path: str | Path = "config/demo.yaml",
    symbol: str | None = None,
    timeframe: str | None = None,
    count: int = 120,
) -> dict[str, Any]:
    config = load_config(config_path)
    simulator = create_broker("simulated")
    market_broker, market_source, market_error = _market_data_broker(simulator)
    active_symbol = (symbol or config.app.symbol).upper()
    active_timeframe = (timeframe or config.app.timeframe).upper()
    candles, source, candle_error = _safe_candles(
        market_broker,
        simulator,
        active_symbol,
        active_timeframe,
        max(min(count, 500), 20),
        market_source,
    )
    structure = _market_structure(active_symbol, active_timeframe, candles, source)
    structure["errors"] = [item for item in (market_error, candle_error) if item]
    return structure


def _market_data_broker(simulator: Any) -> tuple[Any, str, str | None]:
    try:
        broker = create_broker()
        if broker.__class__ is simulator.__class__:
            return broker, "simulated", None
        return broker, "mt5", None
    except Exception as exc:
        return simulator, "simulated", str(exc)


def _safe_candles(
    broker: Any,
    fallback: Any,
    symbol: str,
    timeframe: str,
    count: int,
    source: str,
) -> tuple[list[Candle], str, str | None]:
    try:
        candles = broker.get_candles(symbol, timeframe, count)
        if candles:
            return candles, source, None
        raise RuntimeError("broker returned no candles")
    except Exception as exc:
        candles = fallback.get_candles(symbol, timeframe, count)
        return candles, "simulated", f"{symbol} {timeframe}: {exc}"


def _safe_research(
    broker: Any,
    fallback: Any,
    symbol: str,
    timeframe: str,
    candles: int,
    source: str,
) -> tuple[dict[str, Any], str, str | None]:
    try:
        return StrategyResearchLab(broker).run(symbol, timeframe=timeframe, candles=candles), source, None
    except Exception as exc:
        return (
            StrategyResearchLab(fallback).run(symbol, timeframe=timeframe, candles=candles),
            "simulated",
            f"{symbol} research: {exc}",
        )


def _sentiment_from_intelligence(symbol: str, report: dict[str, Any]) -> Any:
    if report.get("sources") and report.get("items"):
        from panther_trading.models import SentimentSnapshot
        from datetime import datetime, timezone

        return SentimentSnapshot(
            symbol=symbol,
            score=float(report.get("score") or 0.0),
            confidence=float(report.get("confidence") or 0.0),
            sources=tuple(report.get("sources") or ()),
            collected_at=datetime.now(timezone.utc),
        )
    return StaticSentimentCollector().collect(symbol)


def _exit_review(
    config: Any,
    broker: Any,
    fallback: Any,
    positions: list[dict[str, Any]],
    source_name: str,
) -> dict[str, Any]:
    manager = ExitManager(config.demo_auto)
    decisions = []
    for position in positions:
        symbol = str(position.get("symbol") or config.app.symbol)
        candles, source, error = _safe_candles(broker, fallback, symbol, "M5", 80, source_name)
        decision = manager.evaluate_position(position, candles).to_dict()
        decision["source"] = source
        if error:
            decision["data_error"] = error
        decisions.append(decision)
    decisions.sort(key=lambda item: (-int(item["priority"]), item["symbol"]))
    return {
        "reviewed": len(decisions),
        "actions": {
            "close": len([item for item in decisions if item["action"] == "close"]),
            "protect": len([item for item in decisions if item["action"] in {"move_to_breakeven", "trail_stop"}]),
            "hold": len([item for item in decisions if item["action"] == "hold"]),
        },
        "decisions": decisions,
        "policy": "Every trade is reviewed for SL/TP touch, thesis invalidation, time stop, breakeven, and trailing protection.",
    }


def _advisor_suite(
    config: Any,
    broker: Any,
    fallback: Any,
    symbol: str,
    signal: Any,
    candles: list[Candle],
    intelligence: dict[str, Any],
    positions: list[dict[str, Any]],
    edge_validation: dict[str, Any],
) -> dict[str, Any]:
    try:
        opportunities = DailyOpportunityScanner().scan(broker, config)
        source = "configured_broker"
    except Exception:
        opportunities = DailyOpportunityScanner().scan(fallback, config)
        source = "simulated_fallback"
    return {
        "source": source,
        "opportunities": opportunities,
        "positionSizing": PositionSizingManager().plan(config, signal, positions),
        "trapDetector": MarketTrapDetector().analyze(symbol, signal.side, candles, intelligence),
        "newsTrades": NewsToTradesTranslator().translate(intelligence, opportunities),
        "portfolioRisk": PortfolioRiskAnalyzer().analyze(positions, config),
        "customStrategy": CustomStrategyBuilder().build(config, edge_validation),
    }


def _market_structure(symbol: str, timeframe: str, candles: list[Candle], source: str) -> dict[str, Any]:
    recent = candles[-60:]
    closes = [candle.close for candle in recent]
    highs = [candle.high for candle in recent]
    lows = [candle.low for candle in recent]
    latest = closes[-1]
    high = max(highs)
    low = min(lows)
    previous = closes[-2] if len(closes) > 1 else latest
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": source,
        "latest": round(latest, 6),
        "high": round(high, 6),
        "low": round(low, 6),
        "range": round(high - low, 6),
        "change": round(latest - previous, 6),
        "closes": [round(close, 6) for close in closes],
        "candles": [
            {
                "time": candle.time.isoformat(),
                "open": round(candle.open, 6),
                "high": round(candle.high, 6),
                "low": round(candle.low, 6),
                "close": round(candle.close, 6),
                "volume": round(candle.volume, 6),
            }
            for candle in recent
        ],
    }


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
    items = default_watchlist(14)
    gold = next((item for item in default_watchlist(48) if item.symbol == "XAUUSD"), None)
    if gold and all(item.symbol != "XAUUSD" for item in items):
        items = [*items[:6], gold, *items[6:13]]
    for index, item in enumerate(items):
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
