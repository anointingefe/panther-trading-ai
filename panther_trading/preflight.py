from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from panther_trading.models import SignalSide


def execution_preflight(
    broker: Any,
    symbol: str,
    side: SignalSide,
    requested_volume: float,
    planned_entry: float,
    stop_loss: float,
    take_profit: float,
) -> dict[str, Any]:
    """Validate an order against live broker conditions without sending it."""
    if not hasattr(broker, "mt5"):
        return broker.execution_preflight(
            symbol,
            side,
            requested_volume,
            planned_entry,
            stop_loss,
            take_profit,
        )

    mt5 = broker.mt5
    blockers: list[str] = []
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None:
        blockers.append("Broker symbol metadata is unavailable.")
    if tick is None:
        blockers.append("Live broker quote is unavailable.")

    point = float(getattr(info, "point", 0.0) or 0.0) if info is not None else 0.0
    bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick is not None else 0.0
    ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick is not None else 0.0
    if tick is not None and (not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask <= 0 or ask < bid):
        blockers.append("Broker quote is invalid.")

    market_price = ask if side == SignalSide.BUY else bid
    bracket_valid = (
        stop_loss < market_price < take_profit
        if side == SignalSide.BUY
        else take_profit < market_price < stop_loss
    ) if market_price > 0 else False
    if not bracket_valid:
        blockers.append("Market moved outside the planned stop/target bracket.")

    normalized_volume = float(requested_volume)
    if hasattr(broker, "_normalized_volume"):
        try:
            normalized_volume = float(broker._normalized_volume(symbol, requested_volume))
        except Exception as exc:
            blockers.append(f"Broker volume normalization failed: {exc}")
            normalized_volume = 0.0
    volume_valid = math.isfinite(normalized_volume) and normalized_volume > 0
    if not volume_valid:
        blockers.append("No broker-valid volume fits the order.")

    stop_level_points = float(getattr(info, "trade_stops_level", 0.0) or 0.0) if info is not None else 0.0
    spread_points = ((ask - bid) / point) if point > 0 and ask >= bid > 0 else None
    stop_distance_points = abs(market_price - stop_loss) / point if point > 0 and market_price > 0 else None
    target_distance_points = abs(take_profit - market_price) / point if point > 0 and market_price > 0 else None
    if stop_level_points > 0:
        if stop_distance_points is not None and stop_distance_points < stop_level_points:
            blockers.append("Stop-loss violates the broker minimum stop distance.")
        if target_distance_points is not None and target_distance_points < stop_level_points:
            blockers.append("Take-profit violates the broker minimum stop distance.")

    quote_seconds = None
    if tick is not None:
        raw_time_msc = int(getattr(tick, "time_msc", 0) or 0)
        raw_time = int(getattr(tick, "time", 0) or 0)
        quote_timestamp = raw_time_msc / 1000 if raw_time_msc > 0 else float(raw_time)
        if quote_timestamp > 0:
            quote_seconds = max(datetime.now(timezone.utc).timestamp() - quote_timestamp, 0.0)

    trade_mode = getattr(info, "trade_mode", None) if info is not None else None
    disabled = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", None)
    close_only = getattr(mt5, "SYMBOL_TRADE_MODE_CLOSEONLY", None)
    if disabled is not None and trade_mode == disabled:
        blockers.append("Symbol trading is disabled by the broker.")
    if close_only is not None and trade_mode == close_only:
        blockers.append("Symbol is close-only at the broker.")

    order_check_retcode = None
    order_check_comment = None
    if not blockers and hasattr(mt5, "order_check"):
        order_type = mt5.ORDER_TYPE_BUY if side == SignalSide.BUY else mt5.ORDER_TYPE_SELL
        payload = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": normalized_volume,
            "type": order_type,
            "price": market_price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 20,
            "magic": 26001007,
            "comment": "PANTHER shadow preflight",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        filling_modes = (
            getattr(mt5, "ORDER_FILLING_FOK", None),
            getattr(mt5, "ORDER_FILLING_IOC", None),
            getattr(mt5, "ORDER_FILLING_RETURN", None),
        )
        checks = []
        for mode in filling_modes:
            if mode is None:
                continue
            try:
                check = mt5.order_check({**payload, "type_filling": mode})
            except Exception as exc:
                checks.append((None, str(exc)))
                continue
            if check is None:
                checks.append((None, str(mt5.last_error())))
                continue
            retcode = int(getattr(check, "retcode", -1))
            comment = str(getattr(check, "comment", ""))
            checks.append((retcode, comment))
            if retcode == 0 or retcode == getattr(mt5, "TRADE_RETCODE_DONE", None):
                order_check_retcode = retcode
                order_check_comment = comment or "Done"
                break
        else:
            if checks:
                order_check_retcode, order_check_comment = checks[-1]
                blockers.append(f"Broker order_check rejected shadow order: {order_check_comment or order_check_retcode}.")

    return {
        "broker_native": True,
        "executable": not blockers,
        "symbol": symbol,
        "side": side.value,
        "planned_entry": planned_entry,
        "market_price": market_price if market_price > 0 else planned_entry,
        "bid": bid or None,
        "ask": ask or None,
        "spread_points": round(spread_points, 4) if spread_points is not None else None,
        "point": point or None,
        "quote_age_seconds": round(quote_seconds, 4) if quote_seconds is not None else None,
        "stop_level_points": stop_level_points,
        "stop_distance_points": round(stop_distance_points, 4) if stop_distance_points is not None else None,
        "target_distance_points": round(target_distance_points, 4) if target_distance_points is not None else None,
        "requested_volume": requested_volume,
        "normalized_volume": normalized_volume,
        "volume_valid": volume_valid,
        "bracket_valid": bracket_valid,
        "order_check_retcode": order_check_retcode,
        "order_check_comment": order_check_comment,
        "blockers": blockers,
    }
