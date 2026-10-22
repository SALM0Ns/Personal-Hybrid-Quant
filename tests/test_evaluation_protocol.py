"""Synthetic protocol boundaries only; no historical files or model execution."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from quant.research import evaluation_protocol as p
from quant.research.forecast_dataset import FORECAST_SIDE_COLUMNS, split_id

H = timedelta(hours=1)
ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


def fields(**extra):
    return {"feature_open_t": ORIGIN - H, "forecast_origin_utc": ORIGIN, **extra}


def history(method="expanding_mean", sample="a_primary", **extra):
    return p.historical_row_eligible(
        method,
        sample,
        **(
            {
                "label_origin": ORIGIN - H,
                "current_origin": ORIGIN,
                "target_valid": True,
                "target_manifest_anomaly": False,
            }
            | extra
        ),
    )


def test_utc_hour_accepted():
    assert p.validate_hour(ORIGIN) is None
    assert p.RESEARCH_ONLY and not p.POINT_IN_TIME_VERIFIED


def test_custom_zero_offset_timezone_is_utc_equivalent():
    class CustomZero(tzinfo):
        def utcoffset(self, dt):
            return timedelta(0)

        def dst(self, dt):
            return timedelta(0)

        def tzname(self, dt):
            return "custom-zero"

    origin = ORIGIN.replace(tzinfo=CustomZero())
    assert origin.tzinfo is not UTC
    assert p.validate_hour(origin) is None
    assert p.OriginTimes(origin - H, origin, origin, origin, origin + H) == (
        p.OriginTimes(ORIGIN - H, ORIGIN, ORIGIN, ORIGIN, ORIGIN + H)
    )


@pytest.mark.parametrize(
    "value",
    [
        ORIGIN.replace(tzinfo=None),
        ORIGIN.astimezone(timezone(timedelta(hours=7))),
        ORIGIN + timedelta(minutes=1),
        ORIGIN + timedelta(seconds=1),
        ORIGIN + timedelta(microseconds=1),
        None,
    ],
)
def test_invalid_timestamp_rejected(value):
    with pytest.raises(ValueError, match="UTC"):
        p.validate_hour(value)


def test_origin_and_target_alignment():
    assert (
        p.OriginTimes(ORIGIN - H, ORIGIN, ORIGIN, ORIGIN, ORIGIN + H).target_close
        == ORIGIN + H
    )


@pytest.mark.parametrize(
    "key",
    ["feature_open", "feature_close", "forecast_origin", "target_open", "target_close"],
)
def test_each_inconsistent_time_rejected(key):
    times = p.OriginTimes(ORIGIN - H, ORIGIN, ORIGIN, ORIGIN, ORIGIN + H)
    with pytest.raises(ValueError):
        replace(times, **{key: getattr(times, key) + H})


def test_same_clock_label_admitted():
    assert p.label_completed(ORIGIN - H, ORIGIN)
    assert history()


@pytest.mark.parametrize("label_origin", [ORIGIN, ORIGIN + H])
def test_incomplete_or_future_label_rejected_before_flags(label_origin):
    assert not history(
        label_origin=label_origin, target_valid=None, target_manifest_anomaly=None
    )


class UnevaluableOutcomeFlag:
    def __bool__(self):
        raise AssertionError("future outcome flag evaluated")


@pytest.mark.parametrize("sample", ["a_primary", "a_sensitivity"])
@pytest.mark.parametrize("label_origin", [ORIGIN, ORIGIN + H])
@pytest.mark.parametrize(
    "valid,anomaly",
    [
        (True, False),
        (False, True),
        (None, None),
        (1, "unknown"),
        (UnevaluableOutcomeFlag(), UnevaluableOutcomeFlag()),
    ],
)
def test_future_outcome_flags_cannot_affect_history_selection(
    sample, label_origin, valid, anomaly
):
    assert (
        p.historical_target_eligible(
            sample,
            label_origin=label_origin,
            current_origin=ORIGIN,
            target_valid=valid,
            target_manifest_anomaly=anomaly,
        )
        is False
    )


@pytest.mark.parametrize("sample", ["a_primary", "a_sensitivity"])
@pytest.mark.parametrize("field", ["target_valid", "target_manifest_anomaly"])
@pytest.mark.parametrize("invalid", [None, 0, 1, "true"])
def test_completed_history_requires_boolean_outcome_flags(sample, field, invalid):
    flags = {"target_valid": True, "target_manifest_anomaly": False, field: invalid}
    with pytest.raises(ValueError, match="Booleans"):
        p.historical_target_eligible(
            sample, label_origin=ORIGIN - H, current_origin=ORIGIN, **flags
        )


@pytest.mark.parametrize(
    "origin,expected",
    [
        (datetime(2021, 1, 1, tzinfo=UTC), "outside_approved_evaluation_window"),
        (datetime(2021, 1, 1, 1, tzinfo=UTC), "training_history"),
        (ORIGIN - H, "training_history"),
        (ORIGIN, "validation"),
        (datetime(2025, 1, 1, tzinfo=UTC) - H, "validation"),
        (datetime(2025, 1, 1, tzinfo=UTC), "test"),
        (datetime(2026, 10, 20, 12, tzinfo=UTC), "test"),
        (datetime(2026, 10, 20, 13, tzinfo=UTC), "outside_approved_evaluation_window"),
    ],
)
def test_split_boundaries_match_existing_contract(origin, expected):
    assert p.evaluation_split(origin) == split_id(origin) == expected


@pytest.mark.parametrize(
    "sample,valid,anomaly,expected",
    [
        ("a_primary", True, True, True),
        ("a_primary", False, False, False),
        ("a_sensitivity", True, True, False),
        ("a_sensitivity", True, False, True),
    ],
)
def test_sample_target_policies(sample, valid, anomaly, expected):
    assert (
        history(sample=sample, target_valid=valid, target_manifest_anomaly=anomaly)
        is expected
    )


def test_feature_and_lag_masks_do_not_affect_mean_target_eligibility():
    assert history(feature_complete=False, ar_lag_valid=False)
    assert not history("ridge_7", feature_complete=False, ar_lag_valid=True)
    assert not history("ar_1", feature_complete=True, ar_lag_valid=False)


def test_ar_pair_requires_both_lag_and_target_and_three_open_anomaly_union():
    assert history("ar_1", ar_lag_valid=True, target_manifest_anomaly=True)
    assert not history("ar_1", ar_lag_valid=True, target_valid=False)
    assert not history(
        "ar_1", "a_sensitivity", ar_lag_valid=True, ar_lag_manifest_anomaly=True
    )
    assert not history(
        "ar_1", "a_sensitivity", ar_lag_valid=True, target_manifest_anomaly=True
    )


def test_ridge_historical_sample_requires_feature_and_target_rules():
    assert history("ridge_7", feature_complete=True, feature_manifest_anomaly=True)
    assert not history(
        "ridge_7", "a_sensitivity", feature_complete=True, feature_manifest_anomaly=True
    )
    assert not history("ridge_7", feature_complete=True, target_valid=False)
    assert not history("zero_return")  # no training rows needed


@pytest.mark.parametrize("method", ["expanding_mean", "ar_1", "ridge_7"])
def test_719_720_history_threshold(method):
    assert not p.history_requirement_met(method, 719)
    assert p.history_requirement_met(method, 720)


def test_zero_has_no_history_minimum():
    assert p.history_requirement_met("zero_return", 0)


@pytest.mark.parametrize("bad", [-1, True, 720.0])
def test_invalid_history_count(bad):
    with pytest.raises(ValueError):
        p.history_requirement_met("ar_1", bad)


@pytest.mark.parametrize("method", ["ar_1", "ridge_7"])
def test_midnight_schedule_separate_from_history_eligibility(method):
    assert p.refit_scheduled(method, ORIGIN)
    assert not p.refit_scheduled(method, ORIGIN + H)
    assert not p.history_requirement_met(method, 719)
    assert p.history_requirement_met(method, 720)
    assert p.label_completed(ORIGIN - H, ORIGIN)
    assert not p.label_completed(ORIGIN, ORIGIN)


def test_mean_hourly_update_and_zero_no_fit():
    for origin in (ORIGIN, ORIGIN + H, ORIGIN + 23 * H):
        assert p.hourly_update_due("expanding_mean", origin)
        assert not p.refit_scheduled("expanding_mean", origin)
        assert not p.refit_scheduled("zero_return", origin)
        assert not p.hourly_update_due("zero_return", origin)


@pytest.mark.parametrize(
    "forbidden",
    [
        "target_next_1h_log_return",
        "target_valid",
        "target_manifest_anomaly",
        "target_endpoint_anomalies",
        "next_candle_present",
        "next_candle_complete",
        "next_close",
        "score_status",
        "future_label",
        "lane_a_sensitivity",
    ],
)
def test_forecast_interface_rejects_future_fields(forbidden):
    with pytest.raises(ValueError, match="forbidden"):
        p.forecast_inputs_eligible(
            "zero_return", "a_primary", fields(**{forbidden: False})
        )


def test_forecast_allowlist_matches_dataset_view():
    assert p.FORECAST_FIELDS == frozenset(FORECAST_SIDE_COLUMNS)
    assert p.forecast_inputs_eligible("zero_return", "a_sensitivity", fields())
    assert p.forecast_inputs_eligible(
        "expanding_mean", "a_primary", fields(feature_complete=False)
    )
    assert not p.forecast_inputs_eligible(
        "ridge_7",
        "a_primary",
        fields(feature_complete=False, feature_manifest_anomaly=False),
    )
    assert not p.forecast_inputs_eligible(
        "ar_1", "a_sensitivity", fields(ar_lag_valid=True, ar_lag_manifest_anomaly=True)
    )


@pytest.mark.parametrize(
    "bad",
    [
        {},
        fields(split_id="test"),
        fields(research_only=False),
        fields(feature_open_t=ORIGIN),
    ],
)
def test_forecast_time_boundary_invalid_inputs(bad):
    with pytest.raises(ValueError):
        p.validate_forecast_fields(bad)


def test_forecast_method_flags_missing_or_null_fail_closed():
    with pytest.raises(ValueError):
        p.forecast_inputs_eligible("ar_1", "a_primary", fields())
    with pytest.raises(ValueError):
        p.forecast_inputs_eligible(
            "ridge_7",
            "a_primary",
            fields(feature_complete=None, feature_manifest_anomaly=False),
        )


@pytest.mark.parametrize("status", ["emitted", "abstained"])
def test_forecast_status_vocabulary(status):
    assert p.ForecastState(ORIGIN, status).status == status


def test_unknown_forecast_status():
    with pytest.raises(ValueError):
        p.ForecastState(ORIGIN, "ready")


@pytest.mark.parametrize(
    "forecast,score",
    [
        ("emitted", "scored"),
        ("emitted", "emitted_but_not_scored"),
        ("abstained", "not_scored_no_forecast"),
    ],
)
def test_score_status_vocabulary(forecast, score):
    assert (
        p.validate_score_state(
            p.ForecastState(ORIGIN, forecast), score, checked_at=ORIGIN + H
        )
        is None
    )


@pytest.mark.parametrize(
    "forecast,score",
    [
        ("abstained", "scored"),
        ("abstained", "emitted_but_not_scored"),
        ("emitted", "not_scored_no_forecast"),
        ("emitted", "unknown"),
    ],
)
def test_invalid_score_state_pairs(forecast, score):
    with pytest.raises(ValueError):
        p.validate_score_state(
            p.ForecastState(ORIGIN, forecast), score, checked_at=ORIGIN + H
        )


def test_score_cannot_precede_target_close():
    with pytest.raises(ValueError, match="target close"):
        p.validate_score_state(
            p.ForecastState(ORIGIN, "emitted"), "scored", checked_at=ORIGIN
        )


def test_final_unscored_classification_requires_target_close():
    emitted = p.ForecastState(ORIGIN, "emitted")
    with pytest.raises(ValueError, match="target close"):
        p.validate_score_state(emitted, "emitted_but_not_scored", checked_at=ORIGIN)
    assert (
        p.validate_score_state(emitted, "emitted_but_not_scored", checked_at=ORIGIN + H)
        is None
    )
    abstained = p.ForecastState(ORIGIN, "abstained")
    assert (
        p.validate_score_state(abstained, "not_scored_no_forecast", checked_at=ORIGIN)
        is None
    )
    assert p.SCORE_STATUSES == {
        "scored",
        "emitted_but_not_scored",
        "not_scored_no_forecast",
    }
    with pytest.raises(ValueError, match="unknown score status"):
        p.validate_score_state(emitted, "pending", checked_at=ORIGIN)


def test_ex_post_scoreability_never_changes_emission():
    original = p.ForecastState(ORIGIN, "emitted")
    for status in ("scored", "emitted_but_not_scored"):
        p.validate_score_state(original, status, checked_at=ORIGIN + H)
        p.validate_emission_unchanged(original, "emitted")
    with pytest.raises(ValueError):
        p.validate_emission_unchanged(original, "abstained")
    with pytest.raises(FrozenInstanceError):
        original.status = "abstained"


def test_conservation():
    assert (
        p.validate_counts(
            origins=10,
            emitted=7,
            abstained=3,
            scored=5,
            emitted_but_not_scored=2,
            not_scored_no_forecast=3,
        )
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"origins": 11},
        {"scored": 6},
        {"not_scored_no_forecast": 2},
        {"emitted": -1},
        {"origins": True},
    ],
)
def test_conservation_rejects_invalid_counts(change):
    counts = dict(
        origins=10,
        emitted=7,
        abstained=3,
        scored=5,
        emitted_but_not_scored=2,
        not_scored_no_forecast=3,
    )
    with pytest.raises(ValueError):
        p.validate_counts(**(counts | change))


def test_outside_window_cannot_enter_evaluation():
    outside = datetime(2026, 10, 20, 13, tzinfo=UTC)
    with pytest.raises(ValueError, match="audit only"):
        p.ForecastState(outside, "emitted")
    with pytest.raises(ValueError):
        p.forecast_inputs_eligible(
            "zero_return",
            "a_primary",
            fields(feature_open_t=outside - H, forecast_origin_utc=outside),
        )


@pytest.mark.parametrize(
    "protocol,contract",
    [("wrong", p.DATASET_CONTRACT_VERSION), (p.PROTOCOL_VERSION, "wrong")],
)
def test_version_mismatch(protocol, contract):
    with pytest.raises(ValueError):
        p.validate_versions(protocol, contract)


def test_versions_and_repeated_calls_deterministic():
    assert p.validate_versions(p.PROTOCOL_VERSION, p.DATASET_CONTRACT_VERSION) is None
    assert p.OriginTimes(
        ORIGIN - H, ORIGIN, ORIGIN, ORIGIN, ORIGIN + H
    ) == p.OriginTimes(ORIGIN - H, ORIGIN, ORIGIN, ORIGIN, ORIGIN + H)
    assert history() == history()


def test_future_row_prefix_invariance():
    past = [ORIGIN - 2 * H, ORIGIN - H]

    def admitted(origins):
        return [
            o
            for o in origins
            if p.historical_target_eligible(
                "a_primary",
                label_origin=o,
                current_origin=ORIGIN,
                target_valid=True,
                target_manifest_anomaly=False,
            )
        ]

    assert admitted(past) == admitted(past + [ORIGIN, ORIGIN + H, ORIGIN + 100 * H])


@pytest.mark.parametrize(
    "method,sample", [("unknown", "a_primary"), ("ar_1", "unknown")]
)
def test_unknown_method_or_sample_rejected(method, sample):
    with pytest.raises(ValueError):
        history(method, sample)
