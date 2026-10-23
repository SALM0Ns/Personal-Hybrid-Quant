"""Pure, synthetic-first seven-feature Ridge under qnt-003d-design-v1.

No market-data reader, artifact writer, trading interface, or historical run.
Householder QR solves the augmented least-squares objective directly rather
than squaring its condition number through normal equations. Numerical failure
is explicit; there is no solver, penalty, scaler, or imputation fallback.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from quant.features.engine import FEATURES
from quant.research import evaluation_protocol as protocol
from quant.research.forecast_dataset import TEST_START, VALIDATION_START
from quant.research.statistical_baselines import Prediction

HOUR = protocol.HOUR
ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)
FOLDS = (
    (VALIDATION_START, datetime(2024, 5, 1, tzinfo=UTC)),
    (datetime(2024, 5, 1, tzinfo=UTC), datetime(2024, 9, 1, tzinfo=UTC)),
    (datetime(2024, 9, 1, tzinfo=UTC), TEST_START),
)
RESEARCH_ONLY = True
POINT_IN_TIME_VERIFIED = False
FIT_FAILURE_REASONS = frozenset(
    {"insufficient_training_history", "ridge_numerical_failure"}
)
PREDICTION_FAILURE_REASONS = frozenset(
    {
        *FIT_FAILURE_REASONS,
        "nonfinite_prediction",
        *(f"feature_null__{name}" for name in FEATURES),
        *(f"feature_manifest_anomaly__{name}" for name in FEATURES),
    }
)


class ValidationDataIntegrityError(ValueError):
    """A validation target marked valid contradicts its numeric value."""


def _validation_target(row: "ResearchRow") -> float:
    try:
        return _finite(row.target)
    except ArithmeticError as exc:
        raise ValidationDataIntegrityError(
            "validation target marked valid must be finite at "
            f"{row.label_origin.isoformat()}"
        ) from exc


def _finite(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ArithmeticError("nonfinite Ridge input or intermediate")
    return float(value)


def _sample(value: str) -> None:
    if value not in protocol.SAMPLES:
        raise ValueError("unknown Lane A sample")


def _flag(value: bool) -> None:
    if type(value) is not bool:
        raise ValueError("quality flags must be Booleans")


def _alpha(value: float) -> None:
    if type(value) not in (int, float) or value not in ALPHAS:
        raise ValueError("alpha must belong to the fixed approved grid")


def feature_vector(fields: Mapping[str, object]) -> tuple[float, ...]:
    """Exact seven-field schema, ordered by the existing feature contract."""
    if set(fields) != set(FEATURES):
        raise ValueError("exact seven-feature schema required")
    return tuple(fields[name] for name in FEATURES)


def _complete(values: tuple) -> bool:
    return all(type(v) in (int, float) and math.isfinite(v) for v in values)


@dataclass(frozen=True)
class ResearchRow:
    label_origin: datetime
    features: tuple[float | None, ...]
    target: float | None
    target_valid: bool = True
    target_manifest_anomaly: bool = False
    feature_manifest_anomaly: bool = False

    def __post_init__(self) -> None:
        protocol.validate_hour(self.label_origin)
        if type(self.features) is not tuple or len(self.features) != len(FEATURES):
            raise ValueError("features must be a tuple in seven-feature contract order")
        # Values and flags are read only after their historical cutoff.


@dataclass(frozen=True)
class History:
    cutoff: datetime
    sample: str
    rows: tuple[ResearchRow, ...]


@dataclass(frozen=True)
class Scaler:
    means: tuple[float, ...]
    scales: tuple[float, ...]

    def __post_init__(self) -> None:
        if (
            type(self.means) is not tuple
            or type(self.scales) is not tuple
            or len(self.means) != 7
            or len(self.scales) != 7
        ):
            raise ValueError("scaler must contain seven means/scales")
        if not _complete(self.means) or not _complete(self.scales):
            raise ValueError("scaler must be finite")
        if any(scale <= 0 for scale in self.scales):
            raise ValueError("scales must be positive")


@dataclass(frozen=True)
class Fit:
    scheduled_at: datetime
    sample: str
    alpha: float
    history_count: int
    max_outcome_close: datetime | None
    scaler: Scaler | None
    intercept: float | None
    coefficients: tuple[float, ...] | None
    reason: str | None = None

    def __post_init__(self) -> None:
        _sample(self.sample)
        _alpha(self.alpha)
        if not protocol.refit_scheduled("ridge_7", self.scheduled_at):
            raise ValueError("Ridge fit requires scheduled midnight")
        if type(self.history_count) is not int or self.history_count < 0:
            raise ValueError("invalid training count")
        if self.max_outcome_close is not None:
            protocol.validate_hour(self.max_outcome_close)
            if self.max_outcome_close > self.scheduled_at:
                raise ValueError("fit outcome exceeds cutoff")
        if self.reason is not None:
            if self.reason not in FIT_FAILURE_REASONS:
                raise ValueError("unknown Ridge failure")
            if any(
                v is not None for v in (self.scaler, self.intercept, self.coefficients)
            ):
                raise ValueError("failed fits must not carry parameters")
        elif (
            self.history_count < 720
            or self.max_outcome_close is None
            or not isinstance(self.scaler, Scaler)
            or type(self.coefficients) is not tuple
            or len(self.coefficients) != 7
            or not _complete(self.coefficients)
            or not _complete((self.intercept,))
        ):
            raise ValueError("successful fit requires finite parameters and provenance")


def _ordered(rows: Sequence[ResearchRow]) -> tuple[ResearchRow, ...]:
    ordered = tuple(sorted(rows, key=lambda row: row.label_origin))
    if len({r.label_origin for r in ordered}) != len(ordered):
        raise ValueError("duplicate research origin")
    return ordered


def prepare_history(
    rows: Sequence[ResearchRow], *, origin: datetime, sample: str
) -> History:
    protocol.require_evaluation_origin(origin)
    _sample(sample)
    selected = []
    for row in _ordered(rows):
        if not protocol.label_completed(row.label_origin, origin):
            continue
        if protocol.historical_row_eligible(
            "ridge_7",
            sample,
            label_origin=row.label_origin,
            current_origin=origin,
            target_valid=row.target_valid,
            target_manifest_anomaly=row.target_manifest_anomaly,
            feature_complete=_complete(row.features),
            feature_manifest_anomaly=row.feature_manifest_anomaly,
        ):
            selected.append(row)
    return History(origin, sample, tuple(selected))


def fit_scaler(values: Sequence[tuple[float, ...]]) -> Scaler:
    """Training-only population SD; hypot avoids squaring raw deviations."""
    if not values or any(len(row) != 7 for row in values):
        raise ValueError("nonempty seven-column training matrix required")
    means = []
    scales = []
    for j in range(7):
        column = [_finite(row[j]) for row in values]
        mean = _finite(math.fsum(column) / len(column))
        deviations = [_finite(value - mean) for value in column]
        scale = _finite(math.hypot(*deviations) / math.sqrt(len(column)))
        means.append(mean)
        scales.append(1.0 if scale == 0.0 else scale)
    return Scaler(tuple(means), tuple(scales))


def standardize(values: tuple[float, ...], scaler: Scaler) -> tuple[float, ...]:
    if len(values) != 7:
        raise ValueError("seven features required")
    return tuple(
        _finite(_finite(_finite(x) - mu) / scale)
        for x, mu, scale in zip(values, scaler.means, scaler.scales, strict=True)
    )


def _qr_solve(matrix: list[list[float]], rhs: list[float]) -> tuple[float, ...]:
    """Eight-column Householder QR with unit reflectors and binary64 checks.

    Fail on a diagonal <=64 eps times the largest original column norm.
    This is a numerical rank guard, not a changed statistical penalty.
    The positive-alpha augmentation gives full rank even with collinearity.
    """
    width = 8
    matrix_scale = max(
        _finite(math.hypot(*(r[j] for r in matrix))) for j in range(width)
    )
    tolerance = 64 * math.ulp(1.0) * matrix_scale
    for k in range(width):
        column = [r[k] for r in matrix[k:]]
        norm = _finite(math.hypot(*column))
        if norm <= tolerance:
            raise ArithmeticError("numerically rank-deficient augmented system")
        v = [_finite(x / norm) for x in column]
        v[0] = _finite(v[0] + math.copysign(1.0, v[0]))
        vn = _finite(math.hypot(*v))
        v = [_finite(x / vn) for x in v]
        for j in range(k, width):
            dot = _finite(
                2 * math.fsum(_finite(v[i] * matrix[k + i][j]) for i in range(len(v)))
            )
            for i in range(len(v)):
                matrix[k + i][j] = _finite(matrix[k + i][j] - _finite(dot * v[i]))
        dot = _finite(2 * math.fsum(_finite(v[i] * rhs[k + i]) for i in range(len(v))))
        for i in range(len(v)):
            rhs[k + i] = _finite(rhs[k + i] - _finite(dot * v[i]))
    result = [0.0] * width
    for k in reversed(range(width)):
        if abs(matrix[k][k]) <= tolerance:
            raise ArithmeticError("unsafe QR diagonal")
        tail = _finite(
            math.fsum(_finite(matrix[k][j] * result[j]) for j in range(k + 1, width))
        )
        result[k] = _finite(_finite(rhs[k] - tail) / matrix[k][k])
    return tuple(result)


def fit_ridge(
    history: History, *, alpha: float, selection: "AlphaSelection | None" = None
) -> Fit:
    _alpha(alpha)
    if not protocol.refit_scheduled("ridge_7", history.cutoff):
        raise ValueError("Ridge refits are midnight only")
    if history.cutoff >= TEST_START and (
        not isinstance(selection, AlphaSelection) or selection.selected_alpha != alpha
    ):
        raise ValueError("test refits require the frozen validation-selected alpha")
    if history.cutoff >= TEST_START and selection.analysis_as_of > history.cutoff:
        raise ValueError("alpha selection analysis boundary exceeds test fit cutoff")
    checked = prepare_history(
        history.rows, origin=history.cutoff, sample=history.sample
    )
    if checked != history:
        raise ValueError("noncanonical or ineligible training history")
    count = len(history.rows)
    maximum = max((row.label_origin + HOUR for row in history.rows), default=None)

    def failed(reason):
        return Fit(
            history.cutoff,
            history.sample,
            float(alpha),
            count,
            maximum,
            None,
            None,
            None,
            reason,
        )

    if not protocol.history_requirement_met("ridge_7", count):
        return failed("insufficient_training_history")
    try:
        y = [_finite(row.target) for row in history.rows]
        scaler = fit_scaler([row.features for row in history.rows])
        matrix = [[1.0, *standardize(row.features, scaler)] for row in history.rows]
        # Seven penalty rows, no penalty on the intercept column.
        matrix.extend(
            [
                [0.0, *[math.sqrt(alpha) if j == k else 0.0 for j in range(7)]]
                for k in range(7)
            ]
        )
        beta = _qr_solve(matrix, y + [0.0] * 7)
        return Fit(
            history.cutoff,
            history.sample,
            float(alpha),
            count,
            maximum,
            scaler,
            beta[0],
            beta[1:],
        )
    except (ArithmeticError, ValueError):
        return failed("ridge_numerical_failure")


def predict(fields: Mapping[str, object], fit: Fit) -> Prediction:
    protocol.validate_forecast_fields(fields)
    for name in FEATURES:
        if name not in fields or not _complete((fields[name],)):
            return Prediction(None, f"feature_null__{name}")
    if fit.sample == "a_sensitivity":
        if "feature_manifest_anomaly" not in fields:
            raise ValueError("sensitivity prediction requires feature anomaly metadata")
        _flag(fields["feature_manifest_anomaly"])
        if fields["feature_manifest_anomaly"]:
            involved = fields.get("anomaly_involved_features")
            if not involved or not set(involved) <= set(FEATURES):
                raise ValueError("missing/inconsistent anomaly feature references")
            return Prediction(
                None,
                next(
                    f"feature_manifest_anomaly__{f}" for f in FEATURES if f in involved
                ),
            )
    origin = fields["forecast_origin_utc"]
    if fit.scheduled_at != origin.replace(hour=0):
        return Prediction(None, "insufficient_training_history")
    if fit.reason is not None:
        return Prediction(None, fit.reason)
    try:
        z = standardize(tuple(fields[f] for f in FEATURES), fit.scaler)
        value = _finite(
            fit.intercept
            + math.fsum(
                _finite(x * b) for x, b in zip(z, fit.coefficients, strict=True)
            )
        )
        return Prediction(value)
    except (ArithmeticError, ValueError):
        return Prediction(None, "ridge_numerical_failure")


def validation_fold(origin: datetime) -> int | None:
    protocol.validate_hour(origin)
    return next(
        (i for i, (start, end) in enumerate(FOLDS, 1) if start <= origin < end), None
    )


def frozen_validation_origins(
    rows: Sequence[ResearchRow], *, analysis_as_of: datetime
) -> tuple[datetime, ...]:
    protocol.validate_hour(analysis_as_of)
    if analysis_as_of < TEST_START:
        raise ValueError("full 2024 validation outcomes must have theoretically closed")
    candidates = []
    counts = {}
    for row in _ordered(rows):
        if validation_fold(row.label_origin) is None:
            continue  # Test-period outcomes are not inspected.
        _flag(row.target_valid)
        if not row.target_valid:
            continue
        # Data integrity is checked even for incomplete-feature/cold-start rows.
        # It cannot silently redefine the frozen validation denominator.
        _validation_target(row)
        if not _complete(row.features):
            continue
        midnight = row.label_origin.replace(hour=0)
        if midnight not in counts:
            counts[midnight] = len(
                prepare_history(rows, origin=midnight, sample="a_primary").rows
            )
        if counts[midnight] >= 720:
            candidates.append(row.label_origin)
    return tuple(candidates)


def pooled_rmse(errors: Sequence[float]) -> float:
    """One denominator over pooled validation origins, never fold-average RMSE."""
    if not errors:
        raise ValueError("empty validation error set")
    return _finite(math.hypot(*[_finite(e) for e in errors]) / math.sqrt(len(errors)))


@dataclass(frozen=True)
class CandidateResult:
    alpha: float
    rmse: float | None
    failures: tuple[tuple[datetime, str], ...]
    fit_failures: tuple[tuple[datetime, str], ...] = ()

    def __post_init__(self) -> None:
        _alpha(self.alpha)
        if self.rmse is not None and (_finite(self.rmse) < 0 or self.failures):
            raise ValueError("invalid or failed candidate score")
        if tuple(sorted(set(self.failures))) != self.failures:
            raise ValueError("failure records must be sorted unique")
        for origin, reason in self.failures:
            if (
                validation_fold(origin) is None
                or reason not in PREDICTION_FAILURE_REASONS
            ):
                raise ValueError(
                    "candidate failure must identify a 2024 Ridge abstention"
                )
        if tuple(sorted(set(self.fit_failures))) != self.fit_failures:
            raise ValueError("fit failure records must be sorted unique")
        for scheduled_at, reason in self.fit_failures:
            if (
                validation_fold(scheduled_at) is None
                or scheduled_at.hour != 0
                or reason not in FIT_FAILURE_REASONS
            ):
                raise ValueError("invalid validation refit failure record")
        if self.fit_failures and (self.rmse is not None or not self.failures):
            raise ValueError("failed refits must disqualify the candidate")


@dataclass(frozen=True)
class AlphaSelection:
    """Immutable tuning result; analysis_as_of is a theoretical data boundary."""

    candidate_origins: tuple[datetime, ...]
    candidates: tuple[CandidateResult, ...]
    selected_alpha: float | None
    analysis_as_of: datetime

    def __post_init__(self) -> None:
        protocol.validate_hour(self.analysis_as_of)
        if self.analysis_as_of < TEST_START:
            raise ValueError("selection requires complete validation outcomes")
        if tuple(sorted(set(self.candidate_origins))) != self.candidate_origins:
            raise ValueError("candidate origins must be sorted unique")
        if any(validation_fold(o) is None for o in self.candidate_origins):
            raise ValueError("selection origins must be confined to 2024")
        if tuple(c.alpha for c in self.candidates) != ALPHAS:
            raise ValueError("selection must report every approved alpha")
        valid = []
        for candidate in self.candidates:
            if any(
                origin not in self.candidate_origins for origin, _ in candidate.failures
            ):
                raise ValueError("failure outside frozen candidate set")
            if candidate.failures:
                if candidate.rmse is not None:
                    raise ValueError("failed candidates cannot have selection scores")
            elif self.candidate_origins:
                if _finite(candidate.rmse) < 0:
                    raise ValueError("invalid RMSE")
                valid.append(candidate)
            elif candidate.rmse is not None:
                raise ValueError("empty validation set cannot be scored")
        expected = min(valid, key=lambda c: (c.rmse, c.alpha)).alpha if valid else None
        if self.selected_alpha != expected:
            raise ValueError("selected alpha disagrees with pooled-RMSE/tie rule")


def select_alpha(
    rows: Sequence[ResearchRow], *, analysis_as_of: datetime
) -> AlphaSelection:
    """A-primary validation only; no test scoring or historical I/O.

    Operates only on supplied in-memory rows. Candidate membership is frozen
    before any candidate fit. Failures retain timestamps and disqualify the
    entire alpha; failed origins are never dropped for a better denominator.
    """
    ordered = _ordered(rows)
    origins = frozen_validation_origins(ordered, analysis_as_of=analysis_as_of)
    by_origin = {row.label_origin: row for row in ordered}
    results = []
    for alpha in ALPHAS:
        fits = {}
        errors = []
        failures = []
        fit_failures = []
        for origin in origins:
            midnight = origin.replace(hour=0)
            if midnight not in fits:
                fits[midnight] = fit_ridge(
                    prepare_history(ordered, origin=midnight, sample="a_primary"),
                    alpha=alpha,
                )
                if fits[midnight].reason is not None:
                    fit_failures.append((midnight, fits[midnight].reason))
            row = by_origin[origin]
            fields = {
                "feature_open_t": origin - HOUR,
                "forecast_origin_utc": origin,
                **dict(zip(FEATURES, row.features, strict=True)),
            }
            prediction = predict(fields, fits[midnight])
            if prediction.reason is not None:
                failures.append((origin, prediction.reason))
            else:
                try:
                    errors.append(_finite(prediction.value - _validation_target(row)))
                except ArithmeticError:
                    failures.append((origin, "ridge_numerical_failure"))
        score = None
        if origins and not failures:
            try:
                score = pooled_rmse(errors)
            except ArithmeticError:
                failures.append((origins[-1], "ridge_numerical_failure"))
        results.append(
            CandidateResult(alpha, score, tuple(failures), tuple(fit_failures))
        )
    valid = [r for r in results if r.rmse is not None and not r.failures]
    winner = min(valid, key=lambda r: (r.rmse, r.alpha)).alpha if valid else None
    return AlphaSelection(origins, tuple(results), winner, analysis_as_of)
