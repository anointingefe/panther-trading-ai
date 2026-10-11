from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any

from panther_trading.brokers.base import Broker
from panther_trading.config import StrategyConfig
from panther_trading.data import StaticSentimentCollector
from panther_trading.models import Candle, SignalSide, TradeSignal
from panther_trading.strategies import SmaSentimentStrategy


@dataclass(frozen=True)
class StrategyCandidate:
    id: str
    name: str
    description: str
    config: StrategyConfig
    minimum_trades: int = 8
    minimum_profit_factor: float = 1.15
    minimum_win_rate: float = 0.38
    minimum_average_r: float = 0.05
    minimum_quality_score: float = 65.0
    maximum_drawdown_r: float = 6.0


@dataclass(frozen=True)
class StrategyScorecard:
    id: str
    name: str
    description: str
    status: str
    market_condition: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_r: float
    gross_net_r: float
    execution_cost_r: float
    average_r: float
    profit_factor: float
    max_drawdown_r: float
    out_of_sample_trades: int
    out_of_sample_net_r: float
    average_confidence: float
    precision_grade: str
    quality_score: float
    evidence_level: str
    reasons_not_to_enter: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyResearchLab:
    def __init__(
        self,
        broker: Broker,
        sentiment_collector: StaticSentimentCollector | None = None,
        spread_cost_r: float = 0.05,
        slippage_cost_r: float = 0.03,
        out_of_sample_ratio: float = 0.3,
    ) -> None:
        self.broker = broker
        self.sentiment_collector = sentiment_collector or StaticSentimentCollector()
        self.spread_cost_r = spread_cost_r
        self.slippage_cost_r = slippage_cost_r
        self.out_of_sample_ratio = out_of_sample_ratio

    def run(self, symbol: str, timeframe: str = "M15", candles: int = 220) -> dict[str, Any]:
        market_candles = self.broker.get_candles(symbol, timeframe, candles)
        condition = self._classify_market(market_candles)
        scorecards = [
            self._score_candidate(candidate, symbol, market_candles, condition)
            for candidate in self._candidates()
        ]
        scorecards.sort(
            key=lambda item: (
                item.status == "approved",
                item.quality_score,
                item.profit_factor,
                item.net_r,
            ),
            reverse=True,
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "marketCondition": condition,
            "precisionProfile": {
                "spreadCostR": self.spread_cost_r,
                "slippageCostR": self.slippage_cost_r,
                "outOfSampleRatio": self.out_of_sample_ratio,
                "rule": "Strategies must survive execution costs and recent out-of-sample scoring.",
            },
            "scorecards": [scorecard.to_dict() for scorecard in scorecards],
            "summary": self._summary(scorecards),
        }

    def _candidates(self) -> list[StrategyCandidate]:
        return [
            StrategyCandidate(
                id="trend_sma_sentiment",
                name="Trend SMA + Sentiment",
                description="Balanced trend-following strategy with sentiment confirmation.",
                config=StrategyConfig(fast_sma=10, slow_sma=30, sentiment_weight=0.25),
            ),
            StrategyCandidate(
                id="fast_momentum",
                name="Fast Momentum",
                description="Faster SMA response for active markets and early trend shifts.",
                config=StrategyConfig(fast_sma=6, slow_sma=18, sentiment_weight=0.18),
                minimum_profit_factor=1.1,
            ),
            StrategyCandidate(
                id="cautious_swing",
                name="Cautious Swing",
                description="Slower signal that waits for broader confirmation before entry.",
                config=StrategyConfig(fast_sma=14, slow_sma=42, sentiment_weight=0.15),
                maximum_drawdown_r=4.5,
            ),
        ]

    def _score_candidate(
        self,
        candidate: StrategyCandidate,
        symbol: str,
        candles: list[Candle],
        market_condition: str,
    ) -> StrategyScorecard:
        strategy = SmaSentimentStrategy(candidate.config)
        sentiment = self.sentiment_collector.collect(symbol)
        horizon = 12
        step = 4
        trade_results: list[float] = []
        gross_results: list[float] = []
        confidences: list[float] = []
        execution_cost = self.spread_cost_r + self.slippage_cost_r

        start = candidate.config.slow_sma
        stop = max(start, len(candles) - horizon)
        for index in range(start, stop, step):
            signal = strategy.generate(symbol, candles[:index], sentiment)
            if signal.side == SignalSide.HOLD:
                continue
            outcome = self._score_trade(signal, candles[index : index + horizon])
            if outcome is None:
                continue
            gross_results.append(outcome)
            trade_results.append(round(outcome - execution_cost, 4))
            confidences.append(signal.confidence)

        wins = len([result for result in trade_results if result > 0])
        losses = len([result for result in trade_results if result < 0])
        net_r = round(sum(trade_results), 2)
        gross_net_r = round(sum(gross_results), 2)
        positive_r = sum(result for result in trade_results if result > 0)
        negative_r = abs(sum(result for result in trade_results if result < 0))
        trades = wins + losses
        out_of_sample = self._out_of_sample_results(trade_results)
        out_of_sample_net_r = round(sum(out_of_sample), 2)
        win_rate = round(wins / trades, 4) if trades else 0.0
        average_r = round(net_r / trades, 4) if trades else 0.0
        profit_factor = round(positive_r / negative_r, 4) if negative_r else round(positive_r, 4)
        max_drawdown = self._max_drawdown(trade_results)
        average_confidence = round(fmean(confidences), 4) if confidences else 0.0
        quality_score = self._quality_score(
            trades=trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            net_r=net_r,
            average_r=average_r,
            out_of_sample_net_r=out_of_sample_net_r,
        )
        evidence_level = self._evidence_level(trades, out_of_sample, quality_score)
        reasons_not_to_enter = self._reasons_not_to_enter(
            candidate=candidate,
            trades=trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            net_r=net_r,
            average_r=average_r,
            out_of_sample_net_r=out_of_sample_net_r,
            quality_score=quality_score,
        )
        precision_grade = self._precision_grade(
            trades,
            profit_factor,
            max_drawdown,
            net_r,
            average_r,
            out_of_sample_net_r,
            quality_score,
        )
        status = self._status(
            candidate,
            trades,
            win_rate,
            profit_factor,
            max_drawdown,
            net_r,
            average_r,
            out_of_sample_net_r,
            quality_score,
        )
        notes = self._notes(
            candidate,
            trades,
            win_rate,
            profit_factor,
            max_drawdown,
            net_r,
            average_r,
            out_of_sample_net_r,
            quality_score,
            market_condition,
            reasons_not_to_enter,
        )

        return StrategyScorecard(
            id=candidate.id,
            name=candidate.name,
            description=candidate.description,
            status=status,
            market_condition=market_condition,
            trades=trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            net_r=net_r,
            gross_net_r=gross_net_r,
            execution_cost_r=round(execution_cost, 4),
            average_r=average_r,
            profit_factor=profit_factor,
            max_drawdown_r=max_drawdown,
            out_of_sample_trades=len(out_of_sample),
            out_of_sample_net_r=out_of_sample_net_r,
            average_confidence=average_confidence,
            precision_grade=precision_grade,
            quality_score=quality_score,
            evidence_level=evidence_level,
            reasons_not_to_enter=reasons_not_to_enter,
            notes=notes,
        )

    def _score_trade(self, signal: TradeSignal, future_candles: list[Candle]) -> float | None:
        risk = abs(signal.entry - signal.stop_loss)
        if risk <= 0:
            return None

        reward = abs(signal.take_profit - signal.entry) / risk
        for candle in future_candles:
            if signal.side == SignalSide.BUY:
                if candle.low <= signal.stop_loss:
                    return -1.0
                if candle.high >= signal.take_profit:
                    return round(reward, 4)
            if signal.side == SignalSide.SELL:
                if candle.high >= signal.stop_loss:
                    return -1.0
                if candle.low <= signal.take_profit:
                    return round(reward, 4)
        final_close = future_candles[-1].close if future_candles else signal.entry
        direction = 1 if signal.side == SignalSide.BUY else -1
        return round(((final_close - signal.entry) * direction) / risk, 4)

    def _classify_market(self, candles: list[Candle]) -> str:
        if len(candles) < 40:
            return "insufficient_data"
        closes = [candle.close for candle in candles]
        short = fmean(closes[-12:])
        long = fmean(closes[-40:])
        average_range = fmean(candle.high - candle.low for candle in candles[-20:])
        range_pct = average_range / closes[-1]
        slope = (short - long) / closes[-1]
        if range_pct > 0.003:
            return "volatile"
        if slope > 0.001:
            return "uptrend"
        if slope < -0.001:
            return "downtrend"
        return "range"

    def _max_drawdown(self, results: list[float]) -> float:
        peak = 0.0
        equity = 0.0
        drawdown = 0.0
        for result in results:
            equity += result
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        return round(drawdown, 4)

    def _out_of_sample_results(self, results: list[float]) -> list[float]:
        if not results:
            return []
        size = max(1, round(len(results) * self.out_of_sample_ratio))
        return results[-size:]

    def _status(
        self,
        candidate: StrategyCandidate,
        trades: int,
        win_rate: float,
        profit_factor: float,
        max_drawdown: float,
        net_r: float,
        average_r: float,
        out_of_sample_net_r: float,
        quality_score: float,
    ) -> str:
        if trades < candidate.minimum_trades:
            return "incubating"
        if (
            profit_factor >= candidate.minimum_profit_factor
            and win_rate >= candidate.minimum_win_rate
            and max_drawdown <= candidate.maximum_drawdown_r
            and net_r > 0
            and average_r >= candidate.minimum_average_r
            and out_of_sample_net_r > 0
            and quality_score >= candidate.minimum_quality_score
        ):
            return "approved"
        if (
            net_r > 0
            and out_of_sample_net_r >= 0
            and quality_score >= candidate.minimum_quality_score * 0.72
            and max_drawdown <= candidate.maximum_drawdown_r * 1.4
        ):
            return "watch"
        return "rejected"

    def _quality_score(
        self,
        trades: int,
        win_rate: float,
        profit_factor: float,
        max_drawdown: float,
        net_r: float,
        average_r: float,
        out_of_sample_net_r: float,
    ) -> float:
        sample_score = min(trades / 30, 1.0) * 20
        win_score = min(max(win_rate, 0.0) / 0.55, 1.0) * 15
        profit_score = min(max(profit_factor - 1.0, 0.0) / 1.0, 1.0) * 20
        net_score = min(max(net_r, 0.0) / 12.0, 1.0) * 15
        average_score = min(max(average_r, 0.0) / 0.35, 1.0) * 10
        out_of_sample_score = min(max(out_of_sample_net_r, 0.0) / 4.0, 1.0) * 15
        drawdown_penalty = min(max(max_drawdown - 3.0, 0.0) / 6.0, 1.0) * 18
        return round(max(sample_score + win_score + profit_score + net_score + average_score + out_of_sample_score - drawdown_penalty, 0.0), 2)

    def _evidence_level(self, trades: int, out_of_sample: list[float], quality_score: float) -> str:
        if trades >= 30 and len(out_of_sample) >= 8 and quality_score >= 75:
            return "strong"
        if trades >= 14 and len(out_of_sample) >= 4 and quality_score >= 55:
            return "developing"
        return "thin"

    def _precision_grade(
        self,
        trades: int,
        profit_factor: float,
        max_drawdown: float,
        net_r: float,
        average_r: float,
        out_of_sample_net_r: float,
        quality_score: float,
    ) -> str:
        if trades < 8:
            return "insufficient_sample"
        if (
            profit_factor >= 1.5
            and max_drawdown <= 4
            and net_r > 0
            and average_r >= 0.12
            and out_of_sample_net_r > 0
            and quality_score >= 75
        ):
            return "high"
        if profit_factor >= 1.15 and net_r > 0 and average_r > 0 and out_of_sample_net_r >= 0 and quality_score >= 50:
            return "medium"
        return "low"

    def _reasons_not_to_enter(
        self,
        candidate: StrategyCandidate,
        trades: int,
        win_rate: float,
        profit_factor: float,
        max_drawdown: float,
        net_r: float,
        average_r: float,
        out_of_sample_net_r: float,
        quality_score: float,
    ) -> tuple[str, ...]:
        reasons = []
        if trades < candidate.minimum_trades:
            reasons.append(f"Only {trades} qualified backtest trades; needs at least {candidate.minimum_trades}.")
        if win_rate < candidate.minimum_win_rate:
            reasons.append(f"Win rate {win_rate:.0%} is below the {candidate.minimum_win_rate:.0%} minimum.")
        if profit_factor < candidate.minimum_profit_factor:
            reasons.append(f"Profit factor {profit_factor:.2f} is below the {candidate.minimum_profit_factor:.2f} threshold.")
        if max_drawdown > candidate.maximum_drawdown_r:
            reasons.append(f"Max drawdown {max_drawdown:.2f}R exceeds the {candidate.maximum_drawdown_r:.2f}R limit.")
        if net_r <= 0:
            reasons.append("Net R is not positive after execution costs.")
        if average_r < candidate.minimum_average_r:
            reasons.append(f"Average R {average_r:.2f} is below the {candidate.minimum_average_r:.2f} minimum.")
        if out_of_sample_net_r <= 0:
            reasons.append("Recent out-of-sample R is not positive.")
        if quality_score < candidate.minimum_quality_score:
            reasons.append(f"Quality score {quality_score:.0f}/100 is below the {candidate.minimum_quality_score:.0f}/100 approval bar.")
        return tuple(reasons[:4])

    def _notes(
        self,
        candidate: StrategyCandidate,
        trades: int,
        win_rate: float,
        profit_factor: float,
        max_drawdown: float,
        net_r: float,
        average_r: float,
        out_of_sample_net_r: float,
        quality_score: float,
        market_condition: str,
        reasons_not_to_enter: tuple[str, ...],
    ) -> tuple[str, ...]:
        notes = [f"Tested in {market_condition} conditions."]
        if trades < candidate.minimum_trades:
            notes.append("Needs more trades before promotion.")
        if win_rate >= candidate.minimum_win_rate:
            notes.append("Win rate is above the strategy approval floor.")
        if profit_factor < candidate.minimum_profit_factor:
            notes.append("Profit factor is below approval threshold.")
        if max_drawdown > candidate.maximum_drawdown_r:
            notes.append("Drawdown exceeds strategy limit.")
        if net_r > 0 and average_r > 0:
            notes.append("Net R and average R are positive after spread and slippage assumptions.")
        else:
            notes.append("Net R is not strong enough for approval.")
        if out_of_sample_net_r <= 0:
            notes.append("Recent out-of-sample R is not positive.")
        if quality_score >= candidate.minimum_quality_score:
            notes.append(f"Quality score passed at {quality_score:.0f}/100.")
        elif reasons_not_to_enter:
            notes.append(f"Primary rejection reason: {reasons_not_to_enter[0]}")
        return tuple(notes)

    def _summary(self, scorecards: list[StrategyScorecard]) -> dict[str, Any]:
        approved = len([scorecard for scorecard in scorecards if scorecard.status == "approved"])
        watch = len([scorecard for scorecard in scorecards if scorecard.status == "watch"])
        rejected = len([scorecard for scorecard in scorecards if scorecard.status == "rejected"])
        best = scorecards[0] if scorecards else None
        return {
            "approved": approved,
            "watch": watch,
            "rejected": rejected,
            "bestStrategy": best.name if best else None,
            "bestNetR": best.net_r if best else 0,
            "bestQuality": best.quality_score if best else 0,
            "bestEvidence": best.evidence_level if best else "thin",
        }
