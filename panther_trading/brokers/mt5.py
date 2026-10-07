from __future__ import annotations

from datetime import datetime, timezone

from panther_trading.brokers.base import Broker
from panther_trading.models import BrokerStatus, Candle, OrderRequest, OrderResult, OrderStatus, SignalSide


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
        result = self.mt5.order_send(
            {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": request.symbol,
                "volume": request.volume,
                "type": order_type,
                "price": price,
                "sl": request.stop_loss,
                "tp": request.take_profit,
                "deviation": 20,
                "magic": 26001007,
                "comment": request.comment,
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            }
        )
        if result is None:
            return OrderResult(OrderStatus.REJECTED, f"MT5 order_send failed: {self.mt5.last_error()}")
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return OrderResult(OrderStatus.REJECTED, f"MT5 rejected order: {result.comment}")
        return OrderResult(OrderStatus.ACCEPTED, result.comment, broker_order_id=str(result.order))

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
