from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any

from panther_trading.config import PantherConfig
from panther_trading.data.markets import default_watchlist
from panther_trading.models import Candle, SignalSide, TradeSignal


@dataclass(frozen=True)
class Opportunity:
    symbol: str
    direction: str
    score: float
    catalyst: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PositionSizingPlan:
    capital: float
    risk_tolerance_pct: float
    adjusted_risk_pct: float
    risk_amount: float
    unit_size: float
    max_simultaneous_trades: int
    sizing_multiplier: float
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DailyOpportunityScanner:
    def scan(self, broker: Any, config: PantherConfig, limit: int = 5) -> list[dict[str, Any]]:
        opportunities = []
        for market in default_watchlist(24):
            try:
                candles = broker.get_candles(market.symbol, config.app.timeframe, config.app.candles)
            except Exception:
                continue
            if len(candles) < 40:
                continue
            opportunities.append(self._score(market.symbol, candles).to_dict())
        opportunities.sort(key=lambda item: item["score"], reverse=True)
        return opportunities[:limit]

    def _score(self, symbol: str, candles: list[Candle]) -> Opportunity:
        closes = [candle.close for candle in candles]
        latest = closes[-1]
        fast = fmean(closes[-8:])
        slow = fmean(closes[-34:])
        average_range = fmean(candle.high - candle.low for candle in candles[-20:])
        latest_range = candles[-1].high - candles[-1].low
        volume_base = fmean(candle.volume for candle in candles[-21:-1])
        volume_ratio = candles[-1].volume / volume_base if volume_base else 1.0
        trend = (fast - slow) / latest if latest else 0.0
        direction = "buy" if trend > 0 else "sell"
        volatility_score = min(latest_range / average_range, 2.0) / 2 if average_range else 0.0
        volume_score = min(volume_ratio, 2.0) / 2
        trend_score = min(abs(trend) * 400, 1.0)
        score = round((trend_score * 0.5) + (volatility_score * 0.25) + (volume_score * 0.25), 4)
        risk = max(average_range * 1.5, latest * 0.001)
        reward = risk * 1.8
        stop_loss = latest - risk if direction == "buy" else latest + risk
        take_profit = latest + reward if direction == "buy" else latest - reward
        warnings = []
        if latest_range > average_range * 2.2:
            warnings.append("Latest candle is unusually large; wait for spread/slippage to calm.")
        if volume_ratio < 0.8:
            warnings.append("Volume is below recent baseline; breakout quality is weaker.")
        return Opportunity(
            symbol=symbol,
            direction=direction,
            score=score,
            catalyst=f"{direction.upper()} bias from short-term trend, range expansion, and volume ratio {volume_ratio:.2f}.",
            entry=round(latest, 6),
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            risk_reward=1.8,
            warnings=tuple(warnings),
        )


class PositionSizingManager:
    def plan(
        self,
        config: PantherConfig,
        signal: TradeSignal,
        closed_positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        loss_streak = self._loss_streak(closed_positions)
        multiplier = 1.0
        rule = "Base size: risk only the configured percent per trade."
        if loss_streak >= 5:
            multiplier = 0.0
            rule = "Pause new entries after 5 consecutive losses until strategy review passes."
        elif loss_streak >= 3:
            multiplier = 0.5
            rule = "Reduce size by 50% after 3 consecutive losses."
        elif self._win_streak(closed_positions) >= 4:
            multiplier = 1.15
            rule = "Small size increase allowed only after 4 consecutive wins, still capped by risk settings."

        risk_pct = config.risk.max_risk_per_trade_pct * multiplier
        risk_amount = config.risk.account_equity * (risk_pct / 100)
        stop_distance = abs(signal.entry - signal.stop_loss)
        unit_size = risk_amount / stop_distance if stop_distance > 0 else 0.0
        max_total_risk_pct = config.risk.max_daily_loss_pct
        max_simultaneous = int(max_total_risk_pct // risk_pct) if risk_pct > 0 else 0
        max_simultaneous = max(0, min(config.risk.max_open_positions, max_simultaneous))
        return PositionSizingPlan(
            capital=config.risk.account_equity,
            risk_tolerance_pct=config.risk.max_risk_per_trade_pct,
            adjusted_risk_pct=round(risk_pct, 4),
            risk_amount=round(risk_amount, 2),
            unit_size=round(unit_size, 4),
            max_simultaneous_trades=max_simultaneous,
            sizing_multiplier=multiplier,
            rule=rule,
        ).to_dict()

    def _loss_streak(self, positions: list[dict[str, Any]]) -> int:
        streak = 0
        for position in positions:
            if position.get("status") != "closed":
                continue
            if float(position.get("pnl") or 0.0) < 0:
                streak += 1
                continue
            break
        return streak

    def _win_streak(self, positions: list[dict[str, Any]]) -> int:
        streak = 0
        for position in positions:
            if position.get("status") != "closed":
                continue
            if float(position.get("pnl") or 0.0) > 0:
                streak += 1
                continue
            break
        return streak


class MarketTrapDetector:
    def analyze(
        self,
        symbol: str,
        side: SignalSide,
        candles: list[Candle],
        intelligence: dict[str, Any],
    ) -> dict[str, Any]:
        traps: list[str] = []
        required_changes: list[str] = []
        if len(candles) >= 25:
            recent_range = candles[-1].high - candles[-1].low
            average_range = fmean(candle.high - candle.low for candle in candles[-21:-1])
            if average_range and recent_range > average_range * 2.0:
                traps.append("Price may be chasing an exhaustion candle.")
                required_changes.append("Wait for a pullback or second confirmation candle.")
            if self._price_volume_divergence(candles):
                traps.append("Price and volume are diverging.")
                required_changes.append("Require volume to confirm the next breakout.")
        score = float(intelligence.get("score") or 0.0)
        if side == SignalSide.BUY and score < -0.25:
            traps.append("Macro/news tone conflicts with a buy entry.")
            required_changes.append("Wait for news score to neutralize or price to break structure cleanly.")
        if side == SignalSide.SELL and score > 0.25:
            traps.append("Macro/news tone conflicts with a sell entry.")
            required_changes.append("Wait for news score to neutralize or bearish confirmation to strengthen.")
        verdict = "clear" if not traps else "caution" if len(traps) < 3 else "avoid"
        return {
            "symbol": symbol,
            "verdict": verdict,
            "trapCount": len(traps),
            "reasonsNotToEnter": traps[:3],
            "requiredChanges": required_changes[:3],
        }

    def _price_volume_divergence(self, candles: list[Candle]) -> bool:
        recent = candles[-8:]
        price_change = recent[-1].close - recent[0].close
        volume_change = recent[-1].volume - recent[0].volume
        return (price_change > 0 and volume_change < 0) or (price_change < 0 and volume_change > 0)


class NewsToTradesTranslator:
    def translate(self, intelligence: dict[str, Any], opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ideas = []
        by_symbol = {item["symbol"]: item for item in opportunities}
        for item in intelligence.get("items", [])[:8]:
            polarity = float(item.get("polarity") or 0.0)
            if abs(polarity) < 0.2:
                continue
            for symbol in item.get("symbols", [])[:3]:
                opportunity = by_symbol.get(symbol)
                if not opportunity:
                    continue
                direction = "buy" if polarity > 0 else "sell"
                ideas.append(
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "headline": item.get("title"),
                        "entry": opportunity["entry"],
                        "stop_loss": opportunity["stop_loss"],
                        "take_profit": opportunity["take_profit"],
                        "confidence": round(min(abs(polarity) * opportunity["score"], 0.85), 4),
                    }
                )
        return ideas[:3]


class PortfolioRiskAnalyzer:
    def analyze(self, positions: list[dict[str, Any]], config: PantherConfig) -> dict[str, Any]:
        open_positions = [position for position in positions if position.get("status") == "open"]
        risk_amounts = []
        vulnerable = []
        for position in open_positions:
            entry = float(position.get("entry") or 0.0)
            stop = float(position.get("stop_loss") or entry)
            volume = float(position.get("volume") or 0.0)
            risk_amount = abs(entry - stop) * volume
            risk_amounts.append(risk_amount)
            if str(position.get("side")).lower() == "buy":
                impact_10 = (entry * 0.9 - entry) * volume
            else:
                impact_10 = (entry - entry * 1.1) * volume
            vulnerable.append(
                {
                    "symbol": position.get("symbol"),
                    "riskAmount": round(risk_amount, 4),
                    "tenPercentShock": round(impact_10, 4),
                }
            )
        total_risk = sum(risk_amounts)
        equity = config.risk.account_equity
        risk_pct = total_risk / equity if equity else 0.0
        return {
            "openPositions": len(open_positions),
            "totalRiskAmount": round(total_risk, 4),
            "totalRiskPct": round(risk_pct, 4),
            "mostVulnerable": sorted(vulnerable, key=lambda item: abs(item["tenPercentShock"]), reverse=True)[:3],
            "defensiveAdjustment": self._defensive_adjustment(risk_pct, config),
        }

    def _defensive_adjustment(self, risk_pct: float, config: PantherConfig) -> str:
        cap = config.risk.max_daily_loss_pct / 100
        if risk_pct >= cap:
            return "No new trades; total open risk is at or above the daily loss cap."
        if risk_pct >= cap * 0.7:
            return "Reduce new trade size and avoid correlated entries."
        return "Risk load is inside the configured cap."


class CustomStrategyBuilder:
    def build(self, config: PantherConfig, edge_validation: dict[str, Any]) -> dict[str, Any]:
        phase = "incubation" if not edge_validation.get("passed") else "promotion_candidate"
        return {
            "phase": phase,
            "markets": "Trade only symbols with broker data, tight spreads, and enough recent candles.",
            "timeframe": config.app.timeframe,
            "weeklyTradeTarget": "Quality over frequency: cap entries at the configured open-position limit.",
            "workingCriteria": [
                f"At least {config.validation.min_demo_trades} closed demo trades.",
                f"Profit factor >= {config.validation.min_profit_factor}.",
                f"Net R >= {config.validation.min_net_r} with drawdown <= {config.validation.max_drawdown_r}R.",
            ],
            "adjustmentCriteria": [
                "Pause size increases after any 3-loss streak.",
                "Retest strategy when market condition changes.",
                "Promote only after demo evidence and research scorecards agree.",
            ],
        }
