from __future__ import annotations

from panther_trading.brokers.base import Broker
from panther_trading.config import ExecutionConfig
from panther_trading.models import OrderRequest, OrderResult, OrderStatus, TradeSignal
from panther_trading.risk.manager import RiskManager


class ExecutionEngine:
    def __init__(self, broker: Broker, risk_manager: RiskManager, config: ExecutionConfig) -> None:
        self.broker = broker
        self.risk_manager = risk_manager
        self.config = config

    def execute(self, signal: TradeSignal) -> OrderResult:
        open_positions = self.broker.count_open_positions(signal.symbol)
        decision = self.risk_manager.evaluate(signal, open_positions=open_positions)
        if not decision.allowed:
            return OrderResult(OrderStatus.REJECTED, decision.reason)

        if self.config.allow_live_trading:
            comment = "PANTHER live trade"
        else:
            comment = "PANTHER paper trade"

        request = OrderRequest(
            symbol=signal.symbol,
            side=signal.side,
            volume=self.config.default_volume,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            comment=comment,
        )
        return self.broker.place_order(request)
