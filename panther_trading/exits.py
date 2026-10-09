from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from panther_trading.config import DemoAutoConfig
from panther_trading.models import Candle


@dataclass(frozen=True)
class ExitDecision:
    position_id: str
    symbol: str
    side: str
    action: str
    reason: str
    priority: int
    entry: float
    stop_loss: float
    take_profit: float
    latest_price: float
    r_multiple: float
    suggested_stop_loss: float | None = None
    close_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExitManager:
    """Decides how open trades should be managed after entry."""

    def __init__(self, config: DemoAutoConfig) -> None:
        self.config = config

    def evaluate_position(
        self,
        position: dict[str, Any],
        candles: list[Candle],
        now: datetime | None = None,
    ) -> ExitDecision:
        if not candles:
            return self._decision(position, "hold", "No candles available for exit review", 20, 0.0, 0.0)

        latest = candles[-1].close
        side = str(position.get("side", "")).lower()
        entry = float(position["entry"])
        stop_loss = float(position["stop_loss"])
        take_profit = float(position["take_profit"])
        risk = abs(entry - stop_loss)
        if risk <= 0:
            return self._decision(position, "close", "Invalid stop distance; close to prevent unmanaged risk", 95, latest, 0.0)

        r_multiple = self._r_multiple(side, entry, risk, latest)
        latest_candle = candles[-1]
        if self._stop_touched(side, latest_candle, stop_loss):
            return self._decision(position, "close", "Stop-loss was touched", 100, stop_loss, -1.0)
        if self._target_touched(side, latest_candle, take_profit):
            target_r = self._r_multiple(side, entry, risk, take_profit)
            return self._decision(position, "close", "Take-profit was touched", 100, take_profit, target_r)

        max_age = self._max_age_reason(position, now or datetime.now(timezone.utc))
        if max_age:
            return self._decision(position, "close", max_age, 80, latest, r_multiple)

        invalidation = self._invalidation_reason(side, candles)
        if invalidation and r_multiple < 0.25:
            return self._decision(position, "close", invalidation, 75, latest, r_multiple)

        if r_multiple >= self.config.exit_trail_at_r:
            trail = self._trail_stop(side, candles, entry, stop_loss)
            if trail and self._improves_stop(side, stop_loss, trail):
                return self._decision(
                    position,
                    "trail_stop",
                    f"Trade is {r_multiple:.2f}R in profit; trail stop behind recent structure",
                    65,
                    latest,
                    r_multiple,
                    suggested_stop_loss=trail,
                )

        if r_multiple >= self.config.exit_breakeven_at_r and self._improves_stop(side, stop_loss, entry):
            return self._decision(
                position,
                "move_to_breakeven",
                f"Trade reached {r_multiple:.2f}R; protect capital at breakeven",
                60,
                latest,
                r_multiple,
                suggested_stop_loss=entry,
            )

        return self._decision(position, "hold", f"Hold while thesis remains valid at {r_multiple:.2f}R", 10, latest, r_multiple)

    def _decision(
        self,
        position: dict[str, Any],
        action: str,
        reason: str,
        priority: int,
        price: float,
        r_multiple: float,
        suggested_stop_loss: float | None = None,
    ) -> ExitDecision:
        return ExitDecision(
            position_id=str(position.get("id") or position.get("ticket") or ""),
            symbol=str(position.get("symbol") or ""),
            side=str(position.get("side") or "").lower(),
            action=action,
            reason=reason,
            priority=priority,
            entry=float(position.get("entry") or 0.0),
            stop_loss=float(position.get("stop_loss") or 0.0),
            take_profit=float(position.get("take_profit") or 0.0),
            latest_price=float(price),
            r_multiple=round(r_multiple, 4),
            suggested_stop_loss=suggested_stop_loss,
            close_price=float(price) if action == "close" else None,
        )

    def _r_multiple(self, side: str, entry: float, risk: float, price: float) -> float:
        direction = 1 if side == "buy" else -1
        return (price - entry) * direction / risk

    def _stop_touched(self, side: str, candle: Candle, stop_loss: float) -> bool:
        return candle.low <= stop_loss if side == "buy" else candle.high >= stop_loss

    def _target_touched(self, side: str, candle: Candle, take_profit: float) -> bool:
        return candle.high >= take_profit if side == "buy" else candle.low <= take_profit

    def _max_age_reason(self, position: dict[str, Any], now: datetime) -> str | None:
        opened_at = self._parse_time(position.get("opened_at"))
        if not opened_at:
            return None
        age_minutes = (now - opened_at).total_seconds() / 60
        if age_minutes >= self.config.exit_max_trade_minutes:
            return f"Max trade time reached ({self.config.exit_max_trade_minutes} minutes)"
        return None

    def _invalidation_reason(self, side: str, candles: list[Candle]) -> str | None:
        recent = candles[-12:]
        if len(recent) < 6:
            return None
        closes = [candle.close for candle in recent]
        ema = self._ema(closes, min(8, len(closes)))
        lower_highs = recent[-1].high < recent[-4].high and recent[-3].high < recent[-6].high
        higher_lows = recent[-1].low > recent[-4].low and recent[-3].low > recent[-6].low
        if side == "buy" and closes[-1] < ema and lower_highs:
            return "Buy thesis invalidated: bearish closes under short EMA"
        if side == "sell" and closes[-1] > ema and higher_lows:
            return "Sell thesis invalidated: bullish closes over short EMA"
        return None

    def _trail_stop(self, side: str, candles: list[Candle], entry: float, stop_loss: float) -> float | None:
        recent = candles[-8:]
        if len(recent) < 3:
            return None
        if side == "buy":
            return round(max(entry, min(candle.low for candle in recent[-5:])), 6)
        return round(min(entry, max(candle.high for candle in recent[-5:])), 6)

    def _improves_stop(self, side: str, current: float, proposed: float) -> bool:
        return proposed > current if side == "buy" else proposed < current

    def _ema(self, values: list[float], period: int) -> float:
        multiplier = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
        return ema

    def _parse_time(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
