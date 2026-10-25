"""Invented fixtures for the synthetic-only native score classifier."""

from __future__ import annotations

import builtins
import hashlib
import socket
import subprocess
import time
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from quant.features.engine import FEATURES
from quant.research import historical_scoring_contract as contract
from quant.research import native_scoring, ridge_regression, statistical_baselines
from quant.research.forecast_accounting import MODELS, SAMPLES, UNKNOWN_AVAILABILITY
from quant.research.forecast_dataset import ANALYSIS_AS_OF, TEST_START
from quant.research.historical_projection import OpaqueSourceRef
from quant.research.historical_representation import (
    POLICY_VERSION as NATIVE_POLICY_VERSION,
)
from quant.research.historical_representation import (
    SCHEMA_VERSION as NATIVE_SCHEMA_VERSION,
)
from quant.research.historical_representation import NativeOccurrence
from quant.research.historical_scoring_contract import (
    SCHEMA_VERSION,
    HistoricalForecast,
    HistoricalOriginRef,
    HistoricalOutcomeView,
    HistoricalProvenanceRef,
    HistoricalScopeSpec,
    ScoreClassification,
    canonical_json,
    scoring_build_id,
    validate_classification_parent,
)
from quant.research.native_scoring import classify_native_score

HOUR = timedelta(hours=1)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def provenance() -> HistoricalProvenanceRef:
    return HistoricalProvenanceRef(
        **{
            field: digest("synthetic:" + field)
            for field in (
                "dataset_spec_id",
                "source_artifact_build_id",
                "silver_sha256",
                "gold_sha256",
                "origin_ledger_sha256",
                "dataset_validation_sha256",
                "provenance_json_sha256",
                "provenance_sidecar_sha256",
                "manifest_canonical_sha256",
                "manifest_raw_sha256",
                "source_receipt_sha256",
            )
        },
        manifest_version="synthetic-manifest-v1",
        feature_version="synthetic-features-v1",
        feature_order=tuple(FEATURES),
        source_mode="synthetic_fixture",
    )


def fixture(
    model="zero_return",
    sample="a_primary",
    *,
    reasons=(),
    target_reasons=(),
    when=TEST_START,
):
    source = provenance()
    origin = HistoricalOriginRef(
        provenance=source,
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        source_identifier="synthetic:6b-origin",
        source_row_index=0,
        origin=when,
        feature_open_t=when - HOUR,
        target_theoretical_close_at=when + HOUR,
        period_id="test",
    )
    selection_id = digest("synthetic:alpha-selection") if model == "ridge_7" else None
    scope = HistoricalScopeSpec(
        provenance=source,
        period_id="test",
        start=when,
        end_exclusive=when + HOUR,
        analysis_as_of=ANALYSIS_AS_OF,
        intended_use="test_frozen_alpha_comparison",
        origins=(origin,),
        model_ids=(model,),
        sample_policies=(sample,),
        frozen_ridge_selection_id=selection_id,
    )
    build = scoring_build_id(
        scope.scoring_spec_id,
        code_sha256=digest("synthetic:code"),
        dependency_versions={"python": "3.12"},
        deterministic_build_configuration={"fixture": "native-6b"},
    )
    emitted = not reasons
    fit_model = model in {"ar_1", "ridge_7"}
    forecast = HistoricalForecast(
        schema_version=SCHEMA_VERSION,
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=build,
        execution_instance_id=None,
        origin_ref=origin,
        model_id=model,
        sample_policy=sample,
        forecast_status="emitted" if emitted else "abstained",
        prediction=(0.0 if model == "zero_return" else 0.125) if emitted else None,
        abstention_reasons=reasons,
        producer_trace_ref="synthetic:6b-trace",
        model_version="synthetic-model-v1",
        history_count=0 if model == "zero_return" else 720,
        history_cutoff=None if model == "zero_return" else when,
        scheduled_refit_at=when.replace(hour=0) if fit_model else None,
        fit_ref="synthetic:fit" if fit_model and emitted else None,
        alpha_selection_ref=selection_id if model == "ridge_7" and emitted else None,
        selected_alpha=1.0 if model == "ridge_7" and emitted else None,
    )
    ordered = tuple(
        reason for reason in contract.TARGET_REASON_PRIORITY if reason in target_reasons
    )
    outcome = HistoricalOutcomeView(
        origin_ref=origin,
        target=None if target_reasons else 0.25,
        target_valid=not target_reasons,
        original_invalid_reasons=target_reasons,
        ordered_invalid_reasons=ordered,
        target_primary_null_reason=ordered[0] if ordered else None,
        target_manifest_anomaly=False,
        target_value_sensitive=None,
        target_endpoint_occurrences=(),
        feature_window_occurrences=(),
        unresolved_occurrences=(),
        anomaly_evidence_status="no_occurrences",
        source_authentication="synthetic_fixture",
        native_schema_version=NATIVE_SCHEMA_VERSION,
        native_policy_version=NATIVE_POLICY_VERSION,
        theoretical_close_at=when + HOUR,
        checked_at=when + HOUR,
        closure="closed",
        native_envelope_sha256=digest("synthetic:6b-envelope"),
    )
    return forecast, outcome, scope, build


def classify(parts, **changes):
    forecast, outcome, scope, build = parts
    options = {
        "scope": scope,
        "scoring_build_id": build,
        "sample_policy": forecast.sample_policy,
    }
    options.update(changes)
    return classify_native_score(forecast, outcome, **options)


def occurrence(
    origin,
    *,
    field="close",
    collection="target_endpoint_anomalies",
    position=0,
    linkage="matched",
):
    role = {
        "target_endpoint_anomalies": "target_endpoint",
        "feature_window_anomalies": "feature_window",
        "unresolved_anomalies": "unresolved",
    }[collection]
    source_column = {
        "target_endpoint_anomalies": "target_endpoint_anomalies",
        "feature_window_anomalies": "involved_anomalies",
        "unresolved_anomalies": "synthetic:unresolved",
    }[collection]
    raw = {
        "timestamp": origin.feature_open_t,
        "anomaly_type": "missing_hour" if field == "candle" else "source_discrepancy",
        "affected_fields": (field,),
        "note": None,
        "evidence_references": ("synthetic:6b-evidence",),
    }
    ref = OpaqueSourceRef(
        origin.provenance.dataset_spec_id,
        origin.provenance.source_artifact_build_id,
        origin.provenance.source_receipt_sha256,
        origin.source_identifier,
        origin.source_row_index,
        origin.origin,
    )
    return NativeOccurrence(
        source_ref=ref,
        collection=collection,
        position=position,
        association=role,
        source_column=source_column,
        raw=raw,
        linkage=linkage,
        manifest_record_index=position if linkage == "matched" else None,
        manifest_record_sha256=hashlib.sha256(canonical_json(raw)).hexdigest()
        if linkage == "matched"
        else None,
        manifest_record=raw if linkage == "matched" else None,
    )


def with_occurrences(parts, *, endpoint=(), window=(), unresolved=()):
    forecast, outcome, scope, build = parts
    return (
        forecast,
        replace(
            outcome,
            target_manifest_anomaly=bool(endpoint),
            target_endpoint_occurrences=endpoint,
            feature_window_occurrences=window,
            unresolved_occurrences=unresolved,
            anomaly_evidence_status="recorded_references_unverified",
        ),
        scope,
        build,
    )


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("sample", SAMPLES)
def test_valid_emission_scores_for_each_model_and_sample(model, sample):
    parts = fixture(model, sample)
    result = classify(parts)
    assert type(result) is ScoreClassification
    assert result.forecast_id == parts[0].forecast_id
    assert result.score_status == "scored"
    assert (result.prediction, result.target) == (parts[0].prediction, 0.25)
    assert result.primary_score_reason == "scored"
    assert result.score_exclusion_reasons == ()
    assert result.all_diagnostics == (UNKNOWN_AVAILABILITY,)
    validate_classification_parent(result, parts[0])


@pytest.mark.parametrize(
    "reason", ("next_missing", "current_invalid_close", "target_nonfinite")
)
def test_invalid_or_missing_target_is_unscored_without_imputation(reason):
    parts = fixture(target_reasons=(reason,))
    result = classify(parts)
    assert result.score_status == "emitted_but_not_scored"
    assert result.target is None
    assert result.prediction == parts[0].prediction
    assert result.primary_score_reason == reason
    assert result.all_diagnostics == (reason, UNKNOWN_AVAILABILITY)


@pytest.mark.parametrize("target_reasons", ((), ("next_missing",)))
def test_abstention_is_preserved_with_eligible_or_unavailable_target(target_reasons):
    parts = fixture(
        "expanding_mean",
        reasons=("insufficient_training_history",),
        target_reasons=target_reasons,
    )
    before = canonical_json(parts[0])
    result = classify(parts)
    assert result.score_status == "not_scored_no_forecast"
    assert result.prediction is None and result.target is None
    assert result.abstention_reasons == ("insufficient_training_history",)
    expected = (*target_reasons, "insufficient_training_history")
    assert result.score_exclusion_reasons == expected
    assert result.primary_score_reason == expected[0]
    assert canonical_json(parts[0]) == before


@pytest.mark.parametrize(
    "sample, expected",
    (("a_primary", "scored"), ("a_sensitivity", "emitted_but_not_scored")),
)
@pytest.mark.parametrize("field", ("candle", "unknown", "volume", "close"))
def test_endpoint_anomalies_follow_sample_policy_without_field_translation(
    sample, expected, field
):
    parts = fixture(sample=sample)
    annotation = occurrence(parts[0].origin_ref, field=field)
    parts = with_occurrences(parts, endpoint=(annotation,))
    outcome_before = canonical_json(parts[1])
    result = classify(parts)
    assert result.score_status == expected
    assert result.score_exclusion_reasons == (
        () if sample == "a_primary" else ("target_manifest_anomaly",)
    )
    assert parts[1].target_endpoint_occurrences[0].raw["affected_fields"] == (field,)
    assert canonical_json(parts[1]) == outcome_before


def test_feature_window_anomaly_does_not_create_target_exclusion():
    parts = fixture(sample="a_sensitivity")
    annotation = occurrence(
        parts[0].origin_ref, field="unknown", collection="feature_window_anomalies"
    )
    parts = with_occurrences(parts, window=(annotation,))
    assert classify(parts).score_status == "scored"


def test_overlapping_target_anomaly_lag_and_fit_reasons_keep_approved_priority():
    parts = fixture(
        "ar_1",
        "a_sensitivity",
        reasons=("ar_lag_missing_or_invalid", "ar_numerical_failure"),
        target_reasons=("next_missing", "current_missing"),
    )
    parts = with_occurrences(
        parts, endpoint=(occurrence(parts[0].origin_ref, field="unknown"),)
    )
    result = classify(parts)
    assert result.score_status == "not_scored_no_forecast"
    assert result.original_target_reasons == ("next_missing", "current_missing")
    assert result.score_exclusion_reasons == (
        "current_missing",
        "next_missing",
        "target_manifest_anomaly",
        "ar_lag_missing_or_invalid",
        "ar_numerical_failure",
    )
    assert result.primary_score_reason == "current_missing"
    assert result.abstention_reasons[0] == "ar_lag_missing_or_invalid"
    assert result.all_diagnostics == (
        *result.score_exclusion_reasons,
        UNKNOWN_AVAILABILITY,
    )


@pytest.mark.parametrize(
    "field", ("forecast_id", "scoring_spec_id", "scoring_build_id")
)
def test_tampered_parent_identity_is_rejected(field):
    parts = fixture()
    object.__setattr__(parts[0], field, digest("synthetic:wrong-identity"))
    with pytest.raises(ValueError):
        classify(parts)


def test_missing_parent_forecast_id_is_rejected():
    parts = fixture()
    object.__setattr__(parts[0], "forecast_id", None)
    with pytest.raises(ValueError):
        classify(parts)
    assert parts[0].forecast_id is None


@pytest.mark.parametrize(
    "field",
    ("scoring_spec_id", "origin_set_sha256", "source_origin_identity_set_sha256"),
)
def test_missing_scope_identity_is_rejected_without_repair(field):
    parts = fixture()
    object.__setattr__(parts[2], field, None)
    with pytest.raises(ValueError):
        classify(parts)
    assert getattr(parts[2], field) is None


@pytest.mark.parametrize(
    "value", (None, "bad", "A" * 64, digest("synthetic:wrong-build"))
)
def test_expected_build_identity_is_required_and_exact(value):
    with pytest.raises(ValueError):
        classify(fixture(), scoring_build_id=value)


def test_wrong_requested_sample_and_policy_are_rejected():
    parts = fixture()
    for changes in (
        {"sample_policy": "a_sensitivity"},
        {"policy_version": "future-policy"},
    ):
        with pytest.raises(ValueError):
            classify(parts, **changes)


@pytest.mark.parametrize(
    "field, value", (("model_id", "ar_1"), ("sample_policy", "a_sensitivity"))
)
def test_forecast_cannot_be_substituted_with_wrong_model_or_sample(field, value):
    parts = fixture()
    object.__setattr__(parts[0], field, value)
    with pytest.raises(ValueError):
        classify(parts)


def test_other_scope_specification_is_rejected():
    parts = fixture()
    other_scope = replace(
        parts[2], sample_policies=("a_primary", "a_sensitivity"), scoring_spec_id=None
    )
    with pytest.raises(ValueError):
        classify(parts, scope=other_scope)


@pytest.mark.parametrize(
    "field, value",
    (("source_row_index", 9), ("source_identifier", "synthetic:other-row")),
)
def test_outcome_source_row_identity_must_match_forecast(field, value):
    parts = fixture()
    different_origin = replace(parts[1].origin_ref, **{field: value})
    changed = replace(parts[1], origin_ref=different_origin)
    with pytest.raises(ValueError):
        classify((parts[0], changed, parts[2], parts[3]))


def test_incorrect_target_endpoint_is_rejected():
    parts = fixture()
    object.__setattr__(
        parts[1], "theoretical_close_at", parts[0].origin_ref.origin + 2 * HOUR
    )
    with pytest.raises(ValueError):
        classify(parts)


def test_preclosure_rejection_does_not_read_outcome_fields(monkeypatch):
    parts = fixture()
    object.__setattr__(parts[1], "checked_at", parts[0].origin_ref.origin)
    original = HistoricalOutcomeView.__getattribute__
    forbidden = {
        "target",
        "target_valid",
        "original_invalid_reasons",
        "target_manifest_anomaly",
        "target_endpoint_occurrences",
        "feature_window_occurrences",
        "unresolved_occurrences",
    }

    def guarded(self, name):
        if name in forbidden:
            raise AssertionError("preclosure outcome field read")
        return original(self, name)

    with monkeypatch.context() as patch:
        patch.setattr(HistoricalOutcomeView, "__getattribute__", guarded)
        with pytest.raises(ValueError):
            classify(parts)


@pytest.mark.parametrize("linkage", ("missing", "unknown_vocabulary", "contradictory"))
def test_nonmatched_linkage_is_rejected_without_model_abstention(linkage):
    parts = fixture()
    parts = with_occurrences(
        parts, endpoint=(occurrence(parts[0].origin_ref, linkage=linkage),)
    )
    with pytest.raises(ValueError):
        classify(parts)


def test_unresolved_association_is_rejected_even_with_matched_linkage():
    parts = fixture()
    parts = with_occurrences(
        parts,
        unresolved=(
            occurrence(parts[0].origin_ref, collection="unresolved_anomalies"),
        ),
    )
    with pytest.raises(ValueError):
        classify(parts)


def test_native_occurrence_tampering_is_revalidated():
    parts = fixture()
    annotation = occurrence(parts[0].origin_ref)
    parts = with_occurrences(parts, endpoint=(annotation,))
    object.__setattr__(
        annotation, "manifest_record_sha256", digest("synthetic:tampered-record")
    )
    with pytest.raises(ValueError):
        classify(parts)


def test_repeated_tokens_and_occurrences_are_preserved_in_input_order():
    parts = fixture(sample="a_sensitivity")
    first = occurrence(parts[0].origin_ref, field="unknown", position=0)
    second = occurrence(parts[0].origin_ref, field="unknown", position=1)
    parts = with_occurrences(parts, endpoint=(first, second))
    before = canonical_json(parts[1])
    result = classify(parts)
    assert parts[1].target_endpoint_occurrences == (first, second)
    assert canonical_json(parts[1]) == before
    assert result.score_exclusion_reasons == ("target_manifest_anomaly",)
    assert b'"affected_fields":["unknown"]' in before
    assert before.index(b'"position":0') < before.index(b'"position":1')


def test_identical_inputs_produce_identical_canonical_classifications():
    parts = fixture()
    assert canonical_json(classify(parts)) == canonical_json(classify(parts))


def test_mapping_insertion_order_does_not_change_canonical_classification():
    parts = fixture(sample="a_sensitivity")
    first = occurrence(parts[0].origin_ref, field="unknown")
    second = replace(
        first,
        raw=dict(reversed(tuple(first.raw.items()))),
        manifest_record=dict(reversed(tuple(first.manifest_record.items()))),
    )
    left = with_occurrences(parts, endpoint=(first,))
    right = with_occurrences(parts, endpoint=(second,))
    assert canonical_json(left[1]) == canonical_json(right[1])
    assert canonical_json(classify(left)) == canonical_json(classify(right))


def test_source_lexical_reason_order_is_preserved_and_exclusions_are_canonical():
    first = fixture(target_reasons=("next_missing", "current_missing"))
    second = fixture(target_reasons=("current_missing", "next_missing"))
    left, right = classify(first), classify(second)
    assert left.original_target_reasons == ("next_missing", "current_missing")
    assert right.original_target_reasons == ("current_missing", "next_missing")
    assert left.score_exclusion_reasons == right.score_exclusion_reasons
    assert canonical_json(left) != canonical_json(right)


def test_utc_equivalent_inputs_have_identical_canonical_classifications():
    regular = fixture()
    custom = fixture(
        when=TEST_START.astimezone(timezone(timedelta(0), "SyntheticZero"))
    )
    assert canonical_json(classify(regular)) == canonical_json(classify(custom))


def test_signed_zero_is_preserved_in_scored_values():
    forecast, outcome, scope, build = fixture()
    forecast = replace(forecast, prediction=-0.0, forecast_id=None)
    outcome = replace(outcome, target=-0.0)
    result = classify((forecast, outcome, scope, build))
    payload = canonical_json(result)
    assert b'"prediction":-0.0' in payload
    assert b'"target":-0.0' in payload


def test_null_and_absent_raw_keys_remain_distinct():
    parts = fixture()
    annotation = occurrence(parts[0].origin_ref)
    with_null = canonical_json(annotation.raw)
    without_null = canonical_json(
        {key: value for key, value in annotation.raw.items() if key != "note"}
    )
    assert with_null != without_null and b'"note":null' in with_null
    assert "absent" not in annotation.raw
    classify(with_occurrences(parts, endpoint=(annotation,)))
    assert canonical_json(annotation.raw) == with_null


@pytest.mark.parametrize(
    "field, value",
    (
        ("prediction", float("nan")),
        ("prediction", float("inf")),
        ("prediction", True),
        ("target", float("nan")),
        ("target", float("inf")),
        ("target", None),
    ),
)
def test_nonfinite_or_contradictory_numeric_inputs_fail_closed(field, value):
    parts = fixture("expanding_mean")
    record = parts[0] if field == "prediction" else parts[1]
    object.__setattr__(record, field, value)
    with pytest.raises(ValueError):
        classify(parts)


@pytest.mark.parametrize("bad_outcome", (None, {}, object()))
def test_absent_or_untyped_outcome_cannot_be_classified(bad_outcome):
    parts = fixture()
    with pytest.raises(ValueError):
        classify_native_score(
            parts[0],
            bad_outcome,
            scope=parts[2],
            scoring_build_id=parts[3],
            sample_policy="a_primary",
        )


def test_output_cannot_claim_historical_authority_or_enable_decisions():
    result = classify(fixture())
    assert type(result) is ScoreClassification
    for name in (
        "authenticated_historical_score",
        "historical_execution_completed",
        "point_in_time_verified",
        "decision_eligible",
    ):
        assert getattr(result, name) is False
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            setattr(result, name, True)
    assert not hasattr(native_scoring, "score_historical")
    assert not hasattr(native_scoring, "ClosedHistoricalOutcomeRef")
    assert contract.public_authority_issuers() == ()


@pytest.mark.parametrize("field", ("source_mode", "source_authentication"))
def test_historical_mode_labels_are_rejected(field):
    parts = fixture()
    if field == "source_mode":
        object.__setattr__(
            parts[0].origin_ref.provenance, field, "authenticated_pinned_history"
        )
    else:
        object.__setattr__(parts[1], field, "authenticated_pinned_history")
    with pytest.raises(ValueError):
        classify(parts)


def test_claimed_execution_identity_is_rejected():
    parts = fixture()
    forecast = replace(
        parts[0],
        execution_instance_id=digest("synthetic:claimed-execution"),
        forecast_id=None,
    )
    with pytest.raises(ValueError):
        classify((forecast, parts[1], parts[2], parts[3]))


def test_kernel_has_no_io_model_network_clock_or_writer_side_effects(monkeypatch):
    parts = fixture()

    def forbidden(*args, **kwargs):
        raise AssertionError("synthetic classifier performed forbidden side effect")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        for name in ("open", "read_bytes", "read_text", "write_bytes", "write_text"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(subprocess, "run", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(time, "monotonic", forbidden)
        for module, names in (
            (statistical_baselines, ("fit_ar", "predict_ar", "predict_mean")),
            (ridge_regression, ("fit_scaler", "fit_ridge", "predict", "select_alpha")),
        ):
            for name in names:
                patch.setattr(module, name, forbidden)
        assert classify(parts).score_status == "scored"
