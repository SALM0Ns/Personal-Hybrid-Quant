"""Pure synthetic-first accounting. No models, dataset readers or writers.

Emission accepts no target information. Outcome classification is separate
and requires theoretical closure, not verified historical publication.
"""

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from quant.features.engine import FEATURES
from quant.research import evaluation_protocol as p
from quant.research.forecast_dataset import (
    TARGET_REASON_PRIORITY,
    TEST_END,
    TEST_START,
    TRAIN_START,
    VALIDATION_START,
)

PERIODS = {
    "training_history": (TRAIN_START, VALIDATION_START),
    "validation": (VALIDATION_START, TEST_START),
    "test": (TEST_START, TEST_END),
}
MODELS = ("zero_return", "expanding_mean", "ar_1", "ridge_7")
SAMPLES = ("a_primary", "a_sensitivity")
FEATURE_NULL = tuple(f"feature_null__{f}" for f in FEATURES)
FEATURE_ANOMALY = tuple(f"feature_manifest_anomaly__{f}" for f in FEATURES)
SCORE_PRIORITY = (
    *TARGET_REASON_PRIORITY,
    "target_manifest_anomaly",
    *FEATURE_NULL,
    *FEATURE_ANOMALY,
    "ar_lag_missing_or_invalid",
    "ar_lag_manifest_anomaly",
    "insufficient_training_history",
    "ar_ill_conditioned_lag",
    "ar_numerical_failure",
    "ridge_numerical_failure",
    "nonfinite_prediction",
)
UNKNOWN_AVAILABILITY = "unknown_historical_availability"


def finite(value: object) -> float:
    if type(value) not in (float, int):
        raise ValueError("finite numeric value required")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("finite numeric value required") from exc
    if not math.isfinite(result):
        raise ValueError("finite numeric value required")
    return result


def identity(model: str, sample: str) -> None:
    if model not in MODELS or sample not in SAMPLES:
        raise ValueError("unknown model/sample identity")


def forecast_reason_order(model: str, sample: str) -> tuple[str, ...]:
    identity(model, sample)
    sensitivity = sample == "a_sensitivity"
    if model == "zero_return":
        return ()
    if model == "expanding_mean":
        return ("insufficient_training_history", "nonfinite_prediction")
    if model == "ar_1":
        return (
            "ar_lag_missing_or_invalid",
            *(("ar_lag_manifest_anomaly",) if sensitivity else ()),
            "insufficient_training_history",
            "ar_ill_conditioned_lag",
            "ar_numerical_failure",
            "nonfinite_prediction",
        )
    return (
        *FEATURE_NULL,
        *(FEATURE_ANOMALY if sensitivity else ()),
        "insufficient_training_history",
        "ridge_numerical_failure",
        "nonfinite_prediction",
    )


def ordered_reasons(reasons: tuple[str, ...], order: tuple[str, ...]) -> tuple:
    if (
        type(reasons) is not tuple
        or any(type(r) is not str or r not in order for r in reasons)
        or len(set(reasons)) != len(reasons)
    ):
        raise ValueError("unknown, duplicate or malformed reasons")
    return tuple(r for r in order if r in reasons)


@dataclass(frozen=True)
class OriginUniverse:
    """A predeclared bounded synthetic window inside one approved split.

    Empty windows are allowed. This does not move the governing split or
    claim a bounded fixture represents a full historical split.
    """

    period_id: str
    start: datetime
    end: datetime

    def __post_init__(self):
        p.validate_hour(self.start)
        p.validate_hour(self.end)
        if self.period_id not in PERIODS:
            raise ValueError("unknown period")
        lower, upper = PERIODS[self.period_id]
        if not lower <= self.start <= self.end <= upper:
            raise ValueError("window outside approved split")

    @property
    def origins(self) -> tuple[datetime, ...]:
        return tuple(
            self.start + i * p.HOUR
            for i in range(int((self.end - self.start) / p.HOUR))
        )


@dataclass(frozen=True)
class Forecast:
    origin: datetime
    model_id: str
    sample_policy: str
    prediction: float | None
    reasons: tuple[str, ...] = ()

    def __post_init__(self):
        p.require_evaluation_origin(self.origin)
        order = forecast_reason_order(self.model_id, self.sample_policy)
        if ordered_reasons(self.reasons, order) != self.reasons:
            raise ValueError("forecast reasons must follow method priority")
        if self.prediction is None:
            if not self.reasons:
                raise ValueError("abstention requires a reason")
        elif self.reasons or not math.isfinite(finite(self.prediction)):
            raise ValueError("emission must be finite with no abstention reasons")
        if self.model_id == "zero_return" and self.prediction != 0.0:
            raise ValueError("Zero Return must emit 0.0")

    @property
    def status(self) -> str:
        return "emitted" if self.prediction is not None else "abstained"

    @property
    def abstention_reason(self) -> str | None:
        return self.reasons[0] if self.reasons else None


@dataclass(frozen=True)
class Quality:
    """Post-outcome audit metadata; never part of emission construction."""

    feature_complete: bool = True
    ar_lag_valid: bool = True
    anomaly_types: tuple[str, ...] = ()
    affected_fields: tuple[str, ...] = ()

    def __post_init__(self):
        if any(type(v) is not bool for v in (self.feature_complete, self.ar_lag_valid)):
            raise ValueError("quality flags must be Boolean")
        for values, allowed in (
            (
                self.anomaly_types,
                {"missing_hour", "source_discrepancy", "shortened_close"},
            ),
            (self.affected_fields, {"open", "high", "low", "close", "volume"}),
        ):
            if (
                type(values) is not tuple
                or any(type(v) is not str or v not in allowed for v in values)
                or tuple(sorted(set(values))) != values
            ):
                raise ValueError("invalid quality metadata")


@dataclass(frozen=True)
class Outcome:
    origin: datetime
    target: float | None
    target_valid: bool
    invalid_reasons: tuple[str, ...] = ()
    target_manifest_anomaly: bool = False
    quality: Quality = Quality()
    anomaly_evidence_status: str = "unverified"

    def __post_init__(self):
        p.require_evaluation_origin(self.origin)
        if any(
            type(v) is not bool
            for v in (self.target_valid, self.target_manifest_anomaly)
        ) or not isinstance(self.quality, Quality):
            raise ValueError("invalid outcome flags/quality")
        # Flags and type/field lists are supplied audit claims, not a
        # manifest verification. Partial synthetic evidence is permitted;
        # absent details are never inferred and complete lists prove nothing.
        if type(self.anomaly_evidence_status) is not str or (
            self.anomaly_evidence_status not in {"unverified", "partial"}
        ):
            raise ValueError("anomaly evidence must remain unverified or partial")
        if ordered_reasons(self.invalid_reasons, TARGET_REASON_PRIORITY) != (
            self.invalid_reasons
        ):
            raise ValueError("target reasons must follow exclusion priority")
        if self.target_valid:
            finite(self.target)  # A contradictory valid label fails closed.
            if self.invalid_reasons:
                raise ValueError("valid target cannot have invalid reasons")
        elif self.target is not None or not self.invalid_reasons:
            raise ValueError("invalid target requires null value and reasons")


@dataclass(frozen=True)
class Score:
    forecast: Forecast
    outcome: Outcome
    checked_at: datetime

    def __post_init__(self):
        if not isinstance(self.forecast, Forecast) or not isinstance(
            self.outcome, Outcome
        ):
            raise ValueError("typed forecast and outcome required")
        if self.forecast.origin != self.outcome.origin:
            raise ValueError("forecast/outcome origin mismatch")
        p.validate_hour(self.checked_at)
        # This interface reads outcome metadata, so closure is required even
        # for abstentions. The pure protocol helper still allows earlier
        # not_scored_no_forecast classification without an Outcome.
        if self.checked_at < self.forecast.origin + p.HOUR:
            raise ValueError("outcome audit precedes theoretical target closure")
        p.validate_score_state(
            p.ForecastState(self.forecast.origin, self.forecast.status),
            self.status,
            checked_at=self.checked_at,
        )

    @property
    def exclusion_reasons(self) -> tuple[str, ...]:
        reasons = set(self.forecast.reasons) | set(self.outcome.invalid_reasons)
        if (
            self.forecast.sample_policy == "a_sensitivity"
            and self.outcome.target_manifest_anomaly
        ):
            reasons.add("target_manifest_anomaly")
        return tuple(r for r in SCORE_PRIORITY if r in reasons)

    @property
    def all_reasons(self) -> tuple[str, ...]:
        return (*self.exclusion_reasons, UNKNOWN_AVAILABILITY)

    @property
    def primary_reason(self) -> str:
        return self.exclusion_reasons[0] if self.exclusion_reasons else "scored"

    @property
    def status(self) -> str:
        if self.forecast.status == "abstained":
            return "not_scored_no_forecast"
        return "emitted_but_not_scored" if self.exclusion_reasons else "scored"


@dataclass(frozen=True)
class Accounting:
    universe: OriginUniverse
    model_id: str
    sample_policy: str
    scores: tuple[Score, ...]

    def __post_init__(self):
        identity(self.model_id, self.sample_policy)
        if (
            not isinstance(self.universe, OriginUniverse)
            or type(self.scores) is not tuple
        ):
            raise ValueError("typed universe and immutable scores required")
        if any(not isinstance(s, Score) for s in self.scores):
            raise ValueError("typed scores required")
        if tuple(s.forecast.origin for s in self.scores) != self.universe.origins:
            raise ValueError("scores must cover exactly the sorted scheduled universe")
        if any(
            (s.forecast.model_id, s.forecast.sample_policy)
            != (self.model_id, self.sample_policy)
            for s in self.scores
        ):
            raise ValueError("mixed model/sample accounting")
        p.validate_counts(**self.counts)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.universe.period_id, self.model_id, self.sample_policy)

    @property
    def scored_origins(self) -> tuple[datetime, ...]:
        return tuple(s.forecast.origin for s in self.scores if s.status == "scored")

    @property
    def counts(self) -> dict[str, int]:
        forecasts = Counter(s.forecast.status for s in self.scores)
        scores = Counter(s.status for s in self.scores)
        return {
            "origins": len(self.scores),
            "emitted": forecasts["emitted"],
            "abstained": forecasts["abstained"],
            "scored": scores["scored"],
            "emitted_but_not_scored": scores["emitted_but_not_scored"],
            "not_scored_no_forecast": scores["not_scored_no_forecast"],
        }

    @property
    def coverage(self) -> float | None:
        n = self.counts["origins"]
        return self.counts["emitted"] / n if n else None

    def reason_counts(self) -> dict[str, dict[str, int]]:
        abstentions = Counter(
            s.forecast.abstention_reason
            for s in self.scores
            if s.forecast.status == "abstained"
        )
        primary = Counter(s.primary_reason for s in self.scores if s.status != "scored")
        overlapping = Counter(r for s in self.scores for r in s.all_reasons)
        if sum(abstentions.values()) != self.counts["abstained"] or sum(
            primary.values()
        ) + self.counts["scored"] != len(self.scores):
            raise ValueError("exclusive reason conservation failed")
        return {
            "abstention_reasons": dict(sorted(abstentions.items())),
            "primary_score_exclusion_counts": dict(sorted(primary.items())),
            "all_score_exclusion_counts": dict(sorted(overlapping.items())),
        }


def account(
    universe: OriginUniverse, model_id: str, sample_policy: str, scores
) -> Accounting:
    """Sort, but never deduplicate or omit an unscorable scheduled origin."""
    return Accounting(
        universe,
        model_id,
        sample_policy,
        tuple(sorted(scores, key=lambda s: s.forecast.origin)),
    )
