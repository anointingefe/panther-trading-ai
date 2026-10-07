from __future__ import annotations

import os

from panther_trading.brokers.base import Broker
from panther_trading.brokers.mt5 import MT5Broker
from panther_trading.brokers.simulated import SimulatedBroker


def create_broker(kind: str | None = None) -> Broker:
    selected = (kind or os.getenv("PANTHER_BROKER") or "simulated").strip().lower()
    if selected in {"sim", "simulated", "paper"}:
        return SimulatedBroker()
    if selected in {"mt5", "metatrader5", "metatrader"}:
        return MT5Broker()
    raise ValueError(f"Unsupported broker type: {selected}")
