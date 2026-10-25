"""Synthetic tests for the Stage A historical scoring data contract."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from quant.features.engine import FEATURES
from quant.research import historical_scoring_contract as contract
from quant.research.forecast_accounting import UNKNOWN_AVAILABILITY
from quant.research.forecast_dataset import (
    ANALYSIS_AS_OF,
    DATASET_CONTRACT_VERSION,
    PROTOCOL_VERSION,
    TEST_START,
    VALIDATION_START,
)
from quant.research.historical_projection import OpaqueSourceRef
from quant.research.historical_representation import (
    POLICY_VERSION as NATIVE_POLICY_VERSION,
)
from quant.research.historical_representation import (
    SCHEMA_VERSION as NATIVE_SCHEMA_VERSION,
)
from quant.research.historical_representation import NativeOccurrence
from quant.research.historical_scoring_contract import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    AccountingReconciliation,
    CanonicalScoringBundle,
    HistoricalAccountingResult,
    HistoricalForecast,
    HistoricalOriginRef,
    HistoricalOutcomeView,
    HistoricalProvenanceRef,
    HistoricalScopeBlock,
    HistoricalScopeSpec,
    HistoricalScore,
    ScoreClassification,
    canonical_json,
    canonical_loads,
    canonical_scoring_payload,
    payload_sha256,
    public_authority_issuers,
    record_from_mapping,
    scoring_build_id,
    scoring_spec_id,
    validate_accounting_result,
    validate_classification_parent,
    validate_forecast,
    validate_payload_sha256,
    validate_reconciliation,
    validate_scope,
    validate_score,
)

HOUR = timedelta(hours=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _provenance(**changes) -> HistoricalProvenanceRef:
    values = {
        "dataset_spec_id": _hash("dataset-spec"),
        "source_artifact_build_id": _hash("source-build"),
        "silver_sha256": _hash("silver"),
        "gold_sha256": _hash("gold"),
        "origin_ledger_sha256": _hash("origin-ledger"),
        "dataset_validation_sha256": _hash("dataset-validation"),
        "provenance_json_sha256": _hash("provenance-json"),
        "provenance_sidecar_sha256": _hash("provenance-sidecar"),
        "manifest_canonical_sha256": _hash("manifest-canonical"),
        "manifest_raw_sha256": _hash("manifest-raw"),
        "manifest_version": "candidate-v1",
        "feature_version": "qnt-002b-feature-v1",
        "feature_order": tuple(FEATURES),
        "source_receipt_sha256": _hash("source-receipt"),
        "source_mode": "synthetic_fixture",
    }
    values.update(changes)
    return HistoricalProvenanceRef(**values)


def _origin(
    *,
    provenance: HistoricalProvenanceRef | None = None,
    when: datetime = VALIDATION_START,
) -> HistoricalOriginRef:
    provenance = provenance or _provenance()
    return HistoricalOriginRef(
        provenance=provenance,
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        source_identifier="synthetic:origin-ledger",
        source_row_index=0,
        origin=when,
        feature_open_t=when - HOUR,
        target_theoretical_close_at=when + HOUR,
        period_id="validation",
    )


def _scope(
    *,
    provenance: HistoricalProvenanceRef | None = None,
    origin: HistoricalOriginRef | None = None,
    model_ids: tuple[str, ...] = ("zero_return",),
    sample_policies: tuple[str, ...] = ("a_primary",),
    scoring_id: str | None = None,
) -> HistoricalScopeSpec:
    provenance = provenance or _provenance()
    origin = origin or _origin(provenance=provenance)
    return HistoricalScopeSpec(
        provenance=provenance,
        period_id="validation",
        start=origin.origin,
        end_exclusive=origin.origin + HOUR,
        analysis_as_of=ANALYSIS_AS_OF,
        intended_use="validation_candidate_tuning_diagnostics",
        origins=(origin,),
        model_ids=model_ids,
        sample_policies=sample_policies,
        scoring_spec_id=scoring_id,
    )


def _build(scope: HistoricalScopeSpec, token: str = "code") -> str:
    return scoring_build_id(
        scope.scoring_spec_id,
        code_sha256=_hash(token),
        dependency_versions={"python": "3.12.12"},
        deterministic_build_configuration={"mode": "synthetic-test"},
    )


def _forecast(
    scope: HistoricalScopeSpec,
    *,
    build_id: str | None = None,
    execution_id: str | None = None,
    producer_trace_ref: str = "synthetic:trace:zero",
) -> HistoricalForecast:
    return HistoricalForecast(
        schema_version=SCHEMA_VERSION,
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=build_id or _build(scope),
        execution_instance_id=execution_id,
        origin_ref=scope.origins[0],
        model_id="zero_return",
        sample_policy="a_primary",
        forecast_status="emitted",
        prediction=0.0,
        abstention_reasons=(),
        producer_trace_ref=producer_trace_ref,
        model_version="zero-return-v1",
        history_count=0,
        history_cutoff=None,
        scheduled_refit_at=None,
        fit_ref=None,
        alpha_selection_ref=None,
        selected_alpha=None,
    )


def _classification(forecast: HistoricalForecast) -> ScoreClassification:
    return ScoreClassification(
        forecast_id=forecast.forecast_id,
        origin_ref=forecast.origin_ref,
        model_id=forecast.model_id,
        sample_policy=forecast.sample_policy,
        forecast_status=forecast.forecast_status,
        score_status="scored",
        prediction=forecast.prediction,
        target=0.01,
        abstention_reasons=forecast.abstention_reasons,
        original_target_reasons=(),
        score_exclusion_reasons=(),
        primary_score_reason="scored",
        all_diagnostics=(UNKNOWN_AVAILABILITY,),
    )


def _outcome(origin: HistoricalOriginRef, **changes) -> HistoricalOutcomeView:
    values = {
        "origin_ref": origin,
        "target": 0.01,
        "target_valid": True,
        "original_invalid_reasons": (),
        "ordered_invalid_reasons": (),
        "target_primary_null_reason": None,
        "target_manifest_anomaly": False,
        "target_value_sensitive": False,
        "target_endpoint_occurrences": (),
        "feature_window_occurrences": (),
        "unresolved_occurrences": (),
        "anomaly_evidence_status": "no_occurrences",
        "source_authentication": "synthetic_fixture",
        "native_schema_version": NATIVE_SCHEMA_VERSION,
        "native_policy_version": NATIVE_POLICY_VERSION,
        "theoretical_close_at": origin.origin + HOUR,
        "checked_at": origin.origin + HOUR,
        "closure": "closed",
        "native_envelope_sha256": _hash("native-envelope"),
    }
    values.update(changes)
    return HistoricalOutcomeView(**values)


def _score(
    scope: HistoricalScopeSpec,
    forecast: HistoricalForecast,
    classification: ScoreClassification,
    outcome: HistoricalOutcomeView,
) -> HistoricalScore:
    return HistoricalScore(
        schema_version=SCHEMA_VERSION,
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=forecast.scoring_build_id,
        execution_instance_id=forecast.execution_instance_id,
        forecast_id=forecast.forecast_id,
        outcome_view_sha256=payload_sha256(outcome),
        origin_ref=forecast.origin_ref,
        model_id=forecast.model_id,
        sample_policy=forecast.sample_policy,
        period_id=forecast.origin_ref.period_id,
        checked_at=forecast.origin_ref.target_theoretical_close_at,
        forecast_status=classification.forecast_status,
        score_status=classification.score_status,
        prediction=classification.prediction,
        target=classification.target,
        abstention_reasons=classification.abstention_reasons,
        original_target_reasons=classification.original_target_reasons,
        score_exclusion_reasons=classification.score_exclusion_reasons,
        primary_score_reason=classification.primary_score_reason,
        all_diagnostics=classification.all_diagnostics,
    )


def _counts() -> dict[str, object]:
    return {
        "origin_count": 1,
        "forecast_count": 1,
        "abstention_count": 0,
        "scored_count": 1,
        "emitted_but_not_scored_count": 0,
        "not_scored_no_forecast_count": 0,
        "exclusive_abstention_reason_counts": (),
        "primary_score_reason_counts": (),
        "overlapping_diagnostic_counts": ((UNKNOWN_AVAILABILITY, 1),),
        "forecast_coverage": 1.0,
    }


def _mixed_scope(
    *, audit_only_origins: tuple[HistoricalOriginRef, ...] = ()
) -> HistoricalScopeSpec:
    provenance = _provenance()
    origins = tuple(
        replace(
            _origin(provenance=provenance, when=VALIDATION_START + index * HOUR),
            source_identifier=f"synthetic:origin-ledger:{index}",
            source_row_index=index,
        )
        for index in range(3)
    )
    return HistoricalScopeSpec(
        provenance=provenance,
        period_id="validation",
        start=origins[0].origin,
        end_exclusive=origins[-1].origin + HOUR,
        analysis_as_of=ANALYSIS_AS_OF,
        intended_use="validation_candidate_tuning_diagnostics",
        origins=origins,
        model_ids=("expanding_mean",),
        sample_policies=("a_primary",),
        audit_only_origins=audit_only_origins,
    )


def _mean_forecast(
    scope: HistoricalScopeSpec, index: int, *, emitted: bool
) -> HistoricalForecast:
    return HistoricalForecast(
        schema_version=SCHEMA_VERSION,
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=_build(scope),
        execution_instance_id=None,
        origin_ref=scope.origins[index],
        model_id="expanding_mean",
        sample_policy="a_primary",
        forecast_status="emitted" if emitted else "abstained",
        prediction=0.001 * (index + 1) if emitted else None,
        abstention_reasons=() if emitted else ("insufficient_training_history",),
        producer_trace_ref=f"synthetic:mean:{index}",
        model_version="mean-v1",
        history_count=720 if emitted else 719,
        history_cutoff=scope.origins[index].origin,
        scheduled_refit_at=None,
        fit_ref=None,
        alpha_selection_ref=None,
        selected_alpha=None,
    )


def _mixed_records(
    scope: HistoricalScopeSpec,
) -> tuple[tuple[HistoricalForecast, ...], tuple[ScoreClassification, ...]]:
    forecasts = (
        _mean_forecast(scope, 0, emitted=True),
        _mean_forecast(scope, 1, emitted=True),
        _mean_forecast(scope, 2, emitted=False),
    )
    classifications = (
        ScoreClassification(
            forecast_id=forecasts[0].forecast_id,
            origin_ref=forecasts[0].origin_ref,
            model_id="expanding_mean",
            sample_policy="a_primary",
            forecast_status="emitted",
            score_status="scored",
            prediction=forecasts[0].prediction,
            target=0.01,
            abstention_reasons=(),
            original_target_reasons=(),
            score_exclusion_reasons=(),
            primary_score_reason="scored",
            all_diagnostics=(UNKNOWN_AVAILABILITY,),
        ),
        ScoreClassification(
            forecast_id=forecasts[1].forecast_id,
            origin_ref=forecasts[1].origin_ref,
            model_id="expanding_mean",
            sample_policy="a_primary",
            forecast_status="emitted",
            score_status="emitted_but_not_scored",
            prediction=forecasts[1].prediction,
            target=None,
            abstention_reasons=(),
            original_target_reasons=("next_missing",),
            score_exclusion_reasons=("next_missing",),
            primary_score_reason="next_missing",
            all_diagnostics=("next_missing", UNKNOWN_AVAILABILITY),
        ),
        ScoreClassification(
            forecast_id=forecasts[2].forecast_id,
            origin_ref=forecasts[2].origin_ref,
            model_id="expanding_mean",
            sample_policy="a_primary",
            forecast_status="abstained",
            score_status="not_scored_no_forecast",
            prediction=None,
            target=None,
            abstention_reasons=("insufficient_training_history",),
            original_target_reasons=(),
            score_exclusion_reasons=("insufficient_training_history",),
            primary_score_reason="insufficient_training_history",
            all_diagnostics=(
                "insufficient_training_history",
                UNKNOWN_AVAILABILITY,
            ),
        ),
    )
    return forecasts, classifications


def _mixed_counts() -> dict[str, object]:
    return {
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


def _mixed_reconciliation(
    scope: HistoricalScopeSpec,
    forecasts: tuple[HistoricalForecast, ...],
    classifications: tuple[ScoreClassification, ...],
    *,
    counts: dict[str, object] | None = None,
    scored_origins: tuple[datetime, ...] | None = None,
    scored_digest: str | None = None,
) -> AccountingReconciliation:
    return AccountingReconciliation(
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=forecasts[0].scoring_build_id,
        scope=scope,
        model_id="expanding_mean",
        sample_policy="a_primary",
        forecast_ids=tuple(item.forecast_id for item in forecasts),
        classification_keys=tuple(item.forecast_id for item in classifications),
        counts_and_reasons=_mixed_counts() if counts is None else counts,
        scored_origins=(scope.origins[0].origin,)
        if scored_origins is None
        else scored_origins,
        scored_timestamp_set_sha256=scored_digest,
    )


def _pure_bundle() -> CanonicalScoringBundle:
    scope = _scope()
    forecast = _forecast(scope)
    classification = _classification(forecast)
    outcome = _outcome(forecast.origin_ref)
    reconciliation = AccountingReconciliation(
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=forecast.scoring_build_id,
        scope=scope,
        model_id="zero_return",
        sample_policy="a_primary",
        forecast_ids=(forecast.forecast_id,),
        classification_keys=(classification.forecast_id,),
        counts_and_reasons=_counts(),
        scored_origins=(forecast.origin_ref.origin,),
    )
    return CanonicalScoringBundle(
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        serializer_version="pqta-003d-5f-canonical-v1",
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=forecast.scoring_build_id,
        execution_instance_id=None,
        record_type="accounting_reconciliation",
        source_provenance=scope.provenance,
        scope=scope,
        forecasts=(forecast,),
        outcomes=(outcome,),
        score_classifications=(classification,),
        scores=(),
        reconciliation=reconciliation,
        accounting=None,
        scope_block=None,
        research_only=True,
        execution_ready=False,
        point_in_time_verified=False,
        decision_eligible=False,
    )


def test_all_stage_a_records_construct_and_remain_data_only() -> None:
    scope = _scope()
    execution_id = _hash("execution-instance")
    forecast = _forecast(scope, execution_id=execution_id)
    classification = _classification(forecast)
    outcome = _outcome(forecast.origin_ref)
    score = _score(scope, forecast, classification, outcome)
    reconciliation = AccountingReconciliation(
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=forecast.scoring_build_id,
        scope=scope,
        model_id="zero_return",
        sample_policy="a_primary",
        forecast_ids=(forecast.forecast_id,),
        classification_keys=(classification.forecast_id,),
        counts_and_reasons=_counts(),
        scored_origins=(forecast.origin_ref.origin,),
    )
    accounting = HistoricalAccountingResult(
        schema_version=SCHEMA_VERSION,
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=forecast.scoring_build_id,
        execution_instance_id=execution_id,
        execution_completion_ref="synthetic:unverified-completion",
        scope=scope,
        model_id="zero_return",
        sample_policy="a_primary",
        forecast_ids=(forecast.forecast_id,),
        score_ids=(score.score_id,),
        origin_count=1,
        forecast_count=1,
        abstention_count=0,
        scored_count=1,
        emitted_but_not_scored_count=0,
        not_scored_no_forecast_count=0,
        exclusive_abstention_reason_counts=(),
        primary_score_reason_counts=(),
        overlapping_diagnostic_counts=((UNKNOWN_AVAILABILITY, 1),),
        forecast_coverage=1.0,
        scored_origins=(forecast.origin_ref.origin,),
        scored_timestamp_set_sha256=reconciliation.scored_timestamp_set_sha256,
        audit_only_origins=(),
        reconciliation_id=reconciliation.reconciliation_id,
        accounting_complete=True,
        research_only=True,
        execution_ready=False,
        point_in_time_verified=False,
        decision_eligible=False,
    )
    block = HistoricalScopeBlock(
        scope=scope,
        classification="blocked",
        execution_state="not_run",
        diagnostic_codes=("producer_authority_unavailable",),
        affected_origin_refs=scope.origins,
        executed_forecast_ids=(),
        finalized_score_ids=(),
        missing_origin_refs=scope.origins,
    )

    validate_forecast(forecast, scope=scope)
    validate_classification_parent(classification, forecast)
    validate_score(
        score,
        parent=forecast,
        scope=scope,
        classification=classification,
        outcome=outcome,
    )
    validate_reconciliation(
        reconciliation,
        forecasts=(forecast,),
        classifications=(classification,),
    )
    validate_accounting_result(
        accounting,
        reconciliation=reconciliation,
        forecasts=(forecast,),
        scores=(score,),
    )
    assert block.scope_block_id
    assert not forecast.historical_execution_authenticated
    assert not outcome.historical_outcome_authenticated
    assert not classification.authenticated_historical_score
    assert not score.authenticated_historical_issuance
    assert not reconciliation.historical_completion_authenticated
    assert not accounting.authenticated_historical_completion
    assert public_authority_issuers() == ()


def test_exact_canonical_bundle_is_data_only_and_self_validating() -> None:
    bundle = _pure_bundle()
    payload = canonical_scoring_payload(bundle)
    assert payload.endswith(b"\n")
    assert bundle.payload_sha256 == payload_sha256(bundle)
    assert not bundle.authenticated_historical_bundle
    with pytest.raises(ValueError, match="payload SHA-256 mismatch"):
        replace(bundle, payload_sha256=_hash("wrong-payload"))
    with pytest.raises(ValueError, match="exactly one terminal"):
        replace(
            bundle,
            scope_block=HistoricalScopeBlock(
                scope=bundle.scope,
                classification="blocked",
                execution_state="not_run",
                diagnostic_codes=("producer_authority_unavailable",),
                affected_origin_refs=bundle.scope.origins,
                executed_forecast_ids=(),
                finalized_score_ids=(),
                missing_origin_refs=bundle.scope.origins,
            ),
            payload_sha256=None,
        )


def test_scoring_spec_id_is_nonrecursive_and_deterministic() -> None:
    first = _scope()
    second = _scope()
    assert first.scoring_spec_id == second.scoring_spec_id
    assert scoring_spec_id(first) == first.scoring_spec_id

    changed = _scope(sample_policies=("a_primary", "a_sensitivity"))
    assert changed.scoring_spec_id != first.scoring_spec_id

    original = first.scoring_spec_id
    object.__setattr__(first, "scoring_spec_id", _hash("caller-tampering"))
    assert scoring_spec_id(first) == original
    with pytest.raises(ValueError, match="scoring_spec_id mismatch"):
        validate_scope(first)


def test_incorrect_supplied_scoring_spec_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="scoring_spec_id mismatch"):
        _scope(scoring_id=_hash("wrong"))


@pytest.mark.parametrize(
    "change",
    (
        {"producer_trace_ref": "synthetic:other-trace"},
        {"build_id": _hash("other-build")},
    ),
)
def test_classification_rejects_different_exact_parent(change) -> None:
    scope = _scope()
    parent = _forecast(scope)
    classification = _classification(parent)
    other = _forecast(scope, **change)
    assert other.forecast_id != parent.forecast_id
    with pytest.raises(ValueError, match="parent forecast mismatch"):
        validate_classification_parent(classification, other)


def test_classification_rejects_changed_prediction_and_abstention() -> None:
    scope = _scope(model_ids=("expanding_mean",))
    common = {
        "schema_version": SCHEMA_VERSION,
        "scoring_spec_id": scope.scoring_spec_id,
        "scoring_build_id": _build(scope),
        "execution_instance_id": None,
        "origin_ref": scope.origins[0],
        "model_id": "expanding_mean",
        "sample_policy": "a_primary",
        "producer_trace_ref": "synthetic:mean",
        "model_version": "mean-v1",
        "history_count": 720,
        "history_cutoff": scope.origins[0].origin,
        "scheduled_refit_at": None,
        "fit_ref": None,
        "alpha_selection_ref": None,
        "selected_alpha": None,
    }
    emitted = HistoricalForecast(
        **common,
        forecast_status="emitted",
        prediction=0.1,
        abstention_reasons=(),
    )
    classification = ScoreClassification(
        forecast_id=emitted.forecast_id,
        origin_ref=emitted.origin_ref,
        model_id=emitted.model_id,
        sample_policy=emitted.sample_policy,
        forecast_status="emitted",
        score_status="scored",
        prediction=0.1,
        target=0.01,
        abstention_reasons=(),
        original_target_reasons=(),
        score_exclusion_reasons=(),
        primary_score_reason="scored",
        all_diagnostics=(UNKNOWN_AVAILABILITY,),
    )
    changed_prediction = replace(emitted, prediction=0.2, forecast_id=None)
    abstained = HistoricalForecast(
        **common,
        forecast_status="abstained",
        prediction=None,
        abstention_reasons=("insufficient_training_history",),
    )
    for other in (changed_prediction, abstained):
        with pytest.raises(ValueError, match="parent forecast mismatch"):
            validate_classification_parent(classification, other)


def test_syntactically_valid_wrong_forecast_digest_is_rejected() -> None:
    scope = _scope()
    forecast = _forecast(scope)
    with pytest.raises(ValueError, match="forecast ID mismatch"):
        replace(forecast, forecast_id=_hash("wrong-forecast"))


def test_records_are_frozen() -> None:
    scope = _scope()
    forecast = _forecast(scope)
    with pytest.raises(FrozenInstanceError):
        forecast.prediction = 1.0


def test_zero_offset_custom_timezone_is_utc_equivalent() -> None:
    custom_utc = timezone(timedelta(0), "CustomZero")
    when = VALIDATION_START.astimezone(custom_utc)
    origin = _origin(when=when)
    assert origin.origin.utcoffset() == timedelta(0)


@pytest.mark.parametrize("value", (True, False))
def test_boolean_is_rejected_as_history_count(value) -> None:
    scope = _scope()
    with pytest.raises(ValueError, match="history count"):
        replace(_forecast(scope), history_count=value, forecast_id=None)


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf"), True))
def test_nonfinite_or_boolean_prediction_is_rejected(value) -> None:
    scope = _scope(model_ids=("expanding_mean",))
    with pytest.raises(ValueError, match="finite numeric"):
        HistoricalForecast(
            schema_version=SCHEMA_VERSION,
            scoring_spec_id=scope.scoring_spec_id,
            scoring_build_id=_build(scope),
            execution_instance_id=None,
            origin_ref=scope.origins[0],
            model_id="expanding_mean",
            sample_policy="a_primary",
            forecast_status="emitted",
            prediction=value,
            abstention_reasons=(),
            producer_trace_ref="synthetic:mean",
            model_version="mean-v1",
            history_count=720,
            history_cutoff=scope.origins[0].origin,
            scheduled_refit_at=None,
            fit_ref=None,
            alpha_selection_ref=None,
            selected_alpha=None,
        )


def test_wrong_period_and_timeline_are_rejected() -> None:
    origin = _origin()
    with pytest.raises(ValueError, match="period mismatch"):
        replace(origin, period_id="test")
    with pytest.raises(ValueError, match="origin timeline"):
        replace(origin, feature_open_t=origin.origin)


def test_parent_child_source_identity_mismatch_is_rejected() -> None:
    provenance = _provenance()
    different = _provenance(dataset_spec_id=_hash("different-dataset"))
    origin = _origin(provenance=different)
    with pytest.raises(ValueError, match="different source identity"):
        _scope(provenance=provenance, origin=origin)


def test_duplicate_provenance_digest_roles_are_rejected() -> None:
    with pytest.raises(ValueError, match="digest roles must be distinct"):
        _provenance(gold_sha256=_hash("silver"))


def test_exact_source_ledger_identity_set_is_required() -> None:
    scope = _scope()
    validate_scope(scope, source_ledger_origins=scope.origins)
    extra = replace(
        scope.origins[0],
        source_row_index=1,
        source_identifier="synthetic:second-row",
    )
    with pytest.raises(ValueError, match="exact source-ledger identity set"):
        validate_scope(scope, source_ledger_origins=(*scope.origins, extra))


def test_reconciliation_cannot_replace_full_scope_with_equal_shape() -> None:
    scope = _scope()
    forecast = _forecast(scope)
    reconciliation = AccountingReconciliation(
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=forecast.scoring_build_id,
        scope=scope,
        model_id="zero_return",
        sample_policy="a_primary",
        forecast_ids=(forecast.forecast_id,),
        classification_keys=(forecast.forecast_id,),
        counts_and_reasons=_counts(),
        scored_origins=(forecast.origin_ref.origin,),
    )
    changed_origin = replace(
        forecast.origin_ref,
        source_row_index=1,
        source_identifier="synthetic:substituted-row",
    )
    substituted = replace(
        forecast,
        origin_ref=changed_origin,
        forecast_id=None,
    )
    substituted_classification = _classification(substituted)
    with pytest.raises(ValueError, match="parent scope|scope origin order"):
        validate_reconciliation(
            reconciliation,
            forecasts=(substituted,),
            classifications=(substituted_classification,),
        )


def test_reconciliation_recomputes_matching_record_summaries() -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(scope, forecasts, classifications)
    validate_reconciliation(
        reconciliation,
        forecasts=forecasts,
        classifications=classifications,
    )


def test_reconciliation_rejects_balanced_but_wrong_emission_counts() -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    counts = {
        **_mixed_counts(),
        "forecast_count": 1,
        "abstention_count": 2,
        "scored_count": 1,
        "emitted_but_not_scored_count": 0,
        "not_scored_no_forecast_count": 2,
        "exclusive_abstention_reason_counts": (("insufficient_training_history", 2),),
        "primary_score_reason_counts": (("insufficient_training_history", 2),),
        "forecast_coverage": 1 / 3,
    }
    reconciliation = _mixed_reconciliation(
        scope, forecasts, classifications, counts=counts
    )
    with pytest.raises(ValueError, match="forecast_count differs"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=classifications,
        )


def test_reconciliation_rejects_balanced_but_wrong_score_counts() -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    counts = {
        **_mixed_counts(),
        "scored_count": 2,
        "emitted_but_not_scored_count": 0,
        "primary_score_reason_counts": (("insufficient_training_history", 1),),
    }
    reconciliation = _mixed_reconciliation(
        scope, forecasts, classifications, counts=counts
    )
    with pytest.raises(ValueError, match="scored_count differs"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=classifications,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        (
            "exclusive_abstention_reason_counts",
            (("nonfinite_prediction", 1),),
        ),
        ("primary_score_reason_counts", (("next_missing", 2),)),
        ("overlapping_diagnostic_counts", ((UNKNOWN_AVAILABILITY, 2),)),
    ),
)
def test_reconciliation_rejects_wrong_reason_summaries(field, replacement) -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    counts = {**_mixed_counts(), field: replacement}
    reconciliation = _mixed_reconciliation(
        scope, forecasts, classifications, counts=counts
    )
    with pytest.raises(ValueError, match=f"{field} differs"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=classifications,
        )


def test_reconciliation_rejects_wrong_scored_origin_set() -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(
        scope,
        forecasts,
        classifications,
        scored_origins=(scope.origins[1].origin,),
    )
    with pytest.raises(ValueError, match="scored origins differ"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=classifications,
        )


def test_reconciliation_rejects_wrong_scored_timestamp_digest() -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(scope, forecasts, classifications)
    object.__setattr__(
        reconciliation,
        "scored_timestamp_set_sha256",
        _hash("wrong-scored-origin-set"),
    )
    with pytest.raises(ValueError, match="scored timestamp-set digest mismatch"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=classifications,
        )


@pytest.mark.parametrize("case", ("duplicate", "missing", "extra"))
def test_reconciliation_rejects_inexact_classification_cardinality(case) -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(scope, forecasts, classifications)
    supplied = {
        "duplicate": (classifications[0], classifications[0], classifications[2]),
        "missing": classifications[:-1],
        "extra": (*classifications, classifications[-1]),
    }[case]
    with pytest.raises(ValueError):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=supplied,
        )


@pytest.mark.parametrize("case", ("duplicate", "missing", "extra"))
def test_reconciliation_rejects_inexact_forecast_cardinality(case) -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(scope, forecasts, classifications)
    supplied_forecasts, supplied_classifications = {
        "duplicate": (
            (forecasts[0], forecasts[0], forecasts[2]),
            (classifications[0], classifications[0], classifications[2]),
        ),
        "missing": (forecasts[:-1], classifications[:-1]),
        "extra": (
            (*forecasts, forecasts[-1]),
            (*classifications, classifications[-1]),
        ),
    }[case]
    with pytest.raises(ValueError):
        validate_reconciliation(
            reconciliation,
            forecasts=supplied_forecasts,
            classifications=supplied_classifications,
        )


def test_reconciliation_rejects_substituted_classification() -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(scope, forecasts, classifications)
    substituted_forecast = replace(
        forecasts[0],
        producer_trace_ref="synthetic:substituted-producer",
        forecast_id=None,
    )
    substituted = replace(
        classifications[0],
        forecast_id=substituted_forecast.forecast_id,
    )
    with pytest.raises(ValueError, match="parent forecast mismatch"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=(substituted, *classifications[1:]),
        )


def test_reconciliation_rejects_wrong_parent_forecast_id() -> None:
    scope = _mixed_scope()
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(scope, forecasts, classifications)
    wrong_parent = replace(classifications[0], forecast_id=_hash("wrong-parent"))
    with pytest.raises(ValueError, match="parent forecast mismatch"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=(wrong_parent, *classifications[1:]),
        )


def test_reconciliation_rejects_audit_only_origin_contamination() -> None:
    initial_scope = _mixed_scope()
    audit_origin = HistoricalOriginRef(
        provenance=initial_scope.provenance,
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        source_identifier="synthetic:audit-only-origin",
        source_row_index=999,
        origin=ANALYSIS_AS_OF,
        feature_open_t=ANALYSIS_AS_OF - HOUR,
        target_theoretical_close_at=ANALYSIS_AS_OF + HOUR,
        period_id="outside_approved_evaluation_window",
    )
    scope = replace(
        initial_scope,
        audit_only_origins=(audit_origin,),
        scoring_spec_id=None,
    )
    forecasts, classifications = _mixed_records(scope)
    reconciliation = _mixed_reconciliation(scope, forecasts, classifications)
    contaminated = replace(classifications[0], origin_ref=audit_origin)
    with pytest.raises(ValueError, match="parent forecast mismatch"):
        validate_reconciliation(
            reconciliation,
            forecasts=forecasts,
            classifications=(contaminated, *classifications[1:]),
        )


def test_structural_scope_and_exact_ledger_check_do_not_authenticate_source() -> None:
    provenance = _provenance(source_mode="authenticated_pinned_history")
    origin = _origin(provenance=provenance)
    scope = HistoricalScopeSpec(
        provenance=provenance,
        period_id="validation",
        start=VALIDATION_START,
        end_exclusive=TEST_START,
        analysis_as_of=ANALYSIS_AS_OF,
        intended_use="validation_candidate_tuning_diagnostics",
        origins=(origin,),
        model_ids=("zero_return",),
        sample_policies=("a_primary",),
    )
    validate_scope(scope)
    validate_scope(scope, source_ledger_origins=(origin,))
    assert not scope.provenance.historical_source_authenticated


def test_unknown_fields_and_contract_versions_are_rejected() -> None:
    provenance = _provenance()
    values = {
        name: getattr(provenance, name) for name in provenance.__dataclass_fields__
    }
    values["unexpected"] = "value"
    with pytest.raises(ValueError, match="record fields"):
        record_from_mapping(HistoricalProvenanceRef, values)
    with pytest.raises(ValueError, match="unapproved provenance"):
        replace(provenance, protocol_version="future-protocol")
    with pytest.raises(ValueError, match="scoring schema"):
        replace(_forecast(_scope()), schema_version="future-schema", forecast_id=None)


def test_canonical_json_is_deterministic_and_normalizes_timestamps() -> None:
    when = datetime(2024, 1, 1, tzinfo=timezone(timedelta(0), "zero"))
    left = canonical_json({"z": 1, "a": when})
    right = canonical_json({"a": when, "z": 1})
    assert left == right
    assert left == b'{"a":"2024-01-01T00:00:00.000000Z","z":1}\n'
    assert canonical_loads(left) == {
        "a": "2024-01-01T00:00:00.000000Z",
        "z": 1,
    }


def test_canonical_json_preserves_signed_zero_and_null() -> None:
    payload = canonical_json({"missing": None, "zero": -0.0})
    assert b'"missing":null' in payload
    assert b'"zero":-0.0' in payload
    assert canonical_json({"zero": None}) != canonical_json({})


def test_canonical_parser_rejects_duplicate_keys_and_noncanonical_bytes() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        canonical_loads(b'{"a":1,"a":2}\n')
    with pytest.raises(ValueError, match="canonical form"):
        canonical_loads(b'{"b":2, "a":1}\n')


@pytest.mark.parametrize("value", (float("nan"), float("inf"), object(), b"bytes"))
def test_canonical_json_rejects_nonfinite_or_unsupported_objects(value) -> None:
    with pytest.raises(ValueError):
        canonical_json({"value": value})


def _unresolved_occurrence(
    origin: HistoricalOriginRef, position: int
) -> NativeOccurrence:
    reference = OpaqueSourceRef(
        dataset_spec_id=origin.provenance.dataset_spec_id,
        artifact_build_id=origin.provenance.source_artifact_build_id,
        receipt_sha256=origin.provenance.source_receipt_sha256,
        source_identifier=origin.source_identifier,
        source_row_index=origin.source_row_index,
        origin=origin.origin,
    )
    return NativeOccurrence(
        source_ref=reference,
        collection="unresolved_anomalies",
        position=position,
        association="unresolved",
        source_column="unresolved_source_column",
        raw={"affected_fields": ["candle", "unknown", "candle"]},
        linkage="unknown_vocabulary",
        manifest_record_index=None,
        manifest_record_sha256=None,
        manifest_record=None,
    )


def test_native_tokens_order_and_multiplicity_are_preserved() -> None:
    origin = _origin()
    first = _unresolved_occurrence(origin, 0)
    second = _unresolved_occurrence(origin, 1)
    third = _unresolved_occurrence(origin, 2)
    outcome = _outcome(
        origin,
        unresolved_occurrences=(first, second, third),
        anomaly_evidence_status="recorded_references_unverified",
    )
    payload = canonical_json(outcome)
    assert payload.count(b'"candle"') == 6
    assert payload.count(b'"unknown"') == 3
    assert payload.find(b'"position":0') < payload.find(b'"position":1')


def test_native_occurrence_reordering_is_rejected() -> None:
    origin = _origin()
    with pytest.raises(ValueError, match="unique source order"):
        _outcome(
            origin,
            unresolved_occurrences=(
                _unresolved_occurrence(origin, 1),
                _unresolved_occurrence(origin, 0),
            ),
            anomaly_evidence_status="recorded_references_unverified",
        )


def test_native_occurrence_from_other_source_is_rejected() -> None:
    origin = _origin()
    other = _origin(provenance=_provenance(dataset_spec_id=_hash("other")))
    occurrence = _unresolved_occurrence(other, 0)
    with pytest.raises(ValueError, match="source identity mismatch"):
        _outcome(
            origin,
            unresolved_occurrences=(occurrence,),
            anomaly_evidence_status="recorded_references_unverified",
        )


def test_synthetic_descriptors_cannot_upgrade_authentication() -> None:
    provenance = _provenance(source_mode="authenticated_pinned_history")
    assert provenance.source_mode == "authenticated_pinned_history"
    assert not provenance.historical_source_authenticated
    assert public_authority_issuers() == ()


def test_one_build_can_produce_multiple_payloads() -> None:
    scope = _scope()
    build = _build(scope)
    first = _forecast(scope, build_id=build, producer_trace_ref="synthetic:first")
    second = _forecast(scope, build_id=build, producer_trace_ref="synthetic:second")
    assert first.scoring_build_id == second.scoring_build_id
    assert first.forecast_id != second.forecast_id
    assert payload_sha256(first) != payload_sha256(second)


def test_payload_tampering_and_digest_mismatch_are_rejected() -> None:
    forecast = _forecast(_scope())
    supplied = payload_sha256(forecast)
    validate_payload_sha256(forecast, supplied)
    changed = replace(
        forecast,
        producer_trace_ref="synthetic:tampered",
        forecast_id=None,
    )
    with pytest.raises(ValueError, match="payload SHA-256 mismatch"):
        validate_payload_sha256(changed, supplied)


def test_no_path_callable_or_capability_is_serializable(tmp_path) -> None:
    for value in (tmp_path, lambda: None):
        with pytest.raises(ValueError, match="unsupported canonical object"):
            canonical_json({"value": value})
    assert list(tmp_path.iterdir()) == []
    assert public_authority_issuers() == ()
    assert "ClosedHistoricalOutcomeRef" not in contract.__all__
    assert "classify_native_score" not in contract.__all__
    assert "reconcile_native_accounting" not in contract.__all__


def test_contract_versions_are_explicit_and_approved() -> None:
    provenance = _provenance()
    assert SCHEMA_VERSION == "pqta-historical-scoring-accounting-v1"
    assert POLICY_VERSION == "pqta-003d-5f-scoring-accounting-v1"
    assert provenance.protocol_version == PROTOCOL_VERSION
    assert provenance.dataset_contract_version == DATASET_CONTRACT_VERSION
