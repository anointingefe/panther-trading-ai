from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from panther_trading.config import PantherConfig


@dataclass(frozen=True)
class ExecutionGreenFlagReport:
    status: str
    passed: bool
    score: float
    reasons: tuple[str, ...]
    checklist: tuple[str, ...]
    native_samples: int
    preflight_pass_rate: float
    quote_fresh_rate: float
    volume_valid_rate: float
    bracket_valid_rate: float
    reconciliation_samples: int
    reconciliation_clean_rate: float
    latest_reconciliation_clean: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionGreenFlag:
    """Prove the broker/execution path before Panther can become live-ready."""

    def __init__(self, config: PantherConfig) -> None:
        self.config = config.shadow_execution

    def evaluate(self, state: dict[str, Any]) -> ExecutionGreenFlagReport:
        samples = [sample for sample in state.get("samples", []) if sample.get("broker_native")]
        reconciliations = list(state.get("reconciliationHistory", []))
        native_samples = len(samples)
        reconciliation_samples = len(reconciliations)
        preflight_rate = self._rate(samples, lambda item: bool(item.get("preflight_passed")))
        quote_rate = self._rate(samples, lambda item: bool(item.get("quote_fresh")))
        volume_rate = self._rate(samples, lambda item: bool(item.get("volume_valid")))
        bracket_rate = self._rate(samples, lambda item: bool(item.get("bracket_valid")))
        reconciliation_clean_rate = self._rate(reconciliations, lambda item: bool(item.get("clean")))
        latest_clean = bool(reconciliations and reconciliations[-1].get("clean"))

        reasons: list[str] = []
        if native_samples < self.config.min_samples:
            reasons.append(f"Needs at least {self.config.min_samples} broker-native shadow execution samples.")
        if preflight_rate < self.config.min_preflight_pass_rate:
            reasons.append(
                f"Shadow preflight pass rate must be at least {self.config.min_preflight_pass_rate:.0%}."
            )
        if quote_rate < self.config.min_quote_fresh_rate:
            reasons.append(f"Fresh-quote rate must be at least {self.config.min_quote_fresh_rate:.0%}.")
        if volume_rate < 1.0:
            reasons.append("Every qualifying shadow sample must produce a broker-valid position size.")
        if bracket_rate < 1.0:
            reasons.append("Every qualifying shadow sample must preserve a valid stop/target bracket at market price.")
        if reconciliation_samples < self.config.min_reconciliation_samples:
            reasons.append(
                f"Needs at least {self.config.min_reconciliation_samples} broker reconciliation checks."
            )
        if reconciliation_samples and reconciliation_clean_rate < 1.0:
            reasons.append("All recorded broker reconciliation checks must be clean before live readiness.")
        if reconciliation_samples and not latest_clean:
            reasons.append("Latest broker reconciliation is not clean.")

        passed = not reasons
        status = "passed" if passed else "building_evidence" if native_samples < self.config.min_samples else "blocked"
        score = self._score(
            native_samples,
            preflight_rate,
            quote_rate,
            volume_rate,
            bracket_rate,
            reconciliation_samples,
            reconciliation_clean_rate,
            latest_clean,
        )
        return ExecutionGreenFlagReport(
            status=status,
            passed=passed,
            score=score,
            reasons=tuple(reasons),
            checklist=tuple(self._checklist()),
            native_samples=native_samples,
            preflight_pass_rate=preflight_rate,
            quote_fresh_rate=quote_rate,
            volume_valid_rate=volume_rate,
            bracket_valid_rate=bracket_rate,
            reconciliation_samples=reconciliation_samples,
            reconciliation_clean_rate=reconciliation_clean_rate,
            latest_reconciliation_clean=latest_clean,
        )

    def _checklist(self) -> list[str]:
        return [
            f"Collect at least {self.config.min_samples} MT5-native shadow execution samples.",
            f"Keep shadow preflight success at or above {self.config.min_preflight_pass_rate:.0%}.",
            f"Keep fresh broker quotes at or above {self.config.min_quote_fresh_rate:.0%}.",
            "Every sample must produce a broker-valid position size.",
            "Every sample must preserve a valid SL/TP bracket at the real market quote.",
            f"Record at least {self.config.min_reconciliation_samples} clean broker reconciliation checks.",
            "No orphan, missing, duplicate, or unreconciled Panther live positions may exist.",
        ]

    def _rate(self, items: list[dict[str, Any]], predicate: Any) -> float:
        if not items:
            return 0.0
        return round(sum(1 for item in items if predicate(item)) / len(items), 4)

    def _score(
        self,
        samples: int,
        preflight_rate: float,
        quote_rate: float,
        volume_rate: float,
        bracket_rate: float,
        reconciliation_samples: int,
        reconciliation_rate: float,
        latest_clean: bool,
    ) -> float:
        score = 0.0
        score += min(samples / max(self.config.min_samples, 1), 1.0) * 20
        score += preflight_rate * 20
        score += quote_rate * 12
        score += volume_rate * 12
        score += bracket_rate * 12
        score += min(reconciliation_samples / max(self.config.min_reconciliation_samples, 1), 1.0) * 10
        score += reconciliation_rate * 10
        score += 4 if latest_clean else 0
        return round(min(max(score, 0.0), 100.0), 2)
