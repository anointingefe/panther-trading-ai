from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any

from panther_trading.brokers import SimulatedBroker
from panther_trading.config import load_config
from panther_trading.data import StaticSentimentCollector
from panther_trading.execution import ExecutionEngine
from panther_trading.risk import RiskManager
from panther_trading.strategies import SmaSentimentStrategy


def main() -> None:
    parser = argparse.ArgumentParser(prog="panther-trading")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser("run-once", help="Generate and paper-execute one signal")
    run_once.add_argument("--config", default="config/demo.yaml")
    run_once.add_argument("--symbol")

    args = parser.parse_args()
    if args.command == "run-once":
        result = run_once_command(Path(args.config), symbol=args.symbol)
        print(json.dumps(_jsonable(result), indent=2))


def run_once_command(config_path: Path, symbol: str | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    if symbol:
        config = replace(config, app=replace(config.app, symbol=symbol.upper()))

    broker = SimulatedBroker()
    sentiment_collector = StaticSentimentCollector()
    strategy = SmaSentimentStrategy(config.strategy)
    risk_manager = RiskManager(config.risk)
    execution_engine = ExecutionEngine(broker, risk_manager, config.execution)

    candles = broker.get_candles(config.app.symbol, config.app.timeframe, config.app.candles)
    sentiment = sentiment_collector.collect(config.app.symbol)
    signal = strategy.generate(config.app.symbol, candles, sentiment)
    order = execution_engine.execute(signal)

    return {
        "symbol": config.app.symbol,
        "latest_close": candles[-1].close,
        "sentiment": sentiment,
        "signal": signal,
        "order": order,
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


if __name__ == "__main__":
    main()
