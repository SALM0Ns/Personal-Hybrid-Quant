"""Invented complete scopes for the pure native accounting kernel."""

from __future__ import annotations

import builtins
import hashlib
import itertools
import socket
import subprocess
import time
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from quant.features.engine import FEATURES
from quant.research import historical_scoring_contract as contract
from quant.research import (
    native_accounting,
    native_scoring,
    ridge_regression,
    statistical_baselines,
)
from quant.research.evaluation_reporting import timestamp_digest
from quant.research.forecast_accounting import MODELS, SAMPLES, UNKNOWN_AVAILABILITY
from quant.research.forecast_dataset import ANALYSIS_AS_OF, TEST_START
from quant.research.historical_representation import (
    POLICY_VERSION as NATIVE_POLICY_VERSION,
)
from quant.research.historical_representation import (
    SCHEMA_VERSION as NATIVE_SCHEMA_VERSION,
)
from quant.research.historical_scoring_contract import (
    SCHEMA_VERSION,
    AccountingReconciliation,
    HistoricalForecast,
    HistoricalOriginRef,
    HistoricalOutcomeView,
    HistoricalProvenanceRef,
    HistoricalScopeSpec,
    canonical_json,
    scoring_build_id,
    validate_reconciliation,
)
from quant.research.native_accounting import reconcile_native_accounting

HOUR = timedelta(hours=1)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def provenance():
    return HistoricalProvenanceRef(
        **{
            field: digest("synthetic:6c:" + field)
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
        manifest_version="synthetic-6c-manifest-v1",
        feature_version="synthetic-6c-features-v1",
        feature_order=tuple(FEATURES),
        source_mode="synthetic_fixture",
    )


def scope_fixture(size=3, *, when=TEST_START, audit_only=False):
    source = provenance()
    origins = tuple(
        HistoricalOriginRef(
            provenance=source,
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            source_identifier=f"synthetic:6c-ledger:{index}",
            source_row_index=index,
            origin=when + index * HOUR,
            feature_open_t=when + (index - 1) * HOUR,
            target_theoretical_close_at=when + (index + 1) * HOUR,
            period_id="test",
        )
        for index in range(size)
    )
    audit = ()
    if audit_only:
        audit = (
            HistoricalOriginRef(
                provenance=source,
                exchange="binance",
                symbol="BTC/USDT",
                timeframe="1h",
                source_identifier="synthetic:6c-audit-only",
                source_row_index=999,
                origin=ANALYSIS_AS_OF,
                feature_open_t=ANALYSIS_AS_OF - HOUR,
                target_theoretical_close_at=ANALYSIS_AS_OF + HOUR,
                period_id="outside_approved_evaluation_window",
            ),
        )
    scope = HistoricalScopeSpec(
        provenance=source,
        period_id="test",
        start=when,
        end_exclusive=when + size * HOUR,
        analysis_as_of=ANALYSIS_AS_OF,
        intended_use="test_frozen_alpha_comparison",
        origins=origins,
        model_ids=MODELS,
        sample_policies=SAMPLES,
        audit_only_origins=audit,
        frozen_ridge_selection_id=digest("synthetic:6c-frozen-selection"),
    )
    build = scoring_build_id(
        scope.scoring_spec_id,
        code_sha256=digest("synthetic:6c-code"),
        dependency_versions={"python": "3.12"},
        deterministic_build_configuration={"fixture": "native-6c"},
    )
    return scope, build


def forecast_fixture(scope, build, origin, model, sample, *, abstained=False):
    fit_model = model in {"ar_1", "ridge_7"}
    return HistoricalForecast(
        schema_version=SCHEMA_VERSION,
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=build,
        execution_instance_id=None,
        origin_ref=origin,
        model_id=model,
        sample_policy=sample,
        forecast_status="abstained" if abstained else "emitted",
        prediction=None if abstained else 0.0 if model == "zero_return" else 0.125,
        abstention_reasons=("insufficient_training_history",) if abstained else (),
        producer_trace_ref=f"synthetic:6c-trace:{origin.source_row_index}",
        model_version="synthetic-6c-model-v1",
        history_count=0 if model == "zero_return" else 719 if abstained else 720,
        history_cutoff=None if model == "zero_return" else origin.origin,
        scheduled_refit_at=origin.origin.replace(hour=0) if fit_model else None,
        fit_ref="synthetic:6c-fit" if fit_model and not abstained else None,
        alpha_selection_ref=scope.frozen_ridge_selection_id
        if model == "ridge_7" and not abstained
        else None,
        selected_alpha=1.0 if model == "ridge_7" and not abstained else None,
    )


def outcome_fixture(origin, *, unavailable=False):
    return HistoricalOutcomeView(
        origin_ref=origin,
        target=None if unavailable else 0.25,
        target_valid=not unavailable,
        original_invalid_reasons=("next_missing",) if unavailable else (),
        ordered_invalid_reasons=("next_missing",) if unavailable else (),
        target_primary_null_reason="next_missing" if unavailable else None,
        target_manifest_anomaly=False,
        target_value_sensitive=None,
        target_endpoint_occurrences=(),
        feature_window_occurrences=(),
        unresolved_occurrences=(),
        anomaly_evidence_status="no_occurrences",
        source_authentication="synthetic_fixture",
        native_schema_version=NATIVE_SCHEMA_VERSION,
        native_policy_version=NATIVE_POLICY_VERSION,
        theoretical_close_at=origin.origin + HOUR,
        checked_at=origin.origin + HOUR,
        closure="closed",
        native_envelope_sha256=digest("synthetic:6c-envelope"),
    )


def records_fixture(
    model="expanding_mean",
    sample="a_primary",
    *,
    statuses=("scored", "emitted_but_not_scored", "not_scored_no_forecast"),
    scope=None,
    build=None,
):
    if scope is None:
        scope, build = scope_fixture(len(statuses))
    forecasts, classifications = [], []
    for origin, status in zip(scope.origins, statuses, strict=True):
        forecast = forecast_fixture(
            scope,
            build,
            origin,
            model,
            sample,
            abstained=status == "not_scored_no_forecast",
        )
        outcome = outcome_fixture(
            origin, unavailable=status == "emitted_but_not_scored"
        )
        classification = native_scoring.classify_native_score(
            forecast,
            outcome,
            scope=scope,
            scoring_build_id=build,
            sample_policy=sample,
        )
        assert classification.score_status == status
        forecasts.append(forecast)
        classifications.append(classification)
    return scope, build, tuple(forecasts), tuple(classifications)


def reconcile(parts, *, model="expanding_mean", sample="a_primary", **changes):
    scope, build, forecasts, classifications = parts
    options = {
        "model_id": model,
        "sample_policy": sample,
        "scoring_build_id": build,
        "forecasts": forecasts,
        "score_classifications": classifications,
    }
    options.update(changes)
    return reconcile_native_accounting(scope, **options)


def test_complete_scope_produces_exact_mixed_accounting():
    parts = records_fixture()
    result = reconcile(parts)
    assert type(result) is AccountingReconciliation
    assert dict(result.counts_and_reasons) == {
        "origin_count": 3,
        "forecast_count": 2,
        "abstention_count": 1,
        "scored_count": 1,
        "emitted_but_not_scored_count": 1,
        "not_scored_no_forecast_count": 1,
        "exclusive_abstention_reason_counts": (("insufficient_training_history", 1),),
        "primary_score_reason_counts": (
            ("next_missing", 1),
            ("insufficient_training_history", 1),
        ),
        "overlapping_diagnostic_counts": (
            ("next_missing", 1),
            ("insufficient_training_history", 1),
            (UNKNOWN_AVAILABILITY, 3),
        ),
        "forecast_coverage": 2 / 3,
    }
    assert result.forecast_ids == tuple(item.forecast_id for item in parts[2])
    assert result.classification_keys == result.forecast_ids
    assert result.scored_origins == (parts[0].origins[0].origin,)
    assert result.scored_timestamp_set_sha256 == timestamp_digest(result.scored_origins)
    validate_reconciliation(result, forecasts=parts[2], classifications=parts[3])


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("sample", SAMPLES)
def test_all_emitted_and_scored_for_each_model_and_sample(model, sample):
    parts = records_fixture(model, sample, statuses=("scored",) * 3)
    result = reconcile(parts, model=model, sample=sample)
    counts = result.counts_and_reasons
    assert counts["forecast_count"] == counts["scored_count"] == 3
    assert counts["abstention_count"] == 0
    assert counts["forecast_coverage"] == 1.0
    assert counts["exclusive_abstention_reason_counts"] == ()
    assert counts["primary_score_reason_counts"] == ()
    assert counts["overlapping_diagnostic_counts"] == ((UNKNOWN_AVAILABILITY, 3),)


@pytest.mark.parametrize("model", MODELS[1:])
@pytest.mark.parametrize("sample", SAMPLES)
def test_all_abstained_retains_model_reasons(model, sample):
    parts = records_fixture(model, sample, statuses=("not_scored_no_forecast",) * 3)
    result = reconcile(parts, model=model, sample=sample)
    counts = result.counts_and_reasons
    assert counts["forecast_count"] == counts["scored_count"] == 0
    assert counts["abstention_count"] == counts["not_scored_no_forecast_count"] == 3
    assert counts["forecast_coverage"] == 0.0
    assert counts["exclusive_abstention_reason_counts"] == (
        ("insufficient_training_history", 3),
    )
    assert result.scored_origins == ()
    assert result.scored_timestamp_set_sha256 == timestamp_digest(())


def test_each_model_sample_has_independent_accounting_identity():
    scope, build = scope_fixture()
    reconciliations = []
    for model, sample in itertools.product(MODELS, SAMPLES):
        parts = records_fixture(
            model, sample, statuses=("scored",) * 3, scope=scope, build=build
        )
        reconciliations.append(reconcile(parts, model=model, sample=sample))
    assert len({item.reconciliation_id for item in reconciliations}) == 8


@pytest.mark.parametrize("kind", ("forecast", "classification"))
@pytest.mark.parametrize("corruption", ("missing", "duplicate", "extra"))
def test_inexact_forecast_or_classification_sets_fail_closed(kind, corruption):
    parts = records_fixture()
    position = 2 if kind == "forecast" else 3
    records = parts[position]
    changed = {
        "missing": records[:-1],
        "duplicate": (records[0], records[0], records[2]),
        "extra": (*records, records[-1]),
    }[corruption]
    key = "forecasts" if kind == "forecast" else "score_classifications"
    with pytest.raises(ValueError):
        reconcile(parts, **{key: changed})


def test_extra_out_of_scope_origin_is_not_filtered():
    parts = records_fixture()
    reference = replace(
        parts[0].origins[-1],
        source_identifier="synthetic:6c-extra-origin",
        source_row_index=100,
        origin=parts[0].end_exclusive,
        feature_open_t=parts[0].end_exclusive - HOUR,
        target_theoretical_close_at=parts[0].end_exclusive + HOUR,
    )
    extra = replace(parts[2][0], origin_ref=reference, forecast_id=None)
    with pytest.raises(ValueError):
        reconcile(parts, forecasts=(*parts[2], extra))


def test_duplicate_origin_with_distinct_forecast_ids_is_rejected():
    parts = records_fixture()
    duplicate = replace(
        parts[2][0], producer_trace_ref="synthetic:6c-second-producer", forecast_id=None
    )
    duplicate_classification = replace(parts[3][0], forecast_id=duplicate.forecast_id)
    assert duplicate.forecast_id != parts[2][0].forecast_id
    with pytest.raises(ValueError):
        reconcile(
            parts,
            forecasts=(parts[2][0], duplicate, parts[2][2]),
            score_classifications=(
                parts[3][0],
                duplicate_classification,
                parts[3][2],
            ),
        )


def test_audit_only_origin_contamination_is_rejected_and_audit_refs_retained():
    scope, build = scope_fixture(audit_only=True)
    parts = records_fixture(scope=scope, build=build)
    result = reconcile(parts)
    assert result.scope.audit_only_origins == scope.audit_only_origins
    assert result.counts_and_reasons["origin_count"] == 3
    assert scope.audit_only_origins[0].origin not in result.scored_origins
    object.__setattr__(parts[2][0], "origin_ref", scope.audit_only_origins[0])
    with pytest.raises(ValueError):
        reconcile(parts)


@pytest.mark.parametrize(
    "key,value", (("model", "zero_return"), ("sample", "a_sensitivity"))
)
def test_wrong_selected_model_or_sample_is_rejected(key, value):
    with pytest.raises(ValueError):
        reconcile(records_fixture(), **{key: value})


def test_mixed_model_records_are_rejected_even_in_shared_scope():
    parts = records_fixture()
    substitute = forecast_fixture(
        parts[0], parts[1], parts[0].origins[0], "zero_return", "a_primary"
    )
    with pytest.raises(ValueError):
        reconcile(parts, forecasts=(substitute, *parts[2][1:]))


@pytest.mark.parametrize(
    "value", (None, "bad", "A" * 64, digest("synthetic:6c-wrong-build"))
)
def test_incorrect_build_identity_is_rejected(value):
    with pytest.raises(ValueError):
        reconcile(records_fixture(), scoring_build_id=value)


def test_forecast_specification_substitution_is_rejected():
    parts = records_fixture()
    substitute = replace(
        parts[2][0], scoring_spec_id=digest("synthetic:other-spec"), forecast_id=None
    )
    with pytest.raises(ValueError):
        reconcile(parts, forecasts=(substitute, *parts[2][1:]))


def test_equal_timestamp_with_wrong_source_identity_is_rejected():
    parts = records_fixture()
    changed_source = replace(
        parts[0].provenance, gold_sha256=digest("synthetic:other-gold")
    )
    changed_origin = replace(parts[0].origins[0], provenance=changed_source)
    substitute = replace(parts[2][0], origin_ref=changed_origin, forecast_id=None)
    with pytest.raises(ValueError):
        reconcile(parts, forecasts=(substitute, *parts[2][1:]))


def test_wrong_classification_parent_id_is_rejected():
    parts = records_fixture()
    substitute = replace(parts[3][0], forecast_id=digest("synthetic:other-forecast"))
    with pytest.raises(ValueError):
        reconcile(parts, score_classifications=(substitute, *parts[3][1:]))


def test_classification_for_revised_forecast_cannot_replace_original_parent():
    parts = records_fixture()
    revised = replace(
        parts[2][0], producer_trace_ref="synthetic:revised-producer", forecast_id=None
    )
    substitute = replace(parts[3][0], forecast_id=revised.forecast_id)
    with pytest.raises(ValueError):
        reconcile(parts, score_classifications=(substitute, *parts[3][1:]))


@pytest.mark.parametrize(
    "field,value",
    (
        ("prediction", 0.5),
        ("model_id", "zero_return"),
        ("sample_policy", "a_sensitivity"),
    ),
)
def test_matching_parent_digest_cannot_hide_classification_field_substitution(
    field, value
):
    parts = records_fixture()
    substitute = replace(parts[3][0], **{field: value})
    assert substitute.forecast_id == parts[2][0].forecast_id
    with pytest.raises(ValueError):
        reconcile(parts, score_classifications=(substitute, *parts[3][1:]))


@pytest.mark.parametrize("field", ("abstention_reasons", "score_exclusion_reasons"))
def test_incorrect_reason_precedence_fails_closed(field):
    parts = records_fixture()
    classification = parts[3][2]
    if field == "abstention_reasons":
        reasons = ("nonfinite_prediction", "insufficient_training_history")
    else:
        reasons = ("insufficient_training_history", "next_missing")
    object.__setattr__(classification, field, reasons)
    with pytest.raises(ValueError):
        reconcile(parts)


def test_overlapping_diagnostics_do_not_enter_exclusive_reason_funnels():
    parts = records_fixture()
    result = reconcile(parts)
    counts = result.counts_and_reasons
    assert dict(counts["overlapping_diagnostic_counts"])[UNKNOWN_AVAILABILITY] == 3
    assert UNKNOWN_AVAILABILITY not in dict(counts["primary_score_reason_counts"])
    assert UNKNOWN_AVAILABILITY not in dict(
        counts["exclusive_abstention_reason_counts"]
    )
    assert sum(value for _, value in counts["primary_score_reason_counts"]) == 2
    assert sum(value for _, value in counts["overlapping_diagnostic_counts"]) == 5


def test_reordering_independent_input_sets_is_canonical_and_deterministic():
    parts = records_fixture()
    expected = canonical_json(reconcile(parts))
    for forecasts in itertools.permutations(parts[2]):
        for classifications in itertools.permutations(parts[3]):
            result = reconcile(
                parts, forecasts=forecasts, score_classifications=classifications
            )
            assert canonical_json(result) == expected
    assert canonical_json(parts[2]) == canonical_json(records_fixture()[2])


def test_scored_origin_set_is_exact_sorted_and_uses_existing_digest_encoding():
    parts = records_fixture(statuses=("scored", "emitted_but_not_scored", "scored"))
    result = reconcile(parts, forecasts=tuple(reversed(parts[2])))
    expected = (TEST_START, TEST_START + 2 * HOUR)
    payload = b"2025-01-01T00:00:00Z\n2025-01-01T02:00:00Z\n"
    assert result.scored_origins == expected
    assert result.scored_timestamp_set_sha256 == hashlib.sha256(payload).hexdigest()


def test_all_conservation_equations_hold():
    counts = reconcile(records_fixture()).counts_and_reasons
    assert (
        counts["origin_count"] == counts["forecast_count"] + counts["abstention_count"]
    )
    assert counts["forecast_count"] == (
        counts["scored_count"] + counts["emitted_but_not_scored_count"]
    )
    assert counts["abstention_count"] == counts["not_scored_no_forecast_count"]
    assert counts["origin_count"] == counts["scored_count"] + sum(
        count for _, count in counts["primary_score_reason_counts"]
    )


def test_empty_synthetic_scope_has_zero_counts_null_coverage_and_empty_digest():
    scope, build = scope_fixture(0)
    result = reconcile((scope, build, (), ()))
    for name in (
        "origin_count",
        "forecast_count",
        "abstention_count",
        "scored_count",
        "emitted_but_not_scored_count",
        "not_scored_no_forecast_count",
    ):
        assert result.counts_and_reasons[name] == 0
    assert result.counts_and_reasons["forecast_coverage"] is None
    assert (
        result.forecast_ids == result.classification_keys == result.scored_origins == ()
    )
    assert result.scored_timestamp_set_sha256 == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("build", (None, "invalid", "A" * 64, True))
def test_empty_scope_does_not_bypass_build_identity_validation(build):
    scope, _ = scope_fixture(0)
    with pytest.raises(ValueError):
        reconcile((scope, build, (), ()))


def test_selected_method_must_belong_to_declared_scope():
    scope, _ = scope_fixture(0)
    scope = replace(
        scope,
        model_ids=("zero_return",),
        frozen_ridge_selection_id=None,
        scoring_spec_id=None,
    )
    with pytest.raises(ValueError):
        reconcile((scope, digest("synthetic:6c-empty-build"), (), ()))


def test_nonempty_scope_with_no_records_does_not_fabricate_abstentions():
    parts = records_fixture()
    with pytest.raises(ValueError):
        reconcile(parts, forecasts=(), score_classifications=())


def test_historical_mode_label_cannot_authenticate_or_enable_accounting():
    parts = records_fixture()
    object.__setattr__(
        parts[0].provenance, "source_mode", "authenticated_pinned_history"
    )
    with pytest.raises(ValueError):
        reconcile(parts)


def test_execution_instance_claim_is_rejected():
    parts = records_fixture()
    substitute = replace(
        parts[2][0],
        execution_instance_id=digest("synthetic:claimed-execution"),
        forecast_id=None,
    )
    with pytest.raises(ValueError):
        reconcile(parts, forecasts=(substitute, *parts[2][1:]))


@pytest.mark.parametrize(
    "field",
    ("scoring_spec_id", "origin_set_sha256", "source_origin_identity_set_sha256"),
)
def test_missing_scope_identity_is_not_repaired(field):
    parts = records_fixture()
    object.__setattr__(parts[0], field, None)
    with pytest.raises(ValueError):
        reconcile(parts)
    assert getattr(parts[0], field) is None


def test_missing_forecast_id_is_not_repaired():
    parts = records_fixture()
    object.__setattr__(parts[2][0], "forecast_id", None)
    with pytest.raises(ValueError):
        reconcile(parts)
    assert parts[2][0].forecast_id is None


@pytest.mark.parametrize("field", ("forecasts", "score_classifications"))
def test_untyped_mutable_or_unknown_record_inputs_are_rejected(field):
    parts = records_fixture()
    for value in (None, [], (object(),)):
        with pytest.raises(ValueError):
            reconcile(parts, **{field: value})


def test_invalid_period_and_policy_are_rejected():
    parts = records_fixture()
    with pytest.raises(ValueError):
        reconcile(parts, policy_version="future-policy")
    object.__setattr__(parts[0], "period_id", "training_history")
    with pytest.raises(ValueError):
        reconcile(parts)


def test_output_authority_properties_are_fixed_false_and_immutable():
    result = reconcile(records_fixture())
    for name in (
        "historical_completion_authenticated",
        "authenticated_historical_score",
        "historical_execution_completed",
        "point_in_time_verified",
        "decision_eligible",
        "historical_execution_verified",
    ):
        assert getattr(result, name) is False
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            setattr(result, name, True)
    assert not hasattr(result, "accounting_complete")
    assert not hasattr(native_accounting, "HistoricalAccountingResult")
    assert contract.public_authority_issuers() == ()


def test_utc_equivalent_inputs_produce_identical_accounting_bytes():
    plain = records_fixture()
    custom_scope, custom_build = scope_fixture(
        when=TEST_START.astimezone(timezone(timedelta(0), "SyntheticZero"))
    )
    custom = records_fixture(scope=custom_scope, build=custom_build)
    assert canonical_json(reconcile(plain)) == canonical_json(reconcile(custom))


def test_kernel_cannot_read_outcomes_score_forecast_fit_or_perform_io(monkeypatch):
    parts = records_fixture()

    def forbidden(*args, **kwargs):
        raise AssertionError("accounting kernel performed forbidden side effect")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        for name in ("open", "read_bytes", "read_text", "write_bytes", "write_text"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(subprocess, "run", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(time, "monotonic", forbidden)
        patch.setattr(native_scoring, "classify_native_score", forbidden)
        patch.setattr(contract.HistoricalOutcomeView, "__post_init__", forbidden)
        for module, names in (
            (statistical_baselines, ("fit_ar", "predict_ar", "predict_mean")),
            (ridge_regression, ("fit_scaler", "fit_ridge", "predict", "select_alpha")),
        ):
            for name in names:
                patch.setattr(module, name, forbidden)
        result = reconcile(parts)
        assert result.counts_and_reasons["origin_count"] == 3
