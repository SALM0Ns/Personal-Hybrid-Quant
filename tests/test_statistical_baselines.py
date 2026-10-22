"""Synthetic-only baselines; expected values use analytic or exact fixtures."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

import polars as pl
import pytest

from quant.research import statistical_baselines as b

H = timedelta(hours=1)
ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


def fields(origin=ORIGIN, **extra):
    return {"feature_open_t": origin - H, "forecast_origin_utc": origin, **extra}


def labels(n=720):
    return [b.HistoricalTarget(ORIGIN - (n - i) * H, float(i % 2)) for i in range(n)]


def pairs(n=720):
    # Three consecutive opens are implicit at s-1h,s,s+1h for each row.
    # Analytic y=2+3x gives exact intercept=2, slope=3 and Var(x)=1.
    return tuple(
        b.ARPair(
            ORIGIN - (n - i + 1) * H,
            float(i % 2 * 2 - 1),
            float(2 + 3 * (i % 2 * 2 - 1)),
        )
        for i in range(n)
    )


def history(n=720, **extra):
    return b.ARHistory(ORIGIN, "a_primary", pairs(n), **extra)


def candles(n=725):
    start = ORIGIN - (n + 1) * H
    return [
        b.CloseObservation(start + i * H, math.exp(0.01 * (i % 2))) for i in range(n)
    ]


@pytest.mark.parametrize("sample", ["a_primary", "a_sensitivity"])
@pytest.mark.parametrize("origin", [ORIGIN, ORIGIN + H, ORIGIN + 23 * H])
def test_zero_finite_without_history(sample, origin):
    result = b.zero_return(fields(origin), sample=sample)
    assert result.value == 0.0 and type(result.value) is float
    assert result.reason is None


@pytest.mark.parametrize("n,expected", [(719, None), (720, 0.5)])
def test_mean_threshold(n, expected):
    result = b.predict_mean(
        fields(), b.prepare_mean_history(labels(n), origin=ORIGIN, sample="a_primary")
    )
    assert result.value == expected
    assert result.reason == ("insufficient_training_history" if n == 719 else None)


def test_mean_fsum_cancellation_independent_exact_reference():
    source = labels()
    values = [1e16, 1.0, -1e16] * 240
    source = [replace(row, value=v) for row, v in zip(source, values, strict=True)]
    expected = float(sum((Fraction(v) for v in values), Fraction()) / 720)
    assert (
        b.predict_mean(
            fields(), b.prepare_mean_history(source, origin=ORIGIN, sample="a_primary")
        ).value
        == expected
    )


def test_mean_hourly_update_and_future_labels_ignored():
    source = labels() + [
        b.HistoricalTarget(ORIGIN, 2.0),
        b.HistoricalTarget(ORIGIN + H, 999.0),
    ]
    now = b.prepare_mean_history(source, origin=ORIGIN, sample="a_primary")
    later = b.prepare_mean_history(source, origin=ORIGIN + H, sample="a_primary")
    assert len(now.labels) == 720 and len(later.labels) == 721
    assert b.predict_mean(fields(), now).value == 0.5
    assert b.predict_mean(fields(ORIGIN + H), later).value == pytest.approx(362 / 721)
    with pytest.raises(ValueError):
        b.predict_mean(fields(ORIGIN + H), now)


def test_mean_samples_and_invalid_targets():
    source = labels() + [
        b.HistoricalTarget(ORIGIN - 800 * H, 1e9, True, True),
        b.HistoricalTarget(ORIGIN - 801 * H, None, False, False),
    ]
    primary = b.prepare_mean_history(source, origin=ORIGIN, sample="a_primary")
    sensitivity = b.prepare_mean_history(source, origin=ORIGIN, sample="a_sensitivity")
    assert len(primary.labels) == 721 and len(sensitivity.labels) == 720
    assert b.predict_mean(fields(), sensitivity).value == 0.5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), None])
def test_mean_nonfinite_fails_explicitly(value):
    source = labels()
    source[0] = replace(source[0], value=value)
    result = b.predict_mean(
        fields(), b.prepare_mean_history(source, origin=ORIGIN, sample="a_primary")
    )
    assert result.reason == "nonfinite_prediction" and result.value is None


def test_mean_sum_overflow_has_no_fallback():
    source = [replace(row, value=1e308) for row in labels()]
    assert (
        b.predict_mean(
            fields(), b.prepare_mean_history(source, origin=ORIGIN, sample="a_primary")
        ).reason
        == "nonfinite_prediction"
    )


def test_ar_exact_triple_and_no_gap_crossing():
    start = ORIGIN - 8 * H
    source = [
        b.CloseObservation(start + i * H, c)
        for i, c in [
            (0, 100.0),
            (1, 110.0),
            (2, 99.0),
            (4, 100.0),
            (5, 120.0),
            (6, 132.0),
        ]
    ]
    prepared = b.prepare_ar_history(source, origin=ORIGIN, sample="a_primary")
    assert [p.feature_open for p in prepared.pairs] == [start + H, start + 5 * H]
    assert prepared.pairs[0].lag == pytest.approx(math.log(1.1))
    assert prepared.pairs[0].target == pytest.approx(math.log(0.9))
    assert prepared.pairs[1].lag == pytest.approx(math.log(1.2))


def test_ar_pair_cutoff_same_clock_and_future_flags_not_read():
    source = candles()
    future = [
        b.CloseObservation(ORIGIN, object(), None, None),
        b.CloseObservation(ORIGIN + H, object(), None, None),
    ]
    before = b.prepare_ar_history(source, origin=ORIGIN, sample="a_primary")
    assert before == b.prepare_ar_history(
        source + future, origin=ORIGIN, sample="a_primary"
    )
    exact = [b.CloseObservation(ORIGIN - i * H, 100.0 + i) for i in (3, 2, 1)]
    assert (
        len(b.prepare_ar_history(exact, origin=ORIGIN, sample="a_primary").pairs) == 1
    )
    assert not b.prepare_ar_history(exact, origin=ORIGIN - H, sample="a_primary").pairs


@pytest.mark.parametrize("position", [0, 1, 2])
def test_ar_sensitivity_excludes_any_triple_anomaly(position):
    source = [
        b.CloseObservation(ORIGIN - (3 - i) * H, 100.0 + i, True, i == position)
        for i in range(3)
    ]
    assert (
        len(b.prepare_ar_history(source, origin=ORIGIN, sample="a_primary").pairs) == 1
    )
    assert not b.prepare_ar_history(source, origin=ORIGIN, sample="a_sensitivity").pairs


def test_ar_719_720_and_known_coefficients():
    assert b.fit_ar(history(719)).reason == "insufficient_training_history"
    fit = b.fit_ar(history())
    assert fit.reason is None and fit.intercept == 2.0 and fit.slope == 3.0
    assert fit.history_count == 720 and fit.max_outcome_close == ORIGIN


def test_ar_coefficients_from_consecutive_candle_returns():
    # Alternating returns satisfy r_next=-r_current, intercept=0.
    fit = b.fit_ar(b.prepare_ar_history(candles(), origin=ORIGIN, sample="a_primary"))
    assert fit.slope == pytest.approx(-1.0)
    assert fit.intercept == pytest.approx(0.0, abs=1e-15)


def test_ar_midnight_fit_only():
    with pytest.raises(ValueError, match="00:00"):
        b.fit_ar(replace(history(), cutoff=ORIGIN + H))


def test_current_day_coefficients_reused_then_stale_fit_abstains():
    fit = b.fit_ar(history())
    for origin in (ORIGIN, ORIGIN + H, ORIGIN + 23 * H):
        result = b.predict_ar(
            fields(origin), fit, b.CurrentLag(origin, "a_primary", 0.5)
        )
        assert result.value == 3.5
    tomorrow = ORIGIN + 24 * H
    assert (
        b.predict_ar(
            fields(tomorrow), fit, b.CurrentLag(tomorrow, "a_primary", 0.5)
        ).reason
        == "insufficient_training_history"
    )


def test_failed_refit_invalidates_previous_success():
    old = b.fit_ar(history())
    tomorrow = ORIGIN + 24 * H
    failed = b.fit_ar(b.ARHistory(tomorrow, "a_primary", ()))
    assert failed.intercept is None and failed.slope is None
    assert (
        b.predict_ar(
            fields(tomorrow), failed, b.CurrentLag(tomorrow, "a_primary", 1.0)
        ).reason
        == "insufficient_training_history"
    )
    assert (
        b.predict_ar(
            fields(tomorrow), old, b.CurrentLag(tomorrow, "a_primary", 1.0)
        ).value
        is None
    )


@pytest.mark.parametrize("delta", [0.0, 1e-9])
def test_ar_degenerate_and_tiny_variance_rejected(delta):
    constant = tuple(
        replace(row, lag=1.0 + delta * (i % 2)) for i, row in enumerate(pairs())
    )
    assert (
        b.fit_ar(b.ARHistory(ORIGIN, "a_primary", constant)).reason
        == "ar_ill_conditioned_lag"
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e308])
def test_ar_nonfinite_or_overflow_fit_failure(value):
    rows = list(pairs())
    rows[0] = replace(rows[0], lag=value)
    assert (
        b.fit_ar(b.ARHistory(ORIGIN, "a_primary", tuple(rows))).reason
        == "ar_numerical_failure"
    )


def test_ar_nonfinite_candle_not_silently_removed():
    source = candles()
    source[5] = replace(source[5], close=float("nan"))
    prepared = b.prepare_ar_history(source, origin=ORIGIN, sample="a_primary")
    assert prepared.numerical_failure
    assert b.fit_ar(prepared).reason == "ar_numerical_failure"


@pytest.mark.parametrize("scale,accepted", [(2.0**-27, False), (2.0**-26, True)])
def test_ar_variance_on_both_sides_of_fixed_threshold(scale, accepted):
    rows = tuple(replace(p, lag=p.lag * scale) for p in pairs())
    fit = b.fit_ar(b.ARHistory(ORIGIN, "a_primary", rows))
    assert (fit.reason is None) is accepted


def test_ar_prediction_nonfinite_and_invalid_fit_provenance():
    fit = b.fit_ar(history())
    lag = b.CurrentLag(ORIGIN, "a_primary", 1e308)
    assert b.predict_ar(fields(), fit, lag).reason == "ar_numerical_failure"
    with pytest.raises(ValueError, match="cutoff"):
        b.predict_ar(fields(), replace(fit, max_outcome_close=ORIGIN + H), lag)
    with pytest.raises(ValueError, match="midnight"):
        b.predict_ar(fields(), replace(fit, scheduled_at=ORIGIN + H), lag)


def test_numerically_failed_daily_fit_abstains_until_next_refit():
    failed = b.fit_ar(history(numerical_failure=True))
    for origin in (ORIGIN, ORIGIN + H, ORIGIN + 23 * H):
        result = b.predict_ar(
            fields(origin), failed, b.CurrentLag(origin, "a_primary", 0.1)
        )
        assert result.value is None and result.reason == "ar_numerical_failure"


@pytest.mark.parametrize(
    "source",
    [
        [],
        [b.CloseObservation(ORIGIN - H, 100.0)],
        [
            b.CloseObservation(ORIGIN - 3 * H, 100.0),
            b.CloseObservation(ORIGIN - H, 110.0),
        ],
        [
            b.CloseObservation(ORIGIN - 2 * H, float("nan")),
            b.CloseObservation(ORIGIN - H, 110.0),
        ],
        [
            b.CloseObservation(ORIGIN - 2 * H, 100.0, False),
            b.CloseObservation(ORIGIN - H, 110.0),
        ],
    ],
)
def test_ar_missing_invalid_current_lag_abstains(source):
    lag = b.prepare_current_lag(source, fields(), sample="a_primary")
    assert (
        b.predict_ar(fields(), b.fit_ar(history()), lag).reason
        == "ar_lag_missing_or_invalid"
    )


def test_ar_current_lag_exact_time_and_sample():
    source = [
        b.CloseObservation(ORIGIN - 2 * H, 100.0),
        b.CloseObservation(ORIGIN - H, 110.0, True, True),
        b.CloseObservation(ORIGIN, object(), None, None),
    ]
    lag = b.prepare_current_lag(source, fields(), sample="a_primary")
    assert lag.value == pytest.approx(math.log(1.1))
    assert (
        b.prepare_current_lag(source, fields(), sample="a_sensitivity").reason
        == "ar_lag_manifest_anomaly"
    )
    with pytest.raises(ValueError):
        b.predict_ar(fields(ORIGIN + H), b.fit_ar(history()), lag)


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
    with pytest.raises(ValueError, match="forbidden"):
        b.zero_return(fields(**{key: True}), sample="a_primary")
    with pytest.raises(ValueError, match="forbidden"):
        b.predict_mean(
            fields(**{key: True}),
            b.prepare_mean_history(labels(), origin=ORIGIN, sample="a_primary"),
        )
    with pytest.raises(ValueError, match="forbidden"):
        b.predict_ar(
            fields(**{key: True}),
            b.fit_ar(history()),
            b.CurrentLag(ORIGIN, "a_primary", 1.0),
        )


@pytest.mark.parametrize(
    "origin",
    [
        ORIGIN.replace(tzinfo=None),
        ORIGIN + timedelta(minutes=1),
        ORIGIN.astimezone(timezone(timedelta(hours=7))),
        datetime(2026, 10, 20, 13, tzinfo=UTC),
    ],
)
def test_invalid_timestamp_or_outside_origin(origin):
    with pytest.raises(ValueError):
        b.zero_return(fields(origin), sample="a_primary")


def test_duplicates_rejected_and_history_cannot_bypass_cutoff():
    with pytest.raises(ValueError):
        b.prepare_mean_history(
            labels() + labels()[:1], origin=ORIGIN, sample="a_primary"
        )
    with pytest.raises(ValueError):
        b.prepare_ar_history(
            candles() + candles()[:1], origin=ORIGIN, sample="a_primary"
        )
    with pytest.raises(ValueError):
        b.fit_ar(b.ARHistory(ORIGIN, "a_primary", (b.ARPair(ORIGIN, 1.0, 1.0),)))


def test_determinism_future_prefix_invariance_and_no_parquet_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected file access")

    with monkeypatch.context() as m:
        for owner, name in [
            (pl, "read_parquet"),
            (pl, "scan_parquet"),
            (Path, "read_bytes"),
            (Path, "open"),
        ]:
            m.setattr(owner, name, forbidden)
        initial = b.fit_ar(
            b.prepare_ar_history(candles(), origin=ORIGIN, sample="a_primary")
        )
        extended = b.fit_ar(
            b.prepare_ar_history(
                candles() + [b.CloseObservation(ORIGIN, object(), None, None)],
                origin=ORIGIN,
                sample="a_primary",
            )
        )
        assert initial == extended
        assert initial == b.fit_ar(
            b.prepare_ar_history(
                list(reversed(candles())), origin=ORIGIN, sample="a_primary"
            )
        )
        assert b.predict_ar(
            fields(), initial, b.CurrentLag(ORIGIN, "a_primary", 0.01)
        ) == b.predict_ar(fields(), extended, b.CurrentLag(ORIGIN, "a_primary", 0.01))
        before = b.prepare_mean_history(labels(), origin=ORIGIN, sample="a_primary")
        after = b.prepare_mean_history(
            labels() + [b.HistoricalTarget(ORIGIN, object(), None, None)],
            origin=ORIGIN,
            sample="a_primary",
        )
        assert before == after
        assert b.predict_mean(fields(), before) == b.predict_mean(fields(), after)
        assert b.zero_return(fields(), sample="a_primary").value == 0.0


@pytest.mark.parametrize("field", ["intercept", "slope"])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "1"])
def test_manual_successful_fit_rejects_invalid_parameters(field, value):
    with pytest.raises(ValueError, match="finite parameters"):
        replace(b.fit_ar(history()), **{field: value})


@pytest.mark.parametrize("count", [719, 0, -1, 720.0, True])
def test_manual_successful_fit_rejects_invalid_history_count(count):
    with pytest.raises(ValueError):
        replace(b.fit_ar(history()), history_count=count)


@pytest.mark.parametrize(
    "cutoff",
    [
        None,
        ORIGIN + H,
        ORIGIN.replace(tzinfo=None),
        ORIGIN + timedelta(minutes=1),
    ],
)
def test_manual_successful_fit_requires_valid_completed_outcome_cutoff(cutoff):
    with pytest.raises(ValueError):
        replace(b.fit_ar(history()), max_outcome_close=cutoff)


@pytest.mark.parametrize(
    "scheduled",
    [
        ORIGIN + H,
        ORIGIN.replace(tzinfo=None),
        ORIGIN + timedelta(minutes=1),
        ORIGIN.astimezone(timezone(timedelta(hours=7))),
    ],
)
def test_manual_fit_requires_valid_midnight_timestamp(scheduled):
    with pytest.raises(ValueError):
        replace(b.fit_ar(history()), scheduled_at=scheduled)


def test_manual_valid_fit_allows_equal_cutoff_and_finite_zero_parameters():
    fit = b.ARFit(ORIGIN, "a_primary", 720, ORIGIN, 0.0, 0.0, None)
    assert (
        b.predict_ar(fields(), fit, b.CurrentLag(ORIGIN, "a_primary", 1.0)).value == 0.0
    )


@pytest.mark.parametrize(
    "reason",
    [
        "insufficient_training_history",
        "ar_ill_conditioned_lag",
        "ar_numerical_failure",
    ],
)
def test_manual_failed_fit_never_produces_success(reason):
    failed = b.ARFit(ORIGIN, "a_primary", 720, ORIGIN, None, None, reason)
    assert (
        b.predict_ar(fields(), failed, b.CurrentLag(ORIGIN, "a_primary", 1.0)).reason
        == reason
    )
    with pytest.raises(ValueError, match="no parameters"):
        replace(failed, intercept=2.0, slope=3.0)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "1"])
def test_manual_lag_cannot_claim_success_without_finite_numeric_value(value):
    with pytest.raises(ValueError, match="finite numeric value"):
        b.CurrentLag(ORIGIN, "a_primary", value)


@pytest.mark.parametrize("reason", ["", "unknown"])
def test_manual_unavailable_lag_requires_approved_nonempty_reason(reason):
    with pytest.raises(ValueError, match="valid reason"):
        b.CurrentLag(ORIGIN, "a_primary", None, reason)


@pytest.mark.parametrize(
    "reason", ["ar_lag_missing_or_invalid", "ar_lag_manifest_anomaly"]
)
def test_manual_unavailable_lag_preserves_reason_and_cannot_have_value(reason):
    lag = b.CurrentLag(ORIGIN, "a_primary", None, reason)
    assert b.predict_ar(fields(), b.fit_ar(history()), lag).reason == reason
    with pytest.raises(ValueError, match="null value"):
        b.CurrentLag(ORIGIN, "a_primary", 0.1, reason)


@pytest.mark.parametrize("sample", ["a_primary", "a_sensitivity"])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), 1e99])
def test_invalid_mean_target_is_excluded_by_flag_without_numeric_inspection(
    sample, value
):
    excluded = b.HistoricalTarget(ORIGIN - 800 * H, value, False, False)
    prepared = b.prepare_mean_history(
        labels() + [excluded], origin=ORIGIN, sample=sample
    )
    assert len(prepared.labels) == 720 and excluded not in prepared.labels
    assert b.predict_mean(fields(), prepared).value == 0.5


@pytest.mark.parametrize("sample", ["a_primary", "a_sensitivity"])
@pytest.mark.parametrize("value", [0, 2.5])
def test_valid_finite_mean_target_remains_eligible(sample, value):
    extra = b.HistoricalTarget(ORIGIN - 800 * H, value, True, False)
    prepared = b.prepare_mean_history(labels() + [extra], origin=ORIGIN, sample=sample)
    assert len(prepared.labels) == 721 and extra in prepared.labels
    assert b.predict_mean(fields(), prepared).value == pytest.approx(
        (360 + value) / 721
    )


@pytest.mark.parametrize("sample", ["a_primary", "a_sensitivity"])
@pytest.mark.parametrize("n", [720, 721])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf")])
def test_invalid_numeric_eligible_mean_label_is_retained_and_abstains(sample, n, value):
    source = labels(n)
    source[0] = replace(source[0], value=value)
    prepared = b.prepare_mean_history(source, origin=ORIGIN, sample=sample)
    assert len(prepared.labels) == n
    assert prepared.labels[0] is source[0]
    result = b.predict_mean(fields(), prepared)
    assert result.value is None and result.reason == "nonfinite_prediction"
