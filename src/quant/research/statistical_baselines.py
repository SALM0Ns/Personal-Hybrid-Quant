"""Synthetic-first Lane A baselines. Pure in-memory APIs; no data or ledger I/O.

Times express mathematical closure, never verified publication. The caller
must provide validated source-candle status; no historical execution is wired.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from quant.research import evaluation_protocol as protocol

HOUR = protocol.HOUR
RESEARCH_ONLY = True
POINT_IN_TIME_VERIFIED = False


@dataclass(frozen=True)
class Prediction:
    value: float | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (self.value is None) != (self.reason is not None):
            raise ValueError("prediction must be finite or have an abstention reason")
        if self.value is not None and (
            type(self.value) is not float or not math.isfinite(self.value)
        ):
            raise ValueError("prediction must be a finite float")


@dataclass(frozen=True)
class HistoricalTarget:
    label_origin: datetime
    value: float | None
    target_valid: bool = True
    target_manifest_anomaly: bool = False

    def __post_init__(self) -> None:
        # Outcome flags/values are intentionally not inspected before admission.
        protocol.validate_hour(self.label_origin)


@dataclass(frozen=True)
class CloseObservation:
    candle_open: datetime
    close: float | None
    valid: bool = True
    manifest_anomaly: bool = False

    def __post_init__(self) -> None:
        protocol.validate_hour(self.candle_open)


@dataclass(frozen=True)
class MeanHistory:
    cutoff: datetime
    sample: str
    labels: tuple[HistoricalTarget, ...]


@dataclass(frozen=True)
class ARPair:
    feature_open: datetime
    lag: float
    target: float


@dataclass(frozen=True)
class ARHistory:
    cutoff: datetime
    sample: str
    pairs: tuple[ARPair, ...]
    numerical_failure: bool = False


@dataclass(frozen=True)
class ARFit:
    """Checked fit metadata and numeric state, not cryptographic provenance."""

    scheduled_at: datetime
    sample: str
    history_count: int
    max_outcome_close: datetime | None
    intercept: float | None
    slope: float | None
    reason: str | None

    def __post_init__(self) -> None:
        _sample(self.sample)
        if not protocol.refit_scheduled("ar_1", self.scheduled_at):
            raise ValueError("fit must belong to a scheduled midnight event")
        if type(self.history_count) is not int or self.history_count < 0:
            raise ValueError("fit history count must be a nonnegative integer")
        if self.max_outcome_close is not None:
            protocol.validate_hour(self.max_outcome_close)
            if self.max_outcome_close > self.scheduled_at:
                raise ValueError("fit provenance exceeds historical outcome cutoff")
        if self.reason is not None:
            if (
                self.reason
                not in {
                    "insufficient_training_history",
                    "ar_ill_conditioned_lag",
                    "ar_numerical_failure",
                }
                or self.intercept is not None
                or self.slope is not None
            ):
                raise ValueError(
                    "failed fit must have a valid reason and no parameters"
                )
            return
        if self.history_count < 720 or self.max_outcome_close is None:
            raise ValueError("successful fit requires 720 pairs and an outcome cutoff")
        try:
            _finite(self.intercept)
            _finite(self.slope)
        except (ArithmeticError, ValueError) as exc:
            raise ValueError("successful fit requires finite parameters") from exc


@dataclass(frozen=True)
class CurrentLag:
    origin: datetime
    sample: str
    value: float | None
    reason: str | None = None

    def __post_init__(self) -> None:
        protocol.require_evaluation_origin(self.origin)
        _sample(self.sample)
        if self.reason is not None:
            if (
                self.reason
                not in {"ar_lag_missing_or_invalid", "ar_lag_manifest_anomaly"}
                or self.value is not None
            ):
                raise ValueError(
                    "unavailable lag requires a valid reason and null value"
                )
            return
        try:
            _finite(self.value)
        except (ArithmeticError, ValueError) as exc:
            raise ValueError("successful lag requires a finite numeric value") from exc


def _sample(sample: str) -> None:
    if sample not in protocol.SAMPLES:
        raise ValueError("unknown Lane A sample")


def _bool(value: bool) -> None:
    if type(value) is not bool:
        raise ValueError("source status must be Boolean")


def _finite(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ArithmeticError("nonfinite numeric input or intermediate")
    return float(value)


def _forecast_origin(fields: Mapping[str, object]) -> datetime:
    protocol.validate_forecast_fields(fields)
    return fields["forecast_origin_utc"]


def zero_return(fields: Mapping[str, object], *, sample: str) -> Prediction:
    _sample(sample)
    _forecast_origin(fields)
    return Prediction(0.0)


def prepare_mean_history(
    labels: Sequence[HistoricalTarget], *, origin: datetime, sample: str
) -> MeanHistory:
    """Apply closure/sample flags without discarding eligible numeric failures.

    target_valid=False excludes a row regardless of its numeric value.
    Eligible target_valid=True rows retain finite, nonfinite, or missing
    values. Once the unchanged 720-label minimum is met, predict_mean either
    computes the finite mean or explicitly abstains with nonfinite_prediction.
    """
    _sample(sample)
    protocol.require_evaluation_origin(origin)
    selected = []
    seen = set()
    for label in sorted(labels, key=lambda item: item.label_origin):
        if label.label_origin in seen:
            raise ValueError("duplicate historical label origin")
        seen.add(label.label_origin)
        if protocol.historical_target_eligible(
            sample,
            label_origin=label.label_origin,
            current_origin=origin,
            target_valid=label.target_valid,
            target_manifest_anomaly=label.target_manifest_anomaly,
        ):
            selected.append(label)
    return MeanHistory(origin, sample, tuple(selected))


def predict_mean(fields: Mapping[str, object], history: MeanHistory) -> Prediction:
    origin = _forecast_origin(fields)
    if history.cutoff != origin:
        raise ValueError("mean history must be prepared for this hourly origin")
    # Revalidate admitted rows so direct construction cannot bypass the cutoff.
    checked = prepare_mean_history(history.labels, origin=origin, sample=history.sample)
    if checked != history:
        raise ValueError("mean history is not canonical eligible history")
    if not protocol.history_requirement_met("expanding_mean", len(history.labels)):
        return Prediction(None, "insufficient_training_history")
    try:
        value = _finite(
            math.fsum(_finite(row.value) for row in history.labels)
            / len(history.labels)
        )
        return Prediction(value)
    except (ArithmeticError, ValueError):
        return Prediction(None, "nonfinite_prediction")


def _index(candles: Sequence[CloseObservation]) -> dict[datetime, CloseObservation]:
    result = {}
    for candle in sorted(candles, key=lambda item: item.candle_open):
        protocol.validate_hour(candle.candle_open)
        if candle.candle_open in result:
            raise ValueError("duplicate candle open")
        result[candle.candle_open] = candle
    return result


def _return(previous: CloseObservation, current: CloseObservation) -> float | None:
    if current.candle_open - previous.candle_open != HOUR:
        raise ValueError("return endpoints must be consecutive hours")
    for candle in (previous, current):
        _bool(candle.valid)
        if not candle.valid:
            return None
    before, after = _finite(previous.close), _finite(current.close)
    if before <= 0 or after <= 0:
        return None
    return _finite(math.log(after) - math.log(before))


def prepare_ar_history(
    candles: Sequence[CloseObservation], *, origin: datetime, sample: str
) -> ARHistory:
    _sample(sample)
    protocol.require_evaluation_origin(origin)
    by_open = _index(candles)
    pairs = []
    for s in by_open:
        # Cutoff precedes all access to the three candles' values/quality flags.
        if not protocol.label_completed(s + HOUR, origin):
            continue
        triple = [by_open.get(s - HOUR), by_open[s], by_open.get(s + HOUR)]
        if any(candle is None for candle in triple):
            continue
        previous, current, following = triple
        for candle in triple:
            _bool(candle.valid)
            _bool(candle.manifest_anomaly)
        valid = all(candle.valid for candle in triple)
        if not protocol.historical_row_eligible(
            "ar_1",
            sample,
            label_origin=s + HOUR,
            current_origin=origin,
            target_valid=valid,
            target_manifest_anomaly=current.manifest_anomaly
            or following.manifest_anomaly,
            ar_lag_valid=valid,
            ar_lag_manifest_anomaly=previous.manifest_anomaly
            or current.manifest_anomaly,
        ):
            continue
        try:
            lag, target = _return(previous, current), _return(current, following)
        except (ArithmeticError, ValueError):
            return ARHistory(origin, sample, tuple(pairs), True)
        if lag is not None and target is not None:
            pairs.append(ARPair(s, lag, target))
    return ARHistory(origin, sample, tuple(pairs))


def fit_ar(history: ARHistory) -> ARFit:
    """A fit attempt replaces prior state, including failed attempts."""
    _sample(history.sample)
    if not protocol.refit_scheduled("ar_1", history.cutoff):
        raise ValueError("AR fitting is scheduled at 00:00 UTC only")
    pairs = sorted(history.pairs, key=lambda item: item.feature_open)
    seen = set()
    for pair in pairs:
        protocol.validate_hour(pair.feature_open)
        if pair.feature_open in seen:
            raise ValueError("duplicate AR pair")
        seen.add(pair.feature_open)
        if not protocol.label_completed(pair.feature_open + HOUR, history.cutoff):
            raise ValueError("AR pair outcome exceeds fit cutoff")
    count = len(pairs)
    maximum = max((p.feature_open + 2 * HOUR for p in pairs), default=None)

    def failed(reason):
        return ARFit(history.cutoff, history.sample, count, maximum, None, None, reason)

    if history.numerical_failure:
        return failed("ar_numerical_failure")
    try:
        for pair in pairs:
            _finite(pair.lag)
            _finite(pair.target)
        if not protocol.history_requirement_met("ar_1", count):
            return failed("insufficient_training_history")
        x_bar = _finite(math.fsum(p.lag for p in pairs) / count)
        y_bar = _finite(math.fsum(p.target for p in pairs) / count)
        dx = [_finite(p.lag - x_bar) for p in pairs]
        dy = [_finite(p.target - y_bar) for p in pairs]
        sxx = _finite(math.fsum(_finite(x * x) for x in dx))
        sxy = _finite(math.fsum(_finite(x * y) for x, y in zip(dx, dy, strict=True)))
        if _finite(sxx / count) <= 1e-16:
            return failed("ar_ill_conditioned_lag")
        slope = _finite(sxy / sxx)
        intercept = _finite(y_bar - _finite(slope * x_bar))
        return ARFit(
            history.cutoff, history.sample, count, maximum, intercept, slope, None
        )
    except (ArithmeticError, ValueError):
        return failed("ar_numerical_failure")


def prepare_current_lag(
    candles: Sequence[CloseObservation], fields: Mapping[str, object], *, sample: str
) -> CurrentLag:
    _sample(sample)
    origin = _forecast_origin(fields)
    t = origin - HOUR
    by_open = _index(candles)
    previous, current = by_open.get(t - HOUR), by_open.get(t)
    reason = "ar_lag_missing_or_invalid"
    if previous is None or current is None:
        return CurrentLag(origin, sample, None, reason)
    try:
        value = _return(previous, current)
    except (ArithmeticError, ValueError):
        value = None
    if value is None:
        return CurrentLag(origin, sample, None, reason)
    for candle in (previous, current):
        _bool(candle.manifest_anomaly)
    if sample == "a_sensitivity" and (
        previous.manifest_anomaly or current.manifest_anomaly
    ):
        return CurrentLag(origin, sample, None, "ar_lag_manifest_anomaly")
    return CurrentLag(origin, sample, value)


def predict_ar(fields: Mapping[str, object], fit: ARFit, lag: CurrentLag) -> Prediction:
    origin = _forecast_origin(fields)
    _sample(fit.sample)
    if not protocol.refit_scheduled("ar_1", fit.scheduled_at):
        raise ValueError("fit must belong to a scheduled midnight event")
    if fit.max_outcome_close is not None:
        protocol.validate_hour(fit.max_outcome_close)
        if fit.max_outcome_close > fit.scheduled_at:
            raise ValueError("fit provenance exceeds historical outcome cutoff")
    if lag.origin != origin or lag.sample != fit.sample:
        raise ValueError("current lag origin/sample differs from forecast fit")
    if lag.reason is not None:
        return Prediction(None, lag.reason)
    # A skipped midnight refit cannot extend yesterday's parameters.
    if fit.scheduled_at != origin.replace(hour=0):
        return Prediction(None, "insufficient_training_history")
    if fit.reason is not None:
        return Prediction(None, fit.reason)
    if not protocol.history_requirement_met("ar_1", fit.history_count):
        return Prediction(None, "insufficient_training_history")
    try:
        value = _finite(
            _finite(fit.intercept) + _finite(_finite(fit.slope) * _finite(lag.value))
        )
        return Prediction(value)
    except (ArithmeticError, ValueError):
        return Prediction(None, "ar_numerical_failure")
