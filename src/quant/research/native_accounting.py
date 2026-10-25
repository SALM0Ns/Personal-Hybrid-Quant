"""Pure Stage C reconciliation of complete supplied synthetic record sets.

No forecast, score classification or missing record is created here. The result
validates data identities and arithmetic; it never authenticates historical
source bytes, model execution or historical accounting completion.
"""

from collections import Counter

from quant.research.evaluation_reporting import timestamp_digest
from quant.research.forecast_accounting import (
    SCORE_PRIORITY,
    UNKNOWN_AVAILABILITY,
    forecast_reason_order,
    identity,
)
from quant.research.historical_scoring_contract import (
    POLICY_VERSION,
    AccountingReconciliation,
    HistoricalForecast,
    HistoricalScopeSpec,
    ScoreClassification,
    validate_classification_parent,
    validate_forecast,
    validate_reconciliation,
    validate_scope,
)

__all__ = ("reconcile_native_accounting",)


def reconcile_native_accounting(
    scope: HistoricalScopeSpec,
    *,
    model_id: str,
    sample_policy: str,
    scoring_build_id: str,
    forecasts: tuple[HistoricalForecast, ...],
    score_classifications: tuple[ScoreClassification, ...],
    policy_version: str = POLICY_VERSION,
) -> AccountingReconciliation:
    """Reconcile exact synthetic sets, canonicalized to declared scope order.

    Reject duplicates, missing/extra keys, audit-only contamination and parent
    substitutions before deriving summaries. Invalid input is never repaired.
    An empty synthetic scope permits zero arithmetic, not completed history.
    """
    if type(policy_version) is not str or policy_version != POLICY_VERSION:
        raise ValueError("unapproved native accounting policy")
    if type(scope) is not HistoricalScopeSpec or any(
        type(getattr(scope, name)) is not str
        for name in (
            "scoring_spec_id",
            "origin_set_sha256",
            "source_origin_identity_set_sha256",
        )
    ):
        raise ValueError("validated synthetic scope identities required")
    validate_scope(scope)
    if scope.provenance.source_mode != "synthetic_fixture":
        raise ValueError("explicit synthetic accounting scope required")
    if type(model_id) is not str or type(sample_policy) is not str:
        raise ValueError("explicit model/sample identities required")
    identity(model_id, sample_policy)
    if model_id not in scope.model_ids or sample_policy not in scope.sample_policies:
        raise ValueError("accounting model/sample outside declared scope")
    if type(forecasts) is not tuple or type(score_classifications) is not tuple:
        raise ValueError("immutable forecast/classification tuples required")

    by_origin = {}
    by_forecast_id = {}
    for forecast in forecasts:
        if (
            type(forecast) is not HistoricalForecast
            or type(forecast.forecast_id) is not str
        ):
            raise ValueError("validated forecast with an immutable parent ID required")
        validate_forecast(forecast, scope=scope)
        if (
            forecast.model_id != model_id
            or forecast.sample_policy != sample_policy
            or forecast.scoring_build_id != scoring_build_id
            or forecast.execution_instance_id is not None
        ):
            raise ValueError("synthetic accounting forecast context mismatch")
        if forecast.origin_ref in by_origin or forecast.forecast_id in by_forecast_id:
            raise ValueError("duplicate accounting forecast origin or identity")
        by_origin[forecast.origin_ref] = forecast
        by_forecast_id[forecast.forecast_id] = forecast
    if set(by_origin) != set(scope.origins):
        raise ValueError("forecasts differ from exact declared evaluation universe")

    by_parent = {}
    for classification in score_classifications:
        if type(classification) is not ScoreClassification:
            raise ValueError("typed score classification required")
        classification.__post_init__()
        if classification.forecast_id in by_parent:
            raise ValueError("duplicate accounting classification parent")
        parent = by_forecast_id.get(classification.forecast_id)
        if parent is None:
            raise ValueError("classification parent outside declared forecast set")
        validate_classification_parent(classification, parent)
        by_parent[classification.forecast_id] = classification
    if set(by_parent) != set(by_forecast_id):
        raise ValueError("classifications differ from exact declared forecast set")

    ordered_forecasts = tuple(by_origin[origin] for origin in scope.origins)
    ordered_classifications = tuple(
        by_parent[forecast.forecast_id] for forecast in ordered_forecasts
    )
    forecast_statuses = Counter(item.forecast_status for item in ordered_forecasts)
    score_statuses = Counter(item.score_status for item in ordered_classifications)
    abstentions = Counter(
        item.abstention_reasons[0]
        for item in ordered_classifications
        if item.forecast_status == "abstained"
    )
    primary = Counter(
        item.primary_score_reason
        for item in ordered_classifications
        if item.score_status != "scored"
    )
    diagnostics = Counter(
        reason for item in ordered_classifications for reason in item.all_diagnostics
    )
    scored_origins = tuple(
        item.origin_ref.origin
        for item in ordered_classifications
        if item.score_status == "scored"
    )
    origin_count = len(scope.origins)
    counts = {
        "origin_count": origin_count,
        "forecast_count": forecast_statuses["emitted"],
        "abstention_count": forecast_statuses["abstained"],
        "scored_count": score_statuses["scored"],
        "emitted_but_not_scored_count": score_statuses["emitted_but_not_scored"],
        "not_scored_no_forecast_count": score_statuses["not_scored_no_forecast"],
        "exclusive_abstention_reason_counts": tuple(
            (reason, abstentions[reason])
            for reason in forecast_reason_order(model_id, sample_policy)
            if abstentions[reason]
        ),
        "primary_score_reason_counts": tuple(
            (reason, primary[reason]) for reason in SCORE_PRIORITY if primary[reason]
        ),
        "overlapping_diagnostic_counts": tuple(
            (reason, diagnostics[reason])
            for reason in (*SCORE_PRIORITY, UNKNOWN_AVAILABILITY)
            if diagnostics[reason]
        ),
        "forecast_coverage": (
            forecast_statuses["emitted"] / origin_count if origin_count else None
        ),
    }
    result = AccountingReconciliation(
        scoring_spec_id=scope.scoring_spec_id,
        scoring_build_id=scoring_build_id,
        scope=scope,
        model_id=model_id,
        sample_policy=sample_policy,
        forecast_ids=tuple(item.forecast_id for item in ordered_forecasts),
        classification_keys=tuple(item.forecast_id for item in ordered_classifications),
        counts_and_reasons=counts,
        scored_origins=scored_origins,
        scored_timestamp_set_sha256=timestamp_digest(scored_origins),
    )
    validate_reconciliation(
        result,
        forecasts=ordered_forecasts,
        classifications=ordered_classifications,
    )
    return result
