from __future__ import annotations

from dataclasses import dataclass

from panther_trading.models import Candle, SignalSide, TradeSignal


@dataclass(frozen=True)
class BacktestResult:
    trades: int
    wins: int
    losses: int
    net_r: float


def run_naive_backtest(signals: list[TradeSignal], future_candles: list[Candle]) -> BacktestResult:
    wins = 0
    losses = 0
    net_r = 0.0

    for signal in signals:
        if signal.side == SignalSide.HOLD:
            continue
        risk = abs(signal.entry - signal.stop_loss)
        if risk == 0:
            continue

        for candle in future_candles:
            if signal.side == SignalSide.BUY:
                if candle.low <= signal.stop_loss:
                    losses += 1
                    net_r -= 1
                    break
                if candle.high >= signal.take_profit:
                    wins += 1
                    net_r += abs(signal.take_profit - signal.entry) / risk
                    break
            else:
                if candle.high >= signal.stop_loss:
                    losses += 1
                    net_r -= 1
                    break
                if candle.low <= signal.take_profit:
                    wins += 1
                    net_r += abs(signal.entry - signal.take_profit) / risk
                    break

    return BacktestResult(trades=wins + losses, wins=wins, losses=losses, net_r=round(net_r, 2))
