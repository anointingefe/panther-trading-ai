"""Read-only trade notifications, independent of order submission and validation."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone

from panther_trading.brokers.mt5 import PANTHER_MAGIC


def _net(deals) -> float:
    values = [float(getattr(deal, field, 0) or 0) for deal in deals
              for field in ("profit", "commission", "swap", "fee")]
    if not all(math.isfinite(value) for value in values):
        raise RuntimeError("Non-finite broker P/L; trade result unavailable")
    return round(sum(values), 8)


def position_events(deals, mt5) -> list[dict]:
    """Include manual exits of Panther positions; never infer closure from absence."""
    deals = sorted(deals, key=lambda d: (getattr(d, "time_msc", d.time * 1000), d.ticket))
    entries = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
    if not entries or entries[0].magic != PANTHER_MAGIC:
        return []
    owned = all(d.magic == PANTHER_MAGIC for d in entries)
    remaining = 0.0
    accumulated = []
    results = []
    reversal = False
    for deal in deals:
        accumulated.append(deal)
        volume = float(deal.volume)
        if not math.isfinite(volume) or volume < 0:
            raise RuntimeError("Invalid broker volume")
        pnl = None
        if deal.entry == mt5.DEAL_ENTRY_IN:
            kind = "opened" if remaining <= 1e-8 else "increased"
            remaining += volume
            if deal.magic != PANTHER_MAGIC:
                continue
        elif deal.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
            remaining -= volume
            kind = "closed" if abs(remaining) <= 1e-8 else "partial_close"
            if owned and not reversal and remaining >= -1e-8:
                pnl = _net(accumulated) if kind == "closed" else _net([deal])
        elif deal.entry == mt5.DEAL_ENTRY_INOUT:
            reversal = True
            kind = "reversed"
        else:
            continue
        outcome = ("win" if pnl > 0 else "loss" if pnl < 0 else "breakeven") if pnl is not None and kind == "closed" else None
        results.append({
            "id": f"deal:{deal.ticket}", "positionId": str(deal.position_id),
            "time": float(getattr(deal, "time_msc", deal.time * 1000)) / 1000,
            "kind": kind, "symbol": deal.symbol,
            "side": "buy" if entries[0].type == mt5.DEAL_TYPE_BUY else "sell",
            "volume": volume, "price": float(deal.price), "pnl": pnl,
            "outcome": outcome, "resultKnown": outcome is not None,
        })
    return results


def collect_trade_events(broker, positions, since: float | None = None) -> dict:
    now = datetime.now(timezone.utc)
    if since is not None and not math.isfinite(since):
        raise ValueError("Invalid notification cursor")
    requested = now.timestamp() - 86400 if since is None else since - 60
    cutoff = max(now.timestamp() - 7 * 86400, min(now.timestamp(), requested))
    if hasattr(broker, "mt5"):
        mt5 = broker.mt5
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None or not terminal.connected:
            raise RuntimeError("MT5 disconnected; notifications paused")
        identity = (account.server, account.login, account.trade_mode)
        scope = hashlib.sha256(repr(identity).encode()).hexdigest()[:24]
        recent = mt5.history_deals_get(datetime.fromtimestamp(cutoff, timezone.utc), now)
        if recent is None:
            raise RuntimeError("MT5 deal history unavailable; notifications paused")
        position_ids = {d.position_id for d in recent if d.position_id and d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL)}
        events = []
        for position_id in position_ids:
            history = mt5.history_deals_get(position=position_id)
            if history is None:
                raise RuntimeError("MT5 position history unavailable; notifications paused")
            events.extend(event for event in position_events(history, mt5) if event["time"] >= cutoff)
        after = mt5.account_info()
        if after is None or (after.server, after.login, after.trade_mode) != identity:
            raise RuntimeError("MT5 account changed during history read; retry required")
        return {"scope": scope, "source": "mt5", "mode": broker._account_mode(account.trade_mode),
                "currency": account.currency, "asOf": now.timestamp(),
                "events": sorted(events, key=lambda event: (event["time"], event["id"]))}
    events = []
    for position in positions.latest(limit=10000):
        if (position.get("metadata") or {}).get("source") == "mt5":
            continue
        for kind, date in (("opened", position.get("opened_at")), ("closed", position.get("closed_at"))):
            if not date:
                continue
            timestamp = datetime.fromisoformat(date).timestamp()
            if timestamp < cutoff:
                continue
            pnl = position.get("pnl") if kind == "closed" else None
            outcome = ("win" if pnl > 0 else "loss" if pnl < 0 else "breakeven") if pnl is not None else None
            events.append({"id": f"paper:{position['id']}:{kind}", "positionId": position["id"],
                           "kind": kind, "time": timestamp, "symbol": position["symbol"],
                           "side": position["side"], "volume": position["volume"],
                           "price": position.get("close_price") if kind == "closed" else position["entry"],
                           "pnl": pnl, "outcome": outcome, "resultKnown": outcome is not None})
    return {"scope": "paper-local", "source": "paper", "mode": "simulated", "currency": "",
            "asOf": now.timestamp(), "events": sorted(events, key=lambda event: (event["time"], event["id"]))}
