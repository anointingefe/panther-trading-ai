from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
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
            raise RuntimeError(f"MT5 positions_get failed: {self.mt5.last_error()}")
        return len(positions)

    def open_positions(self) -> list[dict]:
        positions = self.mt5.positions_get()
        if positions is None:
            raise RuntimeError(f"MT5 positions_get failed: {self.mt5.last_error()}")
        results: list[dict] = []
        for position in positions:
            if int(getattr(position, "magic", 0) or 0) != PANTHER_MAGIC:
                continue
            side = "buy" if getattr(position, "type", None) == self.mt5.POSITION_TYPE_BUY else "sell"
            results.append(
                {
                    "id": str(getattr(position, "ticket", "")),
                    "ticket": str(getattr(position, "ticket", "")),
                    "symbol": str(getattr(position, "symbol", "")),
                    "side": side,
                    "volume": float(getattr(position, "volume", 0.0) or 0.0),
                    "entry": float(getattr(position, "price_open", 0.0) or 0.0),
                    "stop_loss": float(getattr(position, "sl", 0.0) or 0.0),
                    "take_profit": float(getattr(position, "tp", 0.0) or 0.0),
                    "status": "open",
                    "opened_at": datetime.fromtimestamp(int(getattr(position, "time", 0) or 0), tz=timezone.utc).isoformat(),
                    "metadata": {"source": "mt5", "comment": str(getattr(position, "comment", ""))},
                }
            )
        return results

    def place_order(self, request: OrderRequest) -> OrderResult:
        if request.side not in {SignalSide.BUY, SignalSide.SELL}:
            return OrderResult(OrderStatus.REJECTED, "Order side must be buy or sell")
        values = (request.volume, request.entry, request.stop_loss, request.take_profit)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            return OrderResult(OrderStatus.REJECTED, "Order values must be finite and positive")
        if not self._valid_bracket(request.side, request.entry, request.stop_loss, request.take_profit):
            return OrderResult(OrderStatus.REJECTED, "Invalid stop-loss/take-profit direction")
        tick = self.mt5.symbol_info_tick(request.symbol)
        if tick is None:
            return OrderResult(OrderStatus.REJECTED, f"No tick available for {request.symbol}")

        order_type = self.mt5.ORDER_TYPE_BUY if request.side == SignalSide.BUY else self.mt5.ORDER_TYPE_SELL
        if not all(math.isfinite(value) and value > 0 for value in (tick.ask, tick.bid)) or tick.ask < tick.bid:
            return OrderResult(OrderStatus.REJECTED, "Invalid market quote")
        price = tick.ask if request.side == SignalSide.BUY else tick.bid
        if not self._valid_bracket(request.side, price, request.stop_loss, request.take_profit):
            return OrderResult(OrderStatus.REJECTED, "Market price moved outside the planned stop/target")
        volume = self._normalized_volume(request.symbol, request.volume)
        if volume <= 0:
            return OrderResult(OrderStatus.REJECTED, "Requested volume is below broker minimum or symbol limits are unavailable")
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
                return OrderResult(
                    OrderStatus.REJECTED,
                    f"MT5 submission outcome unknown; reconcile broker history before retrying: {self.mt5.last_error()}",
                )
            if result.retcode in self._accepted_retcodes():
                message = str(result.comment)
                if volume != request.volume:
                    message = f"{message} (volume adjusted {request.volume:g}->{volume:g})"
                return OrderResult(OrderStatus.ACCEPTED, message, broker_order_id=str(result.order))
            message = str(getattr(result, "comment", "order rejected"))
            rejected.append(message)
            if not self._is_filling_mode_rejection(result):
                return OrderResult(OrderStatus.REJECTED, f"MT5 rejected order: {message}")
        return OrderResult(OrderStatus.REJECTED, f"MT5 rejected order: {'; '.join(rejected)}")

    def close_position(self, position_id: str, reason: str = "exit_manager") -> OrderResult:
        positions = self.mt5.positions_get(ticket=int(position_id))
        if not positions:
            return OrderResult(OrderStatus.REJECTED, f"MT5 position not found: {position_id}")
        position = positions[0]
        if int(getattr(position, "magic", 0) or 0) != PANTHER_MAGIC:
            return OrderResult(OrderStatus.REJECTED, "Refusing to close a non-PANTHER position")
        symbol = str(getattr(position, "symbol", ""))
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(OrderStatus.REJECTED, f"No tick available for {symbol}")

        position_type = getattr(position, "type", None)
        if position_type == self.mt5.POSITION_TYPE_BUY:
            order_type = self.mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = self.mt5.ORDER_TYPE_BUY
            price = tick.ask
        payload = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "position": int(position_id),
            "symbol": symbol,
            "volume": float(getattr(position, "volume", 0.0) or 0.0),
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": PANTHER_MAGIC,
            "comment": f"PANTHER close: {reason}"[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
        }
        rejected: list[str] = []
        for filling_mode in self._order_filling_modes():
            result = self.mt5.order_send({**payload, "type_filling": filling_mode})
            if result is None:
                return OrderResult(
                    OrderStatus.REJECTED,
                    f"MT5 close outcome unknown; reconcile the position before retrying: {self.mt5.last_error()}",
                )
            if result.retcode in self._accepted_retcodes():
                return OrderResult(OrderStatus.ACCEPTED, str(result.comment), broker_order_id=str(result.order))
            message = str(getattr(result, "comment", "close rejected"))
            rejected.append(message)
            if not self._is_filling_mode_rejection(result):
                return OrderResult(OrderStatus.REJECTED, f"MT5 rejected close: {message}")
        return OrderResult(OrderStatus.REJECTED, f"MT5 rejected close: {'; '.join(rejected)}")

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
        orders = self.mt5.history_orders_get(since, now)
        if orders is None:
            raise RuntimeError(f"MT5 history_orders_get failed: {self.mt5.last_error()}")
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
        if demo is not None and trade_mode == demo:
            return "demo"
        if contest is not None and trade_mode == contest:
            return "contest"
        if real is not None and trade_mode == real:
            return "real"
        return "unknown"

    def _order_filling_modes(self) -> tuple[int, ...]:
        candidates = (
            getattr(self.mt5, "ORDER_FILLING_FOK", None),
            getattr(self.mt5, "ORDER_FILLING_IOC", None),
            getattr(self.mt5, "ORDER_FILLING_RETURN", None),
        )
        return tuple(mode for mode in candidates if mode is not None)

    @staticmethod
    def _valid_bracket(side: SignalSide, entry: float, stop_loss: float, take_profit: float) -> bool:
        if side == SignalSide.BUY:
            return stop_loss < entry < take_profit
        return take_profit < entry < stop_loss

    def _accepted_retcodes(self) -> set[int]:
        # Placed and partially filled requests must not be submitted again as failures.
        return {
            code for name in ("TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL", "TRADE_RETCODE_PLACED")
            if (code := getattr(self.mt5, name, None)) is not None
        }

    def _normalized_volume(self, symbol: str, requested: float) -> float:
        return self._floored_volume(symbol, requested)

    def calculate_position_volume(
        self,
        symbol: str,
        side: SignalSide,
        entry: float,
        stop_loss: float,
        risk_amount: float,
        max_volume: float,
    ) -> float:
        if side not in {SignalSide.BUY, SignalSide.SELL}:
            return 0.0
        if any(not math.isfinite(value) or value <= 0 for value in (entry, stop_loss, risk_amount, max_volume)):
            return 0.0
        if (side == SignalSide.BUY and stop_loss >= entry) or (side == SignalSide.SELL and stop_loss <= entry):
            return 0.0
        risk_per_lot = self._risk_per_lot(symbol, side, entry, stop_loss)
        if not math.isfinite(risk_per_lot) or risk_per_lot <= 0:
            return 0.0
        raw_volume = float(Decimal(str(risk_amount)) / Decimal(str(risk_per_lot)))
        return self._floored_volume(symbol, min(raw_volume, max_volume))

    def _risk_per_lot(self, symbol: str, side: SignalSide, entry: float, stop_loss: float) -> float:
        order_type = self.mt5.ORDER_TYPE_BUY if side == SignalSide.BUY else self.mt5.ORDER_TYPE_SELL
        calculated = self.mt5.order_calc_profit(order_type, symbol, 1.0, entry, stop_loss)
        if calculated is None:
            return 0.0
        value = float(calculated)
        return -value if math.isfinite(value) and value < 0 else 0.0

    def _floored_volume(self, symbol: str, requested: float) -> float:
        if not math.isfinite(requested) or requested <= 0:
            return 0.0
        symbol_info = self.mt5.symbol_info(symbol)
        if symbol_info is None:
            return 0.0
        minimum = float(getattr(symbol_info, "volume_min", 0.0) or 0.0)
        maximum = float(getattr(symbol_info, "volume_max", 0.0) or 0.0)
        step = float(getattr(symbol_info, "volume_step", 0.0) or 0.0)
        if any(not math.isfinite(value) or value <= 0 for value in (minimum, maximum, step)):
            return 0.0
        if maximum < minimum or requested < minimum:
            return 0.0
        lower, increment = Decimal(str(minimum)), Decimal(str(step))
        limit = min(Decimal(str(requested)), Decimal(str(maximum)))
        steps = ((limit - lower) / increment).to_integral_value(rounding=ROUND_FLOOR)
        volume = float(lower + steps * increment)
        return volume if 0 < volume <= min(requested, maximum) else 0.0

    def _is_filling_mode_rejection(self, result: Any) -> bool:
        retcode = getattr(result, "retcode", None)
        invalid_fill = getattr(self.mt5, "TRADE_RETCODE_INVALID_FILL", None)
        return invalid_fill is not None and retcode == invalid_fill

    def _closed_trade_from_deals(
        self, position_id: str, deals: list[Any], order_by_ticket: dict[str, Any]
    ) -> ClosedTrade | None:
        entry_codes = {getattr(self.mt5, "DEAL_ENTRY_IN", 0)}
        exit_codes = {getattr(self.mt5, "DEAL_ENTRY_OUT", 1), getattr(self.mt5, "DEAL_ENTRY_OUT_BY", 3)}
        sorted_deals = sorted(deals, key=lambda deal: getattr(deal, "time", 0))
        entry_deal = next((deal for deal in sorted_deals if getattr(deal, "entry", None) in entry_codes), None)
        exit_deal = next((deal for deal in reversed(sorted_deals) if getattr(deal, "entry", None) in exit_codes), None)
        if entry_deal is None or exit_deal is None:
            return None

        # Partial exits are not completed trades. Reversals and scale-ins need
        # separate accounting; do not fabricate a single entry/risk for them.
        entries = [deal for deal in sorted_deals if getattr(deal, "entry", None) in entry_codes]
        plain_exit_codes = {
            getattr(self.mt5, "DEAL_ENTRY_OUT", 1),
            getattr(self.mt5, "DEAL_ENTRY_OUT_BY", 3),
        }
        if len(entries) != 1 or any(
            getattr(deal, "entry", None) not in entry_codes | plain_exit_codes
            for deal in sorted_deals
        ):
            return None
        exits = [deal for deal in sorted_deals if getattr(deal, "entry", None) in plain_exit_codes]
        volumes = [float(getattr(deal, "volume", 0.0)) for deal in [entry_deal, *exits]]
        prices = [float(getattr(deal, "price", 0.0)) for deal in [entry_deal, *exits]]
        if not exits or any(not math.isfinite(value) or value <= 0 for value in volumes + prices):
            return None
        entry_volume, exit_volume = volumes[0], math.fsum(volumes[1:])
        if not math.isclose(entry_volume, exit_volume, rel_tol=1e-9, abs_tol=1e-12):
            return None
        exit_deal = exits[-1]
        close_price = math.fsum(
            float(deal.price) * float(deal.volume) for deal in exits
        ) / exit_volume

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
        if not math.isfinite(pnl):
            return None
        return ClosedTrade(
            external_id=position_id,
            source="mt5",
            symbol=str(getattr(entry_deal, "symbol")),
            side=side,
            volume=entry_volume,
            entry=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            close_price=close_price,
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
            if math.isfinite(number) and number > 0:
                return number
        return None
