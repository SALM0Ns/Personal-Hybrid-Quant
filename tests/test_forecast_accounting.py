"""Synthetic scheduled origins and outcome accounting; no historical I/ORIGIN."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from quant.research import forecast_accounting as a

H = timedelta(hours=1)
ORIGIN = datetime(2025, 1, 1, tzinfo=UTC)


def forecast(model="zero_return", sample="a_primary", origin=ORIGIN, **kwargs):
    return a.Forecast(origin, model, sample, **({"prediction": 0.0} | kwargs))


def score(f=None, **kwargs):
    f = f or forecast()
    outcome = a.Outcome(f.origin, **({"target": 0.1, "target_valid": True} | kwargs))
    return a.Score(f, outcome, f.origin + H)


def test_universe_half_open_sort_and_empty():
    u = a.OriginUniverse("test", ORIGIN, ORIGIN + 2 * H)
    assert u.origins == (ORIGIN, ORIGIN + H)
    assert not a.OriginUniverse("test", ORIGIN, ORIGIN).origins
    assert a.OriginUniverse("test", a.TEST_END, a.TEST_END).origins == ()


@pytest.mark.parametrize(
    "start,end,period",
    [
        (ORIGIN, ORIGIN - H, "test"),
        (ORIGIN - H, ORIGIN, "test"),
        (ORIGIN, a.TEST_END + H, "test"),
        (ORIGIN, ORIGIN, "unknown"),
        (ORIGIN.replace(tzinfo=None), ORIGIN, "test"),
        (ORIGIN + timedelta(minutes=1), ORIGIN + H, "test"),
        (ORIGIN.astimezone(timezone(timedelta(hours=7))), ORIGIN, "test"),
    ],
)
def test_invalid_universe(start, end, period):
    with pytest.raises(ValueError):
        a.OriginUniverse(period, start, end)


@pytest.mark.parametrize(
    "value", [None, float("nan"), float("inf"), True, "0", 10**1000]
)
def test_finite_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        a.finite(value)


def test_forecast_frozen_and_no_target_interface():
    f = forecast()
    with pytest.raises(FrozenInstanceError):
        f.prediction = 2
    with pytest.raises(TypeError):
        a.Forecast(ORIGIN, "zero_return", "a_primary", 0.0, target_valid=False)
    assert f.status == "emitted" and f.abstention_reason is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model_id": "unknown"},
        {"sample_policy": "lane_b"},
        {"prediction": None},
        {"prediction": 0.1},
        {"prediction": True},
        {"prediction": float("nan")},
        {"reasons": ("next_missing",)},
    ],
)
def test_zero_contract_and_unknown_identities(kwargs):
    values = dict(
        origin=ORIGIN, model_id="zero_return", sample_policy="a_primary", prediction=0.0
    )
    with pytest.raises(ValueError):
        a.Forecast(**(values | kwargs))


@pytest.mark.parametrize(
    "model,reason",
    [
        ("expanding_mean", "insufficient_training_history"),
        ("expanding_mean", "nonfinite_prediction"),
        ("ar_1", "ar_lag_missing_or_invalid"),
        ("ar_1", "ar_ill_conditioned_lag"),
        ("ar_1", "ar_numerical_failure"),
        ("ridge_7", "ridge_numerical_failure"),
        ("ridge_7", "feature_null__log_return_1h"),
    ],
)
def test_approved_abstentions(model, reason):
    f = forecast(model, prediction=None, reasons=(reason,))
    s = score(f)
    assert f.status == "abstained" and f.abstention_reason == reason
    assert s.status == "not_scored_no_forecast" and s.primary_reason == reason


@pytest.mark.parametrize(
    "reasons",
    [
        ("ar_numerical_failure", "ar_lag_missing_or_invalid"),
        ("ar_numerical_failure", "ar_numerical_failure"),
        ("ar_lag_manifest_anomaly",),
        ("next_missing",),
        ("unknown",),
    ],
)
def test_forecast_priority_duplicate_or_inapplicable_reasons(reasons):
    with pytest.raises(ValueError):
        forecast("ar_1", prediction=None, reasons=reasons)


def test_target_change_cannot_modify_emission():
    f = forecast()
    valid = score(f)
    invalid = score(
        f, target=None, target_valid=False, invalid_reasons=("next_missing",)
    )
    assert valid.forecast is invalid.forecast is f
    assert valid.status == "scored"
    assert invalid.status == "emitted_but_not_scored"
    assert invalid.forecast.prediction == 0.0


def test_target_anomaly_separate_sample_policy():
    primary = score(target_manifest_anomaly=True)
    sensitivity = score(forecast(sample="a_sensitivity"), target_manifest_anomaly=True)
    assert primary.status == "scored"
    assert sensitivity.status == "emitted_but_not_scored"
    assert sensitivity.primary_reason == "target_manifest_anomaly"


@pytest.mark.parametrize("target", [None, float("nan"), float("inf"), True])
def test_valid_but_bad_target_fails_closed(target):
    with pytest.raises(ValueError):
        a.Outcome(ORIGIN, target, True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_valid": None},
        {"target_manifest_anomaly": None},
        {"invalid_reasons": ("next_missing",)},
        {"target": None, "target_valid": False},
        {"target_valid": False, "invalid_reasons": ("next_missing",)},
        {"target": None, "target_valid": False, "invalid_reasons": ("unknown",)},
    ],
)
def test_inconsistent_target_flags_and_reasons(kwargs):
    with pytest.raises(ValueError):
        a.Outcome(ORIGIN, **({"target": 1.0, "target_valid": True} | kwargs))


def test_closure_required_even_abstention_with_outcome_metadata():
    f = forecast("ar_1", prediction=None, reasons=("ar_numerical_failure",))
    out = a.Outcome(ORIGIN, 1.0, True)
    with pytest.raises(ValueError, match="closure"):
        a.Score(f, out, ORIGIN)
    assert a.Score(f, out, ORIGIN + H).status == "not_scored_no_forecast"
    with pytest.raises(ValueError, match="origin mismatch"):
        a.Score(f, replace(out, origin=ORIGIN + H), ORIGIN + 2 * H)


def test_overlapping_reasons_keep_score_priority_distinct_from_abstention():
    f = forecast(
        "ar_1",
        "a_sensitivity",
        prediction=None,
        reasons=("ar_lag_manifest_anomaly", "ar_numerical_failure"),
    )
    s = score(
        f,
        target=None,
        target_valid=False,
        invalid_reasons=("current_missing", "next_missing"),
        target_manifest_anomaly=True,
    )
    assert s.primary_reason == "current_missing"
    assert f.abstention_reason == "ar_lag_manifest_anomaly"
    assert s.exclusion_reasons == (
        "current_missing",
        "next_missing",
        "target_manifest_anomaly",
        "ar_lag_manifest_anomaly",
        "ar_numerical_failure",
    )
    assert a.UNKNOWN_AVAILABILITY in s.all_reasons


def test_full_conservation_no_silent_drops_and_sorting():
    u = a.OriginUniverse("test", ORIGIN, ORIGIN + 3 * H)
    scores = [
        score(forecast("expanding_mean", origin=ORIGIN)),
        score(
            forecast("expanding_mean", origin=ORIGIN + H),
            target=None,
            target_valid=False,
            invalid_reasons=("next_missing", "next_invalid_close"),
        ),
        score(
            forecast(
                "expanding_mean",
                origin=ORIGIN + 2 * H,
                prediction=None,
                reasons=("insufficient_training_history",),
            )
        ),
    ]
    book = a.account(u, "expanding_mean", "a_primary", reversed(scores))
    assert book.counts == dict(
        origins=3,
        emitted=2,
        abstained=1,
        scored=1,
        emitted_but_not_scored=1,
        not_scored_no_forecast=1,
    )
    assert book.coverage == 2 / 3
    counts = book.reason_counts()
    assert counts["abstention_reasons"] == {"insufficient_training_history": 1}
    assert counts["primary_score_exclusion_counts"] == {
        "next_missing": 1,
        "insufficient_training_history": 1,
    }
    assert counts["all_score_exclusion_counts"][a.UNKNOWN_AVAILABILITY] == 3
    for broken in (scores[:-1], scores + scores[:1]):
        with pytest.raises(ValueError, match="exactly"):
            a.account(u, "expanding_mean", "a_primary", broken)


def test_empty_accounting_has_null_coverage():
    book = a.account(
        a.OriginUniverse("test", ORIGIN, ORIGIN), "zero_return", "a_primary", ()
    )
    assert book.coverage is None
    assert not any(book.counts.values())
    assert all(not c for c in book.reason_counts().values())


def test_failed_daily_refit_counts_all_hourly_abstentions_without_stale_success():
    u = a.OriginUniverse("test", ORIGIN, ORIGIN + 24 * H)
    book = a.account(
        u,
        "ar_1",
        "a_primary",
        [
            score(
                forecast(
                    "ar_1", origin=o, prediction=None, reasons=("ar_numerical_failure",)
                )
            )
            for o in u.origins
        ],
    )
    assert book.counts["abstained"] == book.counts["not_scored_no_forecast"] == 24
    assert book.coverage == 0.0
    assert book.reason_counts()["abstention_reasons"] == {"ar_numerical_failure": 24}


@pytest.mark.parametrize(
    "quality",
    [
        {"feature_complete": None},
        {"ar_lag_valid": 1},
        {"anomaly_types": ("exchange_outage",)},
        {"affected_fields": ("secret",)},
        {"affected_fields": ("close", "close")},
    ],
)
def test_quality_metadata_validation(quality):
    with pytest.raises(ValueError):
        a.Quality(**quality)


@pytest.mark.parametrize("label", ["verified", "evidence_verified", None, True, ""])
def test_outcome_cannot_claim_verified_anomaly_evidence(label):
    with pytest.raises(ValueError, match="unverified or partial"):
        a.Outcome(ORIGIN, 0.1, True, anomaly_evidence_status=label)


def test_populated_anomaly_fields_are_not_evidence_verification():
    quality = a.Quality(
        anomaly_types=("source_discrepancy",), affected_fields=("close",)
    )
    outcome = a.Outcome(
        ORIGIN, 0.1, True, target_manifest_anomaly=True, quality=quality
    )
    assert outcome.anomaly_evidence_status == "unverified"
    assert outcome.quality == quality
    # A partial flag alone never fabricates a type or affected field.
    partial = a.Outcome(
        ORIGIN,
        0.1,
        True,
        target_manifest_anomaly=True,
        anomaly_evidence_status="partial",
    )
    assert partial.quality.anomaly_types == partial.quality.affected_fields == ()
