"""Pure Lane A protocol checks; no fitting, predictions, scoring, or I/O.

All closure times are theoretical. These helpers establish no historical
publication evidence and cannot enable Lane B or trading eligibility.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from quant.research.forecast_dataset import (
    DATASET_CONTRACT_VERSION,
    FORECAST_SIDE_COLUMNS,
    PROTOCOL_VERSION,
    split_id,
)

HOUR = timedelta(hours=1)
RESEARCH_ONLY = True
POINT_IN_TIME_VERIFIED = False
METHODS = frozenset({"zero_return", "expanding_mean", "ar_1", "ridge_7"})
SAMPLES = frozenset({"a_primary", "a_sensitivity"})
FORECAST_STATUSES = frozenset({"emitted", "abstained"})
SCORE_STATUSES = frozenset(
    {"scored", "emitted_but_not_scored", "not_scored_no_forecast"}
)
FORECAST_FIELDS = frozenset(FORECAST_SIDE_COLUMNS)


def validate_versions(protocol: str, dataset_contract: str) -> None:
    if protocol != PROTOCOL_VERSION or dataset_contract != DATASET_CONTRACT_VERSION:
        raise ValueError("protocol or dataset-contract version mismatch")


def validate_hour(value: datetime) -> None:
    """Accept aware, hour-aligned datetimes with zero offset at that instant.

    This is UTC-equivalence, matching PQTA-003C's require_utc validator;
    neither a particular tzinfo identity nor a timezone name is required.
    """
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
        or value.minute
        or value.second
        or value.microsecond
    ):
        raise ValueError("timestamp must be an aware, hour-aligned UTC datetime")


@dataclass(frozen=True)
class OriginTimes:
    feature_open: datetime
    feature_close: datetime
    forecast_origin: datetime
    target_open: datetime
    target_close: datetime

    def __post_init__(self) -> None:
        for value in vars(self).values():
            validate_hour(value)
        if not (
            self.feature_open + HOUR == self.feature_close == self.forecast_origin
            and self.target_open == self.forecast_origin
            and self.target_close == self.forecast_origin + HOUR
        ):
            raise ValueError("inconsistent forecast-origin timeline")


def evaluation_split(origin: datetime) -> str:
    """Delegate boundaries to the approved origin-dataset contract."""
    validate_hour(origin)
    return split_id(origin)


def require_evaluation_origin(origin: datetime) -> None:
    if evaluation_split(origin) == "outside_approved_evaluation_window":
        raise ValueError("outside approved evaluation window; audit only")


def label_completed(label_origin: datetime, current_origin: datetime) -> bool:
    validate_hour(label_origin)
    validate_hour(current_origin)
    return label_origin + HOUR <= current_origin


def _boolean(value: bool) -> None:
    if type(value) is not bool:
        raise ValueError("policy flags must be non-null Booleans")


def _sample(sample: str) -> None:
    if sample not in SAMPLES:
        raise ValueError("unknown Lane A sample")


def _method(method: str) -> None:
    if method not in METHODS:
        raise ValueError("unknown method")


def historical_target_eligible(
    sample: str,
    *,
    label_origin: datetime,
    current_origin: datetime,
    target_valid: bool,
    target_manifest_anomaly: bool,
) -> bool:
    """Select completed history, never current-origin forecast emission.

    Incomplete labels return False without validating or evaluating outcome
    flags. Completed labels require both flags to be actual Booleans.
    """
    _sample(sample)
    if not label_completed(label_origin, current_origin):
        return False
    _boolean(target_valid)
    _boolean(target_manifest_anomaly)
    return target_valid and (sample == "a_primary" or not target_manifest_anomaly)


def historical_row_eligible(
    method: str,
    sample: str,
    *,
    label_origin: datetime,
    current_origin: datetime,
    target_valid: bool,
    target_manifest_anomaly: bool,
    feature_complete: bool = False,
    feature_manifest_anomaly: bool = False,
    ar_lag_valid: bool = False,
    ar_lag_manifest_anomaly: bool = False,
) -> bool:
    """One completed target/pair/feature row; never an aggregate count.

    AR pair validity combines the exact previous/current lag with the exact
    current/next target. Its two anomaly masks cover all three candle opens.
    Zero Return has no training rows.
    """
    _method(method)
    eligible = historical_target_eligible(
        sample,
        label_origin=label_origin,
        current_origin=current_origin,
        target_valid=target_valid,
        target_manifest_anomaly=target_manifest_anomaly,
    )
    if not eligible or method == "zero_return":
        return False
    if method == "ar_1":
        _boolean(ar_lag_valid)
        _boolean(ar_lag_manifest_anomaly)
        return ar_lag_valid and (sample == "a_primary" or not ar_lag_manifest_anomaly)
    if method == "ridge_7":
        _boolean(feature_complete)
        _boolean(feature_manifest_anomaly)
        return feature_complete and (
            sample == "a_primary" or not feature_manifest_anomaly
        )
    return True


def history_requirement_met(method: str, eligible_count: int) -> bool:
    """Count must already use historical_row_eligible, not raw row count."""
    _method(method)
    if type(eligible_count) is not int or eligible_count < 0:
        raise ValueError("eligible history count must be a nonnegative integer")
    return method == "zero_return" or eligible_count >= 720


def refit_scheduled(method: str, origin: datetime) -> bool:
    _method(method)
    require_evaluation_origin(origin)
    return method in {"ar_1", "ridge_7"} and origin.hour == 0


def hourly_update_due(method: str, origin: datetime) -> bool:
    _method(method)
    require_evaluation_origin(origin)
    return method == "expanding_mean"


def validate_forecast_fields(fields: Mapping[str, object]) -> None:
    """Accept a subset of the existing forecast_side_view, fail on extras.

    Callers must use the separate completed-history interface for labels.
    This validates the boundary, not all optional Gold metadata values.
    """
    if set(fields) - FORECAST_FIELDS:
        raise ValueError("forbidden forecast-time fields")
    if not {"feature_open_t", "forecast_origin_utc"} <= fields.keys():
        raise ValueError("missing forecast time keys")
    t, origin = fields["feature_open_t"], fields["forecast_origin_utc"]
    validate_hour(t)
    require_evaluation_origin(origin)
    if t + HOUR != origin:
        raise ValueError("inconsistent feature open and forecast origin")
    if "split_id" in fields and fields["split_id"] != evaluation_split(origin):
        raise ValueError("split identity mismatch")
    if "research_only" in fields and fields["research_only"] is not True:
        raise ValueError("forecast interface is research only")


def forecast_inputs_eligible(
    method: str, sample: str, fields: Mapping[str, object]
) -> bool:
    """Current-input eligibility only; history and fit state remain separate.

    A True result never implies a finite forecast, scoreability, publication,
    or decision eligibility. No target-side field is accepted.
    """
    _method(method)
    _sample(sample)
    validate_forecast_fields(fields)
    if method in {"zero_return", "expanding_mean"}:
        return True
    valid_key, anomaly_key = (
        ("ar_lag_valid", "ar_lag_manifest_anomaly")
        if method == "ar_1"
        else ("feature_complete", "feature_manifest_anomaly")
    )
    if valid_key not in fields or anomaly_key not in fields:
        raise ValueError("missing method input flags")
    _boolean(fields[valid_key])
    _boolean(fields[anomaly_key])
    return fields[valid_key] and (sample == "a_primary" or not fields[anomaly_key])


@dataclass(frozen=True)
class ForecastState:
    """Immutable status contract only; contains no forecast value or ledger."""

    origin: datetime
    status: str

    def __post_init__(self) -> None:
        require_evaluation_origin(self.origin)
        if self.status not in FORECAST_STATUSES:
            raise ValueError("unknown forecast status")


def validate_score_state(
    forecast: ForecastState, score_status: str, *, checked_at: datetime
) -> None:
    """Validate final classifications; there is no intermediate pending state.

    Both emitted-forecast outcomes require theoretical target closure.
    An abstention can be classified not_scored_no_forecast at its origin
    because that classification does not depend on the future outcome.
    """
    validate_hour(checked_at)
    if score_status not in SCORE_STATUSES:
        raise ValueError("unknown score status")
    if (forecast.status == "abstained") != (score_status == "not_scored_no_forecast"):
        raise ValueError("incompatible forecast and score statuses")
    if checked_at < forecast.origin:
        raise ValueError("status check precedes forecast origin")
    if score_status != "not_scored_no_forecast" and checked_at < forecast.origin + HOUR:
        raise ValueError("outcome status precedes target close")


def validate_emission_unchanged(forecast: ForecastState, status: str) -> None:
    if status != forecast.status:
        raise ValueError("ex-post scoreability cannot change emission status")


def validate_counts(
    *,
    origins: int,
    emitted: int,
    abstained: int,
    scored: int,
    emitted_but_not_scored: int,
    not_scored_no_forecast: int,
) -> None:
    counts = (
        origins,
        emitted,
        abstained,
        scored,
        emitted_but_not_scored,
        not_scored_no_forecast,
    )
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("counts must be nonnegative integers")
    if not (
        origins == emitted + abstained
        and emitted == scored + emitted_but_not_scored
        and abstained == not_scored_no_forecast
    ):
        raise ValueError("forecast/score conservation failure")
