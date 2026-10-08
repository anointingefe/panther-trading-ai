from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from panther_trading.brokers.base import Broker
from panther_trading.models import BrokerStatus, Candle, ClosedTrade, OrderRequest, OrderResult, OrderStatus, SignalSide


PANTHER_MAGIC = 26001007


class MT5Broker(Broker):
    """MetaTrader 5 adapter.

    The MetaTrader5 Python package only works where the MT5 terminal is
    installed and logged in, usually Windows or a Windows VPS.
    """

    def __init__(self) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError(
                "MetaTrader5 package is not installed. Use the simulated broker "
                "locally, then install/configure MT5 on the trading machine."
            ) from exc

        self.mt5 = mt5
        if not self.mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {self.mt5.last_error()}")

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        rates = self.mt5.copy_rates_from_pos(symbol, self._timeframe(timeframe), 0, count)
        if rates is None:
            raise RuntimeError(f"MT5 candle fetch failed: {self.mt5.last_error()}")

        candles: list[Candle] = []
        for row in rates:
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(int(row["time"]), tz=timezone.utc),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["tick_volume"]),
                )
            )
        return candles

    def get_status(self) -> BrokerStatus:
        account = self.mt5.account_info()
        terminal = self.mt5.terminal_info()
        symbols_total = self.mt5.symbols_total() or 0
        connected = bool(terminal and terminal.connected)
        if account is None:
            return BrokerStatus(
                name="MetaTrader 5",
                connected=connected,
                mode="unknown",
                account_login=None,
                account_server=None,
                balance=None,
                equity=None,
                open_positions=self.count_open_positions(),
                symbols_total=symbols_total,
                message="MT5 terminal connected, but account details are unavailable",
            )

        trade_mode = getattr(account, "trade_mode", None)
        return BrokerStatus(
            name="MetaTrader 5",
            connected=connected,
            mode=self._account_mode(trade_mode),
            account_login=str(account.login),
            account_server=str(account.server),
            balance=float(account.balance),
            equity=float(account.equity),
            open_positions=self.count_open_positions(),
            symbols_total=symbols_total,
            message="MT5 broker connection active",
        )

    def list_symbols(self) -> list[str]:
        symbols = self.mt5.symbols_get()
        if symbols is None:
            raise RuntimeError(f"MT5 symbols_get failed: {self.mt5.last_error()}")
        return [str(symbol.name) for symbol in symbols if getattr(symbol, "visible", True)]

    def count_open_positions(self, symbol: str | None = None) -> int:
        positions = self.mt5.positions_get(symbol=symbol) if symbol else self.mt5.positions_get()
        if positions is None:
            return 0
        return len(positions)

    def place_order(self, request: OrderRequest) -> OrderResult:
        tick = self.mt5.symbol_info_tick(request.symbol)
        if tick is None:
            return OrderResult(OrderStatus.REJECTED, f"No tick available for {request.symbol}")

        order_type = self.mt5.ORDER_TYPE_BUY if request.side == SignalSide.BUY else self.mt5.ORDER_TYPE_SELL
        price = tick.ask if request.side == SignalSide.BUY else tick.bid
        volume = self._normalized_volume(request.symbol, request.volume)
        payload = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": request.stop_loss,
            "tp": request.take_profit,
            "deviation": 20,
            "magic": PANTHER_MAGIC,
            "comment": request.comment,
            "type_time": self.mt5.ORDER_TIME_GTC,
        }
        rejected: list[str] = []
        for filling_mode in self._order_filling_modes():
            result = self.mt5.order_send({**payload, "type_filling": filling_mode})
            if result is None:
                rejected.append(f"order_send failed: {self.mt5.last_error()}")
                continue
            if result.retcode == self.mt5.TRADE_RETCODE_DONE:
                message = str(result.comment)
                if volume != request.volume:
                    message = f"{message} (volume adjusted {request.volume:g}->{volume:g})"
                return OrderResult(OrderStatus.ACCEPTED, message, broker_order_id=str(result.order))
            message = str(getattr(result, "comment", "order rejected"))
            rejected.append(message)
            if not self._is_filling_mode_rejection(result):
                return OrderResult(OrderStatus.REJECTED, f"MT5 rejected order: {message}")
        return OrderResult(OrderStatus.REJECTED, f"MT5 rejected order: {'; '.join(rejected)}")

    def get_closed_trades(self, days: int = 30) -> list[ClosedTrade]:
        """Import auditable PANTHER MT5 history for demo validation.

        Only trades with the PANTHER magic number and enough order metadata to
        reconstruct entry, stop-loss, take-profit, close price, and realized PnL
        are returned. Missing stop-loss data is skipped because it cannot be
        converted into an honest R-multiple.
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        deals = self.mt5.history_deals_get(since, now)
        if deals is None:
            raise RuntimeError(f"MT5 history_deals_get failed: {self.mt5.last_error()}")
        orders = self.mt5.history_orders_get(since, now) or ()
        order_by_ticket = {str(getattr(order, "ticket", "")): order for order in orders}

        grouped: dict[str, list[Any]] = {}
        for deal in deals:
            if int(getattr(deal, "magic", 0) or 0) != PANTHER_MAGIC:
                continue
            position_id = str(getattr(deal, "position_id", "") or getattr(deal, "order", ""))
            grouped.setdefault(position_id, []).append(deal)

        closed: list[ClosedTrade] = []
        for position_id, position_deals in grouped.items():
            imported = self._closed_trade_from_deals(position_id, position_deals, order_by_ticket)
            if imported is not None:
                closed.append(imported)
        return sorted(closed, key=lambda trade: trade.closed_at)

    def _timeframe(self, timeframe: str) -> int:
        mapping = {
            "M1": self.mt5.TIMEFRAME_M1,
            "M5": self.mt5.TIMEFRAME_M5,
            "M15": self.mt5.TIMEFRAME_M15,
            "M30": self.mt5.TIMEFRAME_M30,
            "H1": self.mt5.TIMEFRAME_H1,
            "H4": self.mt5.TIMEFRAME_H4,
            "D1": self.mt5.TIMEFRAME_D1,
        }
        try:
            return mapping[timeframe.upper()]
        except KeyError as exc:
            raise ValueError(f"Unsupported timeframe: {timeframe}") from exc

    def _account_mode(self, trade_mode: int | None) -> str:
        demo = getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        contest = getattr(self.mt5, "ACCOUNT_TRADE_MODE_CONTEST", None)
        real = getattr(self.mt5, "ACCOUNT_TRADE_MODE_REAL", None)
        if trade_mode == demo:
            return "demo"
        if trade_mode == contest:
            return "contest"
        if trade_mode == real:
            return "real"
        return "unknown"

    def _order_filling_modes(self) -> tuple[int, ...]:
        candidates = (
            getattr(self.mt5, "ORDER_FILLING_FOK", None),
            getattr(self.mt5, "ORDER_FILLING_IOC", None),
            getattr(self.mt5, "ORDER_FILLING_RETURN", None),
        )
        return tuple(mode for mode in candidates if mode is not None)

    def _normalized_volume(self, symbol: str, requested: float) -> float:
        symbol_info = self.mt5.symbol_info(symbol)
        if symbol_info is None:
            return requested

        minimum = float(getattr(symbol_info, "volume_min", 0.0) or 0.0)
        maximum = float(getattr(symbol_info, "volume_max", 0.0) or 0.0)
        step = float(getattr(symbol_info, "volume_step", 0.0) or 0.0)
        volume = max(requested, minimum) if minimum > 0 else requested

        if step > 0:
            steps = math.ceil((volume - minimum) / step) if minimum > 0 else math.ceil(volume / step)
            volume = (minimum + steps * step) if minimum > 0 else steps * step
            precision = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
            volume = round(volume, precision)
        if maximum > 0:
            volume = min(volume, maximum)
        return volume

    def _is_filling_mode_rejection(self, result: Any) -> bool:
        retcode = getattr(result, "retcode", None)
        invalid_fill = getattr(self.mt5, "TRADE_RETCODE_INVALID_FILL", None)
        comment = str(getattr(result, "comment", "")).lower()
        return retcode == invalid_fill or "filling" in comment

    def _closed_trade_from_deals(
        self, position_id: str, deals: list[Any], order_by_ticket: dict[str, Any]
    ) -> ClosedTrade | None:
        entry_codes = {getattr(self.mt5, "DEAL_ENTRY_IN", 0)}
        exit_codes = {getattr(self.mt5, "DEAL_ENTRY_OUT", 1), getattr(self.mt5, "DEAL_ENTRY_INOUT", 2)}
        sorted_deals = sorted(deals, key=lambda deal: getattr(deal, "time", 0))
        entry_deal = next((deal for deal in sorted_deals if getattr(deal, "entry", None) in entry_codes), None)
        exit_deal = next((deal for deal in reversed(sorted_deals) if getattr(deal, "entry", None) in exit_codes), None)
        if entry_deal is None or exit_deal is None:
            return None

        entry_order = order_by_ticket.get(str(getattr(entry_deal, "order", "")))
        exit_order = order_by_ticket.get(str(getattr(exit_deal, "order", "")))
        stop_loss = self._first_number(getattr(entry_order, "sl", None), getattr(exit_order, "sl", None))
        take_profit = self._first_number(getattr(entry_order, "tp", None), getattr(exit_order, "tp", None))
        if stop_loss is None or take_profit is None:
            return None

        side = self._deal_side(entry_deal)
        if side is None:
            return None
        entry_price = float(getattr(entry_deal, "price"))
        if side == SignalSide.BUY and stop_loss >= entry_price:
            return None
        if side == SignalSide.SELL and stop_loss <= entry_price:
            return None

        pnl = sum(
            float(getattr(deal, field, 0.0) or 0.0)
            for deal in sorted_deals
            for field in ("profit", "swap", "commission", "fee")
        )
        return ClosedTrade(
            external_id=position_id,
            source="mt5",
            symbol=str(getattr(entry_deal, "symbol")),
            side=side,
            volume=float(min(float(getattr(entry_deal, "volume", 0.0)), float(getattr(exit_deal, "volume", 0.0)))),
            entry=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            close_price=float(getattr(exit_deal, "price")),
            pnl=round(pnl, 6),
            opened_at=datetime.fromtimestamp(int(getattr(entry_deal, "time")), tz=timezone.utc),
            closed_at=datetime.fromtimestamp(int(getattr(exit_deal, "time")), tz=timezone.utc),
            broker_order_id=str(getattr(exit_deal, "order", "")),
            comment=str(getattr(entry_deal, "comment", "") or getattr(exit_deal, "comment", "")),
        )

    def _deal_side(self, deal: Any) -> SignalSide | None:
        deal_type = getattr(deal, "type", None)
        if deal_type == getattr(self.mt5, "DEAL_TYPE_BUY", None):
            return SignalSide.BUY
        if deal_type == getattr(self.mt5, "DEAL_TYPE_SELL", None):
            return SignalSide.SELL
        return None

    def _first_number(self, *values: Any) -> float | None:
        for value in values:
            if value is None:
                continue
            number = float(value)
            if number > 0:
                return number
        return None
