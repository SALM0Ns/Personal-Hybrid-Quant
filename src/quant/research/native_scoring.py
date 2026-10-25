"""Pure Stage B classification of explicitly supplied synthetic data.

The scope, build identity, forecast and outcome are caller-supplied data. No
digest or source label authenticates execution, publication or historical
bytes. The kernel never resolves a source or creates a historical score.
"""

from dataclasses import replace

from quant.research import evaluation_protocol as protocol
from quant.research.forecast_accounting import (
    SCORE_PRIORITY,
    UNKNOWN_AVAILABILITY,
    ordered_reasons,
)
from quant.research.historical_scoring_contract import (
    POLICY_VERSION,
    HistoricalForecast,
    HistoricalOutcomeView,
    HistoricalScopeSpec,
    ScoreClassification,
    validate_classification_parent,
    validate_forecast,
    validate_scope,
)

__all__ = ("classify_native_score",)


def classify_native_score(
    forecast: HistoricalForecast,
    outcome: HistoricalOutcomeView,
    *,
    scope: HistoricalScopeSpec,
    scoring_build_id: str,
    sample_policy: str,
    policy_version: str = POLICY_VERSION,
) -> ScoreClassification:
    """Classify one closed synthetic pair using the approved 5G score rules.

    A closed invalid-null target must retain its existing source reason. An
    absent view, pre-closure input or unresolved required association/linkage
    raises ValueError; it cannot create a fabricated abstention or score.
    Raw anomaly records remain unchanged in the supplied immutable outcome.
    """
    if type(policy_version) is not str or policy_version != POLICY_VERSION:
        raise ValueError("unapproved native scoring policy")
    if (
        type(forecast) is not HistoricalForecast
        or type(forecast.forecast_id) is not str
    ):
        raise ValueError("validated forecast with an immutable parent ID required")
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
    validate_forecast(forecast, scope=scope)
    if (
        type(scoring_build_id) is not str
        or scoring_build_id != forecast.scoring_build_id
    ):
        raise ValueError("synthetic scoring build identity mismatch")
    if type(sample_policy) is not str or sample_policy != forecast.sample_policy:
        raise ValueError("synthetic scoring sample policy mismatch")
    if (
        scope.provenance.source_mode != "synthetic_fixture"
        or forecast.execution_instance_id is not None
    ):
        raise ValueError("explicit synthetic scope and forecast required")
    if type(outcome) is not HistoricalOutcomeView:
        raise ValueError("explicit synthetic outcome view required")

    # Only safe identity and clock fields are read until closure is established.
    if outcome.origin_ref != forecast.origin_ref:
        raise ValueError("synthetic forecast/outcome origin identity mismatch")
    protocol.validate_hour(outcome.theoretical_close_at)
    protocol.validate_hour(outcome.checked_at)
    if (
        outcome.theoretical_close_at != forecast.origin_ref.origin + protocol.HOUR
        or outcome.checked_at < outcome.theoretical_close_at
        or outcome.closure != "closed"
    ):
        raise ValueError("synthetic outcome is not theoretically closed")
    if outcome.source_authentication != "synthetic_fixture":
        raise ValueError("explicit synthetic outcome required")
    outcome.__post_init__()
    if outcome.unresolved_occurrences:
        raise ValueError("unresolved native anomaly association blocks classification")
    for occurrences in (
        outcome.target_endpoint_occurrences,
        outcome.feature_window_occurrences,
    ):
        for occurrence in occurrences:
            replace(occurrence)  # Validate without re-freezing the caller's record.
            if occurrence.linkage != "matched":
                raise ValueError(
                    "required native anomaly linkage blocks classification: "
                    + occurrence.linkage
                )

    reasons = set(forecast.abstention_reasons) | set(outcome.original_invalid_reasons)
    if sample_policy == "a_sensitivity" and outcome.target_manifest_anomaly:
        reasons.add("target_manifest_anomaly")
    exclusions = ordered_reasons(tuple(reasons), SCORE_PRIORITY)
    status = (
        "not_scored_no_forecast"
        if forecast.forecast_status == "abstained"
        else "emitted_but_not_scored"
        if exclusions
        else "scored"
    )
    protocol.validate_score_state(
        protocol.ForecastState(forecast.origin_ref.origin, forecast.forecast_status),
        status,
        checked_at=outcome.checked_at,
    )
    classification = ScoreClassification(
        forecast_id=forecast.forecast_id,
        origin_ref=forecast.origin_ref,
        model_id=forecast.model_id,
        sample_policy=forecast.sample_policy,
        forecast_status=forecast.forecast_status,
        score_status=status,
        prediction=forecast.prediction,
        target=outcome.target if status == "scored" else None,
        abstention_reasons=forecast.abstention_reasons,
        original_target_reasons=outcome.original_invalid_reasons,
        score_exclusion_reasons=exclusions,
        primary_score_reason=exclusions[0] if exclusions else "scored",
        all_diagnostics=(*exclusions, UNKNOWN_AVAILABILITY),
    )
    validate_classification_parent(classification, forecast)
    return classification
