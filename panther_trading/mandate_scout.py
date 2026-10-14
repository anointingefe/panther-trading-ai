from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from panther_trading.live_scout import LiveScoutDecision, LiveScoutTrader


class BalancedMandateLiveScoutTrader(LiveScoutTrader):
    """Live scout with a conservative pre-authorization mandate score.

    The mandate score identifies setups that satisfy the user's balanced rules.
    It does not change Panther's real-money execution permission: the returned
    ticket remains approval-gated and this class never submits an order.
    """

    def status(self) -> dict[str, Any]:
        state = super().status()
        config = self._config()
        state["balancedMandate"] = {
            "minConfidence": config.live_scout.mandate_min_confidence,
            "minEdgeProbability": config.live_scout.mandate_min_edge_probability,
            "minLearningQuality": config.live_scout.mandate_min_learning_quality,
            "maxRiskPerTradePct": config.live_scout.mandate_max_risk_per_trade_pct,
            "dailyLossStopPct": config.live_scout.mandate_daily_loss_stop_pct,
            "maxOpenPositions": config.live_scout.model_max_open_positions,
            "maxPortfolioRiskPct": config.live_scout.model_max_portfolio_risk_pct,
            "maxExposureBucketRiskPct": config.live_scout.model_max_exposure_bucket_risk_pct,
            "adaptiveTightening": True,
            "executionPermission": "explicit_approval_required",
        }
        return state

    def _config(self) -> Any:
        from panther_trading.config import load_config

        return load_config(self.config_path)

    def _evaluate_symbol(
        self,
        config: Any,
        broker: Any,
        helper: Any,
        learning_engine: Any,
        learning: dict[str, Any],
        symbol: str,
        positions: list[dict[str, Any]],
        loss_state: dict[str, dict[str, Any]],
        goal_pressure: dict[str, Any],
        daily_pnl: float,
    ) -> LiveScoutDecision:
        daily_stop_amount = config.risk.account_equity * config.live_scout.mandate_daily_loss_stop_pct / 100
        if math.isfinite(daily_pnl) and daily_pnl <= -daily_stop_amount:
            return self._blocked(
                symbol,
                "hold",
                0.0,
                (
                    f"Balanced mandate daily loss breaker reached: {daily_pnl:.2f} <= "
                    f"-{daily_stop_amount:.2f}. No new mandate candidates until the next trading day."
                ),
                portfolio_risk={
                    "mandate": {
                        "eligible": False,
                        "breaker": "daily_loss_stop",
                        "dailyLossStopPct": config.live_scout.mandate_daily_loss_stop_pct,
                        "executionPermission": "explicit_approval_required",
                    }
                },
            )

        decision = super()._evaluate_symbol(
            config,
            broker,
            helper,
            learning_engine,
            learning,
            symbol,
            positions,
            loss_state,
            goal_pressure,
            daily_pnl,
        )
        if decision.status != "ready":
            return decision

        signal_time = self._parse_time(decision.generated_at) or datetime.now(timezone.utc)
        learning_quality = self._mandate_learning_quality(
            learning,
            symbol,
            signal_time,
            config.live_scout.learning_min_segment_samples,
        )
        recent = self._recent_performance(
            positions,
            window=config.live_scout.mandate_recent_window_trades,
            minimum_samples=config.live_scout.mandate_adaptive_min_samples,
            degraded_win_rate=config.live_scout.mandate_degraded_win_rate,
        )
        effective = self._effective_thresholds(config, recent)
        mandate = self._mandate_eligibility(
            config,
            confidence=decision.confidence,
            edge_probability=decision.edge_probability,
            learning_quality=learning_quality,
            effective=effective,
            recent=recent,
        )
        portfolio_payload = dict(decision.portfolio_risk or {})
        portfolio_payload["mandate"] = mandate
        mandate_text = (
            "Balanced mandate thresholds passed."
            if mandate["eligible"]
            else "Balanced mandate thresholds not met: " + "; ".join(mandate["reasons"])
        )
        rationale = tuple(
            [
                *decision.rationale,
                (
                    f"Mandate evidence quality {learning_quality:.0%}; effective floors: "
                    f"confidence {effective['confidence']:.0%}, edge {effective['edgeProbability']:.0%}, "
                    f"learning {effective['learningQuality']:.0%}."
                ),
                mandate_text,
                "Mandate eligibility does not bypass explicit real-money execution approval.",
            ]
        )
        return replace(
            decision,
            learning_quality=learning_quality,
            reason=(
                "Approval-ready live setup; balanced mandate eligible"
                if mandate["eligible"]
                else "Approval-ready live setup; balanced mandate review required"
            ),
            rationale=rationale,
            portfolio_risk=portfolio_payload,
            approval_required=True,
        )

    def _live_volume(
        self,
        config: Any,
        broker: Any,
        signal: Any,
        goal_pressure: dict[str, Any],
        risk_budget: float | None = None,
    ) -> float:
        mandate_risk = min(
            float(config.risk.max_risk_per_trade_pct),
            float(config.live_scout.mandate_max_risk_per_trade_pct),
        )
        mandate_config = replace(
            config,
            risk=replace(config.risk, max_risk_per_trade_pct=mandate_risk),
        )
        return super()._live_volume(
            mandate_config,
            broker,
            signal,
            goal_pressure,
            risk_budget=risk_budget,
        )

    def _effective_thresholds(self, config: Any, recent: dict[str, Any]) -> dict[str, float]:
        confidence = float(config.live_scout.mandate_min_confidence)
        edge = float(config.live_scout.mandate_min_edge_probability)
        learning = float(config.live_scout.mandate_min_learning_quality)
        if recent.get("degraded"):
            confidence += float(config.live_scout.mandate_confidence_tighten_step)
            edge += float(config.live_scout.mandate_edge_tighten_step)
            learning += float(config.live_scout.mandate_learning_tighten_step)
        return {
            "confidence": round(min(confidence, 0.99), 4),
            "edgeProbability": round(min(edge, 0.99), 4),
            "learningQuality": round(min(learning, 0.99), 4),
        }

    def _mandate_eligibility(
        self,
        config: Any,
        confidence: float,
        edge_probability: float | None,
        learning_quality: float,
        effective: dict[str, float],
        recent: dict[str, Any],
    ) -> dict[str, Any]:
        edge = float(edge_probability) if edge_probability is not None else 0.0
        reasons: list[str] = []
        if confidence < effective["confidence"]:
            reasons.append(
                f"confidence {confidence:.0%} below {effective['confidence']:.0%} mandate floor"
            )
        if edge < effective["edgeProbability"]:
            reasons.append(
                f"edge {edge:.0%} below {effective['edgeProbability']:.0%} mandate floor"
            )
        if learning_quality < effective["learningQuality"]:
            reasons.append(
                f"learning quality {learning_quality:.0%} below {effective['learningQuality']:.0%} mandate floor"
            )
        return {
            "eligible": not reasons,
            "executionPermission": "explicit_approval_required",
            "baseThresholds": {
                "confidence": config.live_scout.mandate_min_confidence,
                "edgeProbability": config.live_scout.mandate_min_edge_probability,
                "learningQuality": config.live_scout.mandate_min_learning_quality,
            },
            "effectiveThresholds": effective,
            "candidate": {
                "confidence": round(float(confidence), 4),
                "edgeProbability": round(edge, 4),
                "learningQuality": round(float(learning_quality), 4),
            },
            "recentPerformance": recent,
            "maxRiskPerTradePct": config.live_scout.mandate_max_risk_per_trade_pct,
            "dailyLossStopPct": config.live_scout.mandate_daily_loss_stop_pct,
            "reasons": reasons,
        }

    def _mandate_learning_quality(
        self,
        profile: dict[str, Any],
        symbol: str,
        signal_time: datetime,
        minimum_samples: int,
    ) -> float:
        symbol_key = "".join(char for char in symbol.upper() if char.isalnum())
        hour_key = str(signal_time.astimezone(timezone.utc).hour)
        symbol_row = next(
            (row for row in profile.get("symbols") or [] if str(row.get("key")) == symbol_key),
            None,
        )
        hour_row = next(
            (row for row in profile.get("utc_hours") or [] if str(row.get("key")) == hour_key),
            None,
        )
        weighted: list[tuple[float, float]] = []
        if symbol_row and int(symbol_row.get("samples") or 0) >= minimum_samples:
            weighted.append((float(symbol_row.get("win_rate") or 0.0), 2.0))
        if hour_row and int(hour_row.get("samples") or 0) >= minimum_samples:
            weighted.append((float(hour_row.get("win_rate") or 0.0), 1.0))
        if not weighted:
            return 0.5
        numerator = sum(value * weight for value, weight in weighted)
        denominator = sum(weight for _, weight in weighted)
        return round(max(min(numerator / denominator, 1.0), 0.0), 4)

    def _recent_performance(
        self,
        positions: list[dict[str, Any]],
        window: int,
        minimum_samples: int,
        degraded_win_rate: float,
    ) -> dict[str, Any]:
        eligible_modes = {"live", "demo", "contest", "paper"}
        closed: list[dict[str, Any]] = []
        for item in positions:
            if item.get("status") != "closed":
                continue
            metadata = item.get("metadata") or {}
            if str(metadata.get("evidence_mode") or "").lower() not in eligible_modes:
                continue
            closed.append(item)
        closed.sort(key=lambda item: self._parse_time(item.get("closed_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        sample = closed[: max(int(window), 1)]
        wins = len([item for item in sample if self._pnl(item) > 0])
        losses = len([item for item in sample if self._pnl(item) < 0])
        decided = wins + losses
        win_rate = wins / decided if decided else 0.0
        net_pnl = sum(self._pnl(item) for item in sample)
        enough = len(sample) >= max(int(minimum_samples), 1)
        degraded = enough and (win_rate < float(degraded_win_rate) or net_pnl < 0)
        return {
            "samples": len(sample),
            "wins": wins,
            "losses": losses,
            "winRate": round(win_rate, 4),
            "netPnl": round(net_pnl, 4),
            "degraded": degraded,
            "minimumSamples": int(minimum_samples),
            "degradedWinRate": float(degraded_win_rate),
        }

    @staticmethod
    def _pnl(item: dict[str, Any]) -> float:
        try:
            value = float(item.get("pnl") or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
