"""Analytic/synthetic Ridge verification; never reads historical market data."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from quant.research import ridge_regression as r
from quant.research.statistical_baselines import Prediction

H = timedelta(hours=1)
ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)


def vector(i):
    # Seven balanced orthogonal columns: nonconstant Walsh characters on 3 bits.
    return tuple(float((-1) ** ((i & mask).bit_count())) for mask in range(1, 8))


def rows(n=720):
    return [
        r.ResearchRow(ORIGIN - (n - i) * H, vector(i), 3.0 + 2 * vector(i)[0])
        for i in range(n)
    ]


def history(source=None, origin=ORIGIN, sample="a_primary"):
    return r.prepare_history(
        rows() if source is None else source, origin=origin, sample=sample
    )


def fields(origin=ORIGIN, values=None, **extra):
    return {
        "feature_open_t": origin - H,
        "forecast_origin_utc": origin,
        **dict(zip(r.FEATURES, vector(0) if values is None else values, strict=True)),
        **extra,
    }


def validation_rows():
    # Zero-feature intercept-only model gives exact alpha ties.
    training = [replace(row, features=(0.0,) * 7, target=0.0) for row in rows()]
    return training + [
        r.ResearchRow(o, (0.0,) * 7, 0.0)
        for o in (
            ORIGIN,
            datetime(2024, 5, 1, tzinfo=UTC),
            datetime(2024, 9, 1, tzinfo=UTC),
        )
    ]


@pytest.mark.parametrize("alpha", r.ALPHAS)
def test_known_orthogonal_solution_sum_objective(alpha):
    fit = r.fit_ridge(history(), alpha=alpha)
    assert fit.reason is None
    assert fit.scaler.means == pytest.approx((0.0,) * 7, abs=1e-15)
    assert fit.scaler.scales == pytest.approx((1.0,) * 7)
    assert fit.intercept == pytest.approx(3.0, abs=1e-12)
    assert fit.coefficients == pytest.approx(
        (1440 / (720 + alpha), 0, 0, 0, 0, 0, 0), abs=1e-12
    )


def test_intercept_unpenalized_and_constant_columns_scale_one():
    source = [replace(row, features=(5.0,) * 7, target=12.0) for row in rows()]
    fit = r.fit_ridge(history(source), alpha=100.0)
    assert fit.scaler.scales == (1.0,) * 7
    assert fit.coefficients == pytest.approx((0.0,) * 7, abs=1e-12)
    assert fit.intercept == pytest.approx(12.0, abs=1e-12)
    assert r.predict(fields(values=(5.0,) * 7), fit).value == pytest.approx(12.0)


def test_exact_collinearity_stable_augmented_qr():
    source = [
        replace(row, features=(row.features[0],) * 7, target=2 * row.features[0])
        for row in rows()
    ]
    fit = r.fit_ridge(history(source), alpha=0.01)
    assert fit.reason is None
    assert fit.coefficients == pytest.approx((1440 / (5040 + 0.01),) * 7, abs=1e-10)


def test_stationarity_of_approved_objective_independent_check():
    training = history()
    fit = r.fit_ridge(training, alpha=10.0)
    z = [r.standardize(row.features, fit.scaler) for row in training.rows]
    errors = [
        fit.intercept
        + sum(b * x for b, x in zip(fit.coefficients, v, strict=True))
        - row.target
        for row, v in zip(training.rows, z, strict=True)
    ]
    assert math.fsum(errors) == pytest.approx(0.0, abs=1e-9)
    for j in range(7):
        assert math.fsum(
            e * v[j] for e, v in zip(errors, z, strict=True)
        ) + 10 * fit.coefficients[j] == pytest.approx(0.0, abs=1e-9)


def test_population_sd_and_training_only_statistics():
    scaler = r.fit_scaler([(0.0,) * 7, (2.0,) * 7])
    assert scaler.means == (1.0,) * 7 and scaler.scales == (1.0,) * 7
    fit = r.fit_ridge(history(), alpha=1.0)
    assert r.predict(fields(values=(100.0,) * 7), fit).value is not None
    assert fit.scaler.means == pytest.approx((0.0,) * 7)


@pytest.mark.parametrize("n", [719, 720])
def test_719_720_minimum(n):
    fit = r.fit_ridge(history(rows(n)), alpha=1.0)
    assert fit.reason == ("insufficient_training_history" if n == 719 else None)


def test_seven_feature_schema_and_fixed_order():
    values = {f: float(i) for i, f in reversed(tuple(enumerate(r.FEATURES)))}
    assert r.feature_vector(values) == tuple(float(i) for i in range(7))
    for bad in ({}, values | {"extra": 1}, {f: 0 for f in r.FEATURES[:-1]}):
        with pytest.raises(ValueError):
            r.feature_vector(bad)
    with pytest.raises(ValueError):
        r.ResearchRow(ORIGIN, (0.0,) * 6, 0.0)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True])
def test_invalid_feature_omitted_from_training_and_prediction_abstains(value):
    source = rows()
    source[0] = replace(source[0], features=(value,) + source[0].features[1:])
    prepared = history(source)
    assert len(prepared.rows) == 719
    fit = r.fit_ridge(history(), alpha=1.0)
    assert (
        r.predict(fields(values=(value,) + vector(0)[1:]), fit).reason
        == "feature_null__log_return_1h"
    )


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_eligible_bad_target_fails_numerically(value):
    source = rows()
    source[0] = replace(source[0], target=value)
    fit = r.fit_ridge(history(source), alpha=1.0)
    assert fit.reason == "ridge_numerical_failure" and fit.coefficients is None


def test_scaling_extreme_finite_units():
    scales = (1e-100, 1e100, 1e-50, 1e50, 1.0, 1e-20, 1e20)
    source = [
        replace(
            row,
            features=tuple(x * s for x, s in zip(row.features, scales, strict=True)),
        )
        for row in rows()
    ]
    fit = r.fit_ridge(history(source), alpha=1.0)
    assert fit.reason is None
    assert fit.scaler.scales == pytest.approx(scales)


def test_overflow_no_silent_solver_fallback():
    source = [replace(row, features=(1e308,) * 7) for row in rows()]
    assert r.fit_ridge(history(source), alpha=1.0).reason == "ridge_numerical_failure"


def test_sample_masks_and_same_clock_closure():
    source = rows() + [r.ResearchRow(ORIGIN, vector(0), object(), None, None, None)]
    assert history(source) == history()
    changed = [replace(row, feature_manifest_anomaly=True) for row in rows()]
    assert len(history(changed).rows) == 720
    assert len(history(changed, sample="a_sensitivity").rows) == 0
    fit = r.fit_ridge(history(sample="a_sensitivity"), alpha=1.0)
    assert (
        r.predict(
            fields(
                feature_manifest_anomaly=True,
                anomaly_involved_features=[r.FEATURES[-1]],
            ),
            fit,
        ).reason
        == "feature_manifest_anomaly__normalized_range_1h"
    )


def test_midnight_daily_fit_failure_and_stale_fit():
    with pytest.raises(ValueError, match="midnight"):
        r.fit_ridge(history(origin=ORIGIN + H), alpha=1.0)
    fit = r.fit_ridge(history(), alpha=1.0)
    assert r.predict(fields(ORIGIN + H), fit).value is not None
    tomorrow = ORIGIN + 24 * H
    assert r.predict(fields(tomorrow), fit).reason == "insufficient_training_history"
    bad = [replace(row, target=float("nan")) for row in rows()]
    failed = r.fit_ridge(history(bad, origin=tomorrow), alpha=1.0)
    assert r.predict(fields(tomorrow), failed).reason == "ridge_numerical_failure"
    assert failed.scaler is None and failed.coefficients is None


@pytest.mark.parametrize(
    "origin,fold",
    [
        (ORIGIN - H, None),
        (ORIGIN, 1),
        (datetime(2024, 5, 1, tzinfo=UTC) - H, 1),
        (datetime(2024, 5, 1, tzinfo=UTC), 2),
        (datetime(2024, 9, 1, tzinfo=UTC) - H, 2),
        (datetime(2024, 9, 1, tzinfo=UTC), 3),
        (END - H, 3),
        (END, None),
    ],
)
def test_approved_fold_boundaries(origin, fold):
    assert r.validation_fold(origin) == fold


def test_pooled_rmse_not_average_of_fold_rmse():
    assert r.pooled_rmse([0.0, 0.0, 0.0, 4.0]) == 2.0
    assert r.pooled_rmse([3.0, 4.0]) == pytest.approx(math.sqrt(12.5))
    with pytest.raises(ValueError):
        r.pooled_rmse([])


def test_alpha_ties_choose_smallest_and_test_labels_cannot_change_selection():
    source = validation_rows()
    selection = r.select_alpha(source, analysis_as_of=END)
    assert selection.selected_alpha == 0.01
    assert selection.candidate_origins == tuple(row.label_origin for row in source[-3:])
    assert all(c.rmse == 0.0 and not c.failures for c in selection.candidates)
    # Test-period target and quality objects must never be evaluated.
    future = r.ResearchRow(END, (object(),) * 7, object(), None, None, None)
    assert selection == r.select_alpha(source + [future], analysis_as_of=END)
    with pytest.raises(ValueError):
        r.select_alpha(source, analysis_as_of=END - H)


def test_frozen_candidate_set_uses_midnight_history_count():
    source = rows(719)
    source += [
        r.ResearchRow(ORIGIN, vector(0), 1.0),
        r.ResearchRow(ORIGIN + H, vector(1), 2.0),
        r.ResearchRow(ORIGIN + 24 * H, vector(2), 3.0),
    ]
    assert r.frozen_validation_origins(source, analysis_as_of=END) == (ORIGIN + 24 * H,)


def test_alpha_disqualification_preserves_identical_origins(monkeypatch):
    source = validation_rows()
    original = r.predict
    seen = {a: [] for a in r.ALPHAS}

    def prediction(fields, fit):
        seen[fit.alpha].append(fields["forecast_origin_utc"])
        if fit.alpha == 0.01 and fields["forecast_origin_utc"] == ORIGIN:
            return Prediction(None, "ridge_numerical_failure")
        return original(fields, fit)

    monkeypatch.setattr(r, "predict", prediction)
    selected = r.select_alpha(source, analysis_as_of=END)
    assert selected.selected_alpha == 0.1
    assert all(
        tuple(origins) == selected.candidate_origins for origins in seen.values()
    )
    assert selected.candidates[0].rmse is None
    assert selected.candidates[0].failures == ((ORIGIN, "ridge_numerical_failure"),)


def test_all_candidates_failed_or_empty_set_unavailable(monkeypatch):
    assert r.select_alpha([], analysis_as_of=END).selected_alpha is None
    monkeypatch.setattr(
        r, "predict", lambda *args: Prediction(None, "ridge_numerical_failure")
    )
    selected = r.select_alpha(validation_rows(), analysis_as_of=END)
    assert selected.selected_alpha is None
    assert all(c.rmse is None and len(c.failures) == 3 for c in selected.candidates)


def test_chronological_fits_admit_earlier_validation_only(monkeypatch):
    source = validation_rows()
    original = r.fit_ridge
    admitted = []

    def fit(h, **kwargs):
        assert all(row.label_origin + H <= h.cutoff for row in h.rows)
        admitted.append((h.cutoff, len(h.rows)))
        return original(h, **kwargs)

    monkeypatch.setattr(r, "fit_ridge", fit)
    r.select_alpha(source, analysis_as_of=END)
    assert admitted[:3] == [
        (ORIGIN, 720),
        (datetime(2024, 5, 1, tzinfo=UTC), 721),
        (datetime(2024, 9, 1, tzinfo=UTC), 722),
    ]


def test_test_refits_require_frozen_selection_and_same_alpha_for_both_samples():
    selected = r.select_alpha(validation_rows(), analysis_as_of=END)
    for sample in ("a_primary", "a_sensitivity"):
        h = history(origin=END, sample=sample)
        with pytest.raises(ValueError, match="frozen"):
            r.fit_ridge(h, alpha=0.1)
        with pytest.raises(ValueError, match="frozen"):
            r.fit_ridge(h, alpha=0.1, selection=selected)
        assert r.fit_ridge(h, alpha=0.01, selection=selected).reason is None


@pytest.mark.parametrize(
    "key",
    [
        "target_valid",
        "target_next_1h_log_return",
        "target_manifest_anomaly",
        "next_candle_present",
        "score_status",
    ],
)
def test_current_target_leakage_rejected(key):
    fit = r.fit_ridge(history(), alpha=1.0)
    with pytest.raises(ValueError, match="forbidden"):
        r.predict(fields(**{key: True}), fit)


def test_repeated_fit_and_prefix_invariance_no_parquet_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("historical file access")

    with monkeypatch.context() as m:
        for owner, name in (
            (pl, "read_parquet"),
            (pl, "scan_parquet"),
            (Path, "open"),
            (Path, "read_bytes"),
        ):
            m.setattr(owner, name, forbidden)
        first = r.fit_ridge(history(), alpha=1.0)
        future = r.ResearchRow(ORIGIN, (object(),) * 7, object(), None, None, None)
        assert first == r.fit_ridge(history(rows() + [future]), alpha=1.0)
        assert first == r.fit_ridge(history(list(reversed(rows()))), alpha=1.0)
        assert r.predict(fields(), first) == r.predict(fields(), first)


def test_alpha_selection_non_tie_uses_smallest_pooled_error():
    source = rows() + [r.ResearchRow(ORIGIN, vector(0), 3.0)]
    result = r.select_alpha(source, analysis_as_of=END)
    assert result.selected_alpha == 100.0
    assert result.candidates[-1].rmse < result.candidates[0].rmse
    assert result == r.select_alpha(list(reversed(source)), analysis_as_of=END)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
def test_invalid_manual_fit_parameters_rejected(bad):
    fit = r.fit_ridge(history(), alpha=1.0)
    with pytest.raises(ValueError):
        replace(fit, intercept=bad)
    with pytest.raises(ValueError):
        replace(fit, coefficients=(bad,) * 7)


def test_fit_provenance_and_failed_parameter_invariants():
    fit = r.fit_ridge(history(), alpha=1.0)
    for change in (
        {"max_outcome_close": None},
        {"max_outcome_close": ORIGIN + H},
        {"history_count": 719},
        {"scheduled_at": ORIGIN + H},
        {"reason": "ridge_numerical_failure"},
    ):
        with pytest.raises(ValueError):
            replace(fit, **change)
    with pytest.raises(ValueError):
        r.Scaler((0.0,) * 7, (0.0,) * 7)


@pytest.mark.parametrize("alpha", [0.0, -1.0, 2.0, float("nan"), True])
def test_only_approved_alpha_grid(alpha):
    with pytest.raises(ValueError):
        r.fit_ridge(history(), alpha=alpha)


def test_prediction_numerical_failure_does_not_fall_back():
    fit = r.fit_ridge(history(), alpha=0.01)
    assert (
        r.predict(fields(values=(1e308,) * 7), fit).reason == "ridge_numerical_failure"
    )


def test_selection_identity_rejects_test_timestamps_and_changed_alpha():
    result = r.select_alpha(validation_rows(), analysis_as_of=END)
    with pytest.raises(ValueError):
        replace(result, candidate_origins=result.candidate_origins + (END,))
    with pytest.raises(ValueError):
        replace(result, selected_alpha=100.0)


def test_refit_failure_retains_scheduled_time_and_affected_candidate_origins(
    monkeypatch,
):
    original = r.fit_ridge

    def fit(h, **kwargs):
        fitted = original(h, **kwargs)
        if kwargs["alpha"] == 0.01 and h.cutoff == ORIGIN:
            return replace(
                fitted,
                scaler=None,
                intercept=None,
                coefficients=None,
                reason="ridge_numerical_failure",
            )
        return fitted

    monkeypatch.setattr(r, "fit_ridge", fit)
    result = r.select_alpha(validation_rows(), analysis_as_of=END)
    assert result.selected_alpha == 0.1
    assert result.candidates[0].fit_failures == ((ORIGIN, "ridge_numerical_failure"),)
    assert result.candidates[0].failures == ((ORIGIN, "ridge_numerical_failure"),)


@pytest.mark.parametrize("reason", sorted(r.PREDICTION_FAILURE_REASONS))
def test_all_approved_prediction_abstentions_disqualify_without_dropping_origins(
    monkeypatch, reason
):
    original = r.predict
    seen = {a: [] for a in r.ALPHAS}

    def prediction(fields, fit):
        origin = fields["forecast_origin_utc"]
        seen[fit.alpha].append(origin)
        if fit.alpha == 0.01 and origin == ORIGIN:
            return Prediction(None, reason)
        return original(fields, fit)

    monkeypatch.setattr(r, "predict", prediction)
    result = r.select_alpha(validation_rows(), analysis_as_of=END)
    assert result.selected_alpha == 0.1
    assert result.candidates[0].rmse is None
    assert result.candidates[0].failures == ((ORIGIN, reason),)
    assert all(tuple(origins) == result.candidate_origins for origins in seen.values())
    assert all(c.rmse == 0.0 for c in result.candidates[1:])


def test_insufficient_history_fit_is_explicit_candidate_failure(monkeypatch):
    original = r.fit_ridge

    def fit(h, **kwargs):
        result = original(h, **kwargs)
        if kwargs["alpha"] == 0.01 and h.cutoff == ORIGIN:
            return replace(
                result,
                scaler=None,
                intercept=None,
                coefficients=None,
                reason="insufficient_training_history",
            )
        return result

    monkeypatch.setattr(r, "fit_ridge", fit)
    result = r.select_alpha(validation_rows(), analysis_as_of=END)
    assert result.selected_alpha == 0.1
    assert result.candidates[0].fit_failures == (
        (ORIGIN, "insufficient_training_history"),
    )
    assert result.candidates[0].failures == ((ORIGIN, "insufficient_training_history"),)


def test_unrecognized_abstention_and_contract_errors_still_fail_closed(monkeypatch):
    monkeypatch.setattr(r, "predict", lambda *args: Prediction(None, "unknown_reason"))
    with pytest.raises(ValueError, match="Ridge abstention"):
        r.select_alpha(validation_rows(), analysis_as_of=END)

    def malformed(*args):
        raise ValueError("malformed forecast input")

    monkeypatch.setattr(r, "predict", malformed)
    with pytest.raises(ValueError, match="malformed forecast input"):
        r.select_alpha(validation_rows(), analysis_as_of=END)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("feature_complete", [True, False])
def test_invalid_validated_target_aborts_before_fitting_without_changing_rows(
    monkeypatch, value, feature_complete
):
    source = validation_rows()
    bad = replace(
        source[-3],
        target=value,
        features=(0.0,) * 7 if feature_complete else (None,) * 7,
    )
    source[-3] = bad

    def forbidden_fit(*args, **kwargs):
        raise AssertionError("candidate fit started before integrity check")

    monkeypatch.setattr(r, "fit_ridge", forbidden_fit)
    with pytest.raises(
        r.ValidationDataIntegrityError, match="target marked valid"
    ) as error:
        r.select_alpha(source, analysis_as_of=END)
    assert ORIGIN.isoformat() in str(error.value)
    assert bad.target is value and bad.target_valid is True
    assert source[-3] is bad


def test_target_integrity_not_suppressed_by_cold_start():
    source = rows(719) + [r.ResearchRow(ORIGIN, vector(0), None, True)]
    with pytest.raises(r.ValidationDataIntegrityError):
        r.frozen_validation_origins(source, analysis_as_of=END)


@pytest.mark.parametrize(
    "analysis_offset,fit_offset,accepted",
    [
        (0, 0, True),
        (0, 24, True),
        (24, 0, False),
    ],
)
def test_alpha_analysis_boundary_cannot_postdate_test_fit(
    analysis_offset, fit_offset, accepted
):
    selection = r.select_alpha(
        validation_rows(), analysis_as_of=END + analysis_offset * H
    )
    h = history(origin=END + fit_offset * H)
    if accepted:
        assert r.fit_ridge(h, alpha=0.01, selection=selection).reason is None
    else:
        with pytest.raises(ValueError, match="analysis boundary exceeds"):
            r.fit_ridge(h, alpha=0.01, selection=selection)


def test_test_fit_rejects_nonselection_object():
    with pytest.raises(ValueError, match="frozen"):
        r.fit_ridge(history(origin=END), alpha=0.01, selection=object())
