"""Stage A native scoring/accounting records, validation and serialization.

This module is data-only. It does not fit models, classify outcomes, reconcile
executions, read historical files, issue capabilities, authenticate producers,
or create completed historical execution authority. Digest equality proves
only deterministic data integrity.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

from quant.features.engine import FEATURES
from quant.research import evaluation_protocol as protocol
from quant.research import evaluation_reporting as reporting
from quant.research.forecast_accounting import (
    MODELS,
    PERIODS,
    SAMPLES,
    SCORE_PRIORITY,
    UNKNOWN_AVAILABILITY,
    finite,
    forecast_reason_order,
    identity,
    ordered_reasons,
)
from quant.research.forecast_dataset import (
    ANALYSIS_AS_OF,
    DATASET_CONTRACT_VERSION,
    PROTOCOL_VERSION,
    TARGET_REASON_PRIORITY,
)
from quant.research.historical_representation import (
    POLICY_VERSION as NATIVE_POLICY_VERSION,
)
from quant.research.historical_representation import (
    SCHEMA_VERSION as NATIVE_SCHEMA_VERSION,
)
from quant.research.historical_representation import (
    SERIALIZER_VERSION as NATIVE_SERIALIZER_VERSION,
)
from quant.research.historical_representation import NativeOccurrence
from quant.research.ridge_regression import ALPHAS

SCHEMA_VERSION = "pqta-historical-scoring-accounting-v1"
POLICY_VERSION = "pqta-003d-5f-scoring-accounting-v1"
SERIALIZER_VERSION = "pqta-003d-5f-canonical-v1"
PROJECTION_POLICY_VERSION = "pqta-003d-5b-projection-v1"

__all__ = (
    "POLICY_VERSION",
    "SCHEMA_VERSION",
    "SERIALIZER_VERSION",
    "AccountingReconciliation",
    "CanonicalScoringBundle",
    "HistoricalAccountingResult",
    "HistoricalForecast",
    "HistoricalOriginRef",
    "HistoricalOutcomeView",
    "HistoricalProvenanceRef",
    "HistoricalScopeBlock",
    "HistoricalScopeSpec",
    "HistoricalScore",
    "ScoreClassification",
    "canonical_scoring_payload",
    "canonical_json",
    "canonical_loads",
    "payload_sha256",
    "public_authority_issuers",
    "record_from_mapping",
    "scoring_build_id",
    "scoring_spec_id",
    "source_origin_identity_set_sha256",
    "validate_accounting_result",
    "validate_classification_parent",
    "validate_forecast",
    "validate_origin",
    "validate_payload_sha256",
    "validate_provenance",
    "validate_reconciliation",
    "validate_scope",
    "validate_score",
)

SOURCE_MODES = ("authenticated_pinned_history", "synthetic_fixture")
PERIOD_IDS = (*PERIODS, "outside_approved_evaluation_window")
INTENDED_USES = {
    "training_history": "training_history_accounting",
    "validation": "validation_candidate_tuning_diagnostics",
    "test": "test_frozen_alpha_comparison",
}
FORECAST_STATUSES = ("emitted", "abstained")
SCORE_STATUSES = (
    "scored",
    "emitted_but_not_scored",
    "not_scored_no_forecast",
)
EVIDENCE_STATUSES = ("no_occurrences", "recorded_references_unverified")

_DIGEST = re.compile(r"[0-9a-f]{64}")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _digest(value: object, name: str = "SHA-256") -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"invalid lowercase {name}")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be Boolean")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _utc(value: object, name: str, *, hour_aligned: bool = True) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ValueError(f"{name} must be timezone-aware UTC")
    if hour_aligned:
        protocol.validate_hour(value)
    return value


def _ordered_unique_strings(
    value: object,
    name: str,
    *,
    allowed: tuple[str, ...] | frozenset[str] | None = None,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise ValueError(f"{name} must be a tuple of strings")
    if not allow_empty and not value:
        raise ValueError(f"{name} cannot be empty")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicates")
    if allowed is not None and any(item not in allowed for item in value):
        raise ValueError(f"{name} contains an unknown value")
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("canonical mapping keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, tuple | list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, datetime):
        _utc(value, "canonical timestamp", hour_aligned=False)
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("canonical mapping keys must be strings")
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite canonical number")
        return value
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, Path) or callable(value) or isinstance(value, bytes):
        raise ValueError("unsupported canonical object")
    raise ValueError("unsupported canonical object")


def canonical_json(value: object) -> bytes:
    """Return sorted compact UTF-8 JSON with one LF and finite numbers only."""
    return (
        json.dumps(
            _plain(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_loads(payload: bytes) -> object:
    """Parse exact canonical JSON while rejecting duplicate keys and constants."""
    if type(payload) is not bytes or not payload.endswith(b"\n"):
        raise ValueError("canonical JSON must be bytes ending in one LF")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate canonical JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    try:
        value = json.loads(
            payload,
            object_pairs_hook=unique,
            parse_constant=nonfinite,
        )
        canonical = canonical_json(value)
    except (UnicodeError, json.JSONDecodeError, TypeError, OverflowError) as exc:
        raise ValueError("invalid canonical JSON") from exc
    if canonical != payload:
        raise ValueError("JSON bytes are not in canonical form")
    return value


def payload_sha256(value: object) -> str:
    """Hash exact canonical payload data, excluding its stored payload digest."""
    plain = _plain(value)
    if isinstance(plain, dict) and "payload_sha256" in plain:
        plain = {key: item for key, item in plain.items() if key != "payload_sha256"}
    return hashlib.sha256(canonical_json(plain)).hexdigest()


def validate_payload_sha256(value: object, supplied: str) -> None:
    if _digest(supplied, "payload SHA-256") != payload_sha256(value):
        raise ValueError("payload SHA-256 mismatch")


def _record_sha256(value: object, identity_field: str) -> str:
    plain = _plain(value)
    if not isinstance(plain, dict):
        raise ValueError("record identity requires a dataclass or mapping")
    plain.pop(identity_field, None)
    return hashlib.sha256(canonical_json(plain)).hexdigest()


def scoring_build_id(
    spec_id: str,
    *,
    code_sha256: str,
    dependency_versions: Mapping[str, str],
    serializer_version: str = SERIALIZER_VERSION,
    deterministic_build_configuration: Mapping[str, object],
) -> str:
    """Return reusable build identity; many payloads may share this digest."""
    _digest(spec_id, "scoring specification SHA-256")
    _digest(code_sha256, "code SHA-256")
    if serializer_version != SERIALIZER_VERSION:
        raise ValueError("unknown scoring serializer version")
    if (
        not isinstance(dependency_versions, Mapping)
        or not dependency_versions
        or any(
            type(key) is not str or not key or type(value) is not str or not value
            for key, value in dependency_versions.items()
        )
    ):
        raise ValueError("dependency versions must be a nonempty string mapping")
    if not isinstance(deterministic_build_configuration, Mapping):
        raise ValueError("deterministic build configuration must be a mapping")
    payload = {
        "scoring_spec_id": spec_id,
        "code_content_sha256": code_sha256,
        "dependency_versions": dict(dependency_versions),
        "serializer_version": serializer_version,
        "deterministic_build_configuration": deterministic_build_configuration,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalProvenanceRef:
    """Data-only source identity. No field authenticates caller input."""

    dataset_spec_id: str
    source_artifact_build_id: str
    silver_sha256: str
    gold_sha256: str
    origin_ledger_sha256: str
    dataset_validation_sha256: str
    provenance_json_sha256: str
    provenance_sidecar_sha256: str
    manifest_canonical_sha256: str
    manifest_raw_sha256: str
    manifest_version: str
    feature_version: str
    feature_order: tuple[str, ...]
    source_receipt_sha256: str
    source_mode: str
    protocol_version: str = PROTOCOL_VERSION
    dataset_contract_version: str = DATASET_CONTRACT_VERSION
    projection_policy_version: str = PROJECTION_POLICY_VERSION
    native_schema_version: str = NATIVE_SCHEMA_VERSION
    native_policy_version: str = NATIVE_POLICY_VERSION
    native_serializer_version: str = NATIVE_SERIALIZER_VERSION

    def __post_init__(self) -> None:
        digest_fields = (
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
        for field in digest_fields:
            _digest(getattr(self, field), field)
        if len({getattr(self, field) for field in digest_fields}) != len(digest_fields):
            raise ValueError("provenance digest roles must be distinct")
        if (
            self.protocol_version != PROTOCOL_VERSION
            or self.dataset_contract_version != DATASET_CONTRACT_VERSION
            or self.projection_policy_version != PROJECTION_POLICY_VERSION
            or self.native_schema_version != NATIVE_SCHEMA_VERSION
            or self.native_policy_version != NATIVE_POLICY_VERSION
            or self.native_serializer_version != NATIVE_SERIALIZER_VERSION
        ):
            raise ValueError("unapproved provenance contract version")
        for field in ("manifest_version", "feature_version"):
            _text(getattr(self, field), field)
        if self.feature_order != tuple(FEATURES):
            raise ValueError("feature order differs from the approved contract")
        if self.source_mode not in SOURCE_MODES:
            raise ValueError("unknown source mode")

    @property
    def historical_source_authenticated(self) -> bool:
        """Caller data never establishes authenticated source bytes."""
        return False


def validate_provenance(value: HistoricalProvenanceRef) -> None:
    if type(value) is not HistoricalProvenanceRef:
        raise ValueError("typed historical provenance required")
    value.__post_init__()


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalOriginRef:
    provenance: HistoricalProvenanceRef
    exchange: str
    symbol: str
    timeframe: str
    source_identifier: str
    source_row_index: int
    origin: datetime
    feature_open_t: datetime
    target_theoretical_close_at: datetime
    period_id: str

    def __post_init__(self) -> None:
        validate_provenance(self.provenance)
        if (self.exchange, self.symbol, self.timeframe) != (
            "binance",
            "BTC/USDT",
            "1h",
        ):
            raise ValueError("unapproved market identity")
        _text(self.source_identifier, "source identifier")
        if self.source_identifier.startswith(("/", "~")) or _WINDOWS_DRIVE.match(
            self.source_identifier
        ):
            raise ValueError("source identifier cannot be an absolute local path")
        _integer(self.source_row_index, "source row index")
        for field in ("origin", "feature_open_t", "target_theoretical_close_at"):
            _utc(getattr(self, field), field)
        if (
            self.feature_open_t + protocol.HOUR != self.origin
            or self.target_theoretical_close_at != self.origin + protocol.HOUR
        ):
            raise ValueError("inconsistent origin timeline")
        expected = protocol.evaluation_split(self.origin)
        if self.period_id != expected or self.period_id not in PERIOD_IDS:
            raise ValueError("origin period mismatch")


def validate_origin(value: HistoricalOriginRef) -> None:
    if type(value) is not HistoricalOriginRef:
        raise ValueError("typed historical origin required")
    value.__post_init__()


def _origin_key(value: HistoricalOriginRef) -> tuple:
    return (
        value.origin,
        value.source_identifier,
        value.source_row_index,
        value.provenance.dataset_spec_id,
        value.provenance.source_artifact_build_id,
    )


def source_origin_identity_set_sha256(
    origins: tuple[HistoricalOriginRef, ...],
) -> str:
    if type(origins) is not tuple:
        raise ValueError("origin identity set must be a tuple")
    records = []
    for origin in origins:
        validate_origin(origin)
        records.append(
            {
                "dataset_spec_id": origin.provenance.dataset_spec_id,
                "source_artifact_build_id": origin.provenance.source_artifact_build_id,
                "source_identifier": origin.source_identifier,
                "source_row_index": origin.source_row_index,
                "origin": origin.origin,
                "period_id": origin.period_id,
            }
        )
    if origins != tuple(sorted(origins, key=_origin_key)) or len(
        {_origin_key(origin) for origin in origins}
    ) != len(origins):
        raise ValueError("origin identity set must be canonical and unique")
    return hashlib.sha256(canonical_json(records)).hexdigest()


def _canonical_subset(
    value: tuple[str, ...], order: tuple[str, ...], name: str
) -> None:
    _ordered_unique_strings(value, name, allowed=order, allow_empty=False)
    if value != tuple(item for item in order if item in value):
        raise ValueError(f"{name} must follow canonical order")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalScopeSpec:
    provenance: HistoricalProvenanceRef
    period_id: str
    start: datetime
    end_exclusive: datetime
    analysis_as_of: datetime
    intended_use: str
    origins: tuple[HistoricalOriginRef, ...]
    model_ids: tuple[str, ...]
    sample_policies: tuple[str, ...]
    audit_only_origins: tuple[HistoricalOriginRef, ...] = ()
    frozen_ridge_selection_id: str | None = None
    origin_set_sha256: str | None = None
    source_origin_identity_set_sha256: str | None = None
    scoring_spec_id: str | None = None

    def __post_init__(self) -> None:
        validate_provenance(self.provenance)
        if self.period_id not in PERIODS:
            raise ValueError("unknown evaluation period")
        _utc(self.start, "scope start")
        _utc(self.end_exclusive, "scope end")
        _utc(self.analysis_as_of, "analysis boundary")
        if self.analysis_as_of != ANALYSIS_AS_OF or self.start > self.end_exclusive:
            raise ValueError("unapproved scope boundary")
        if self.intended_use != INTENDED_USES[self.period_id]:
            raise ValueError("scope intended use does not match period")
        if self.provenance.source_mode == "authenticated_pinned_history":
            if (self.start, self.end_exclusive) != PERIODS[self.period_id]:
                raise ValueError("historical scope must use the complete split")
        else:
            lower, upper = PERIODS[self.period_id]
            if not lower <= self.start <= self.end_exclusive <= upper:
                raise ValueError("synthetic scope falls outside approved split")
        self._validate_origins()
        _canonical_subset(self.model_ids, MODELS, "model identities")
        _canonical_subset(self.sample_policies, SAMPLES, "sample identities")
        if self.period_id == "test" and "ridge_7" in self.model_ids:
            _digest(self.frozen_ridge_selection_id, "frozen Ridge selection SHA-256")
        elif self.frozen_ridge_selection_id is not None:
            raise ValueError("frozen Ridge selection applies only to Test Ridge")
        timestamp_digest = reporting.timestamp_digest(
            tuple(origin.origin for origin in self.origins)
        )
        identity_digest = source_origin_identity_set_sha256(self.origins)
        self._set_or_check("origin_set_sha256", timestamp_digest)
        self._set_or_check("source_origin_identity_set_sha256", identity_digest)
        self._set_or_check("scoring_spec_id", scoring_spec_id(self))

    def _validate_origins(self) -> None:
        for name, values in (
            ("origins", self.origins),
            ("audit-only origins", self.audit_only_origins),
        ):
            if type(values) is not tuple:
                raise ValueError(f"{name} must be a tuple")
            if any(type(item) is not HistoricalOriginRef for item in values):
                raise ValueError(f"{name} must contain typed origin references")
            if values != tuple(sorted(values, key=_origin_key)):
                raise ValueError(f"{name} must be in canonical source-ledger order")
            if len({_origin_key(item) for item in values}) != len(values):
                raise ValueError(f"{name} contains duplicate source identities")
            if any(item.provenance != self.provenance for item in values):
                raise ValueError(f"{name} contains a different source identity")
        if any(
            item.period_id != self.period_id
            or not self.start <= item.origin < self.end_exclusive
            for item in self.origins
        ):
            raise ValueError("evaluation origin falls outside the declared scope")
        if any(
            item.period_id != "outside_approved_evaluation_window"
            for item in self.audit_only_origins
        ):
            raise ValueError("audit-only identities must remain outside evaluation")
        if set(self.origins) & set(self.audit_only_origins):
            raise ValueError("evaluation and audit-only origins must be disjoint")

    def _set_or_check(self, name: str, expected: str) -> None:
        supplied = getattr(self, name)
        if supplied is None:
            object.__setattr__(self, name, expected)
        elif _digest(supplied, name) != expected:
            raise ValueError(f"{name} mismatch")


def _logical_specification(scope: HistoricalScopeSpec) -> dict[str, object]:
    """Exact semantic input; deliberately excludes the stored spec digest."""
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "projection_policy_version": PROJECTION_POLICY_VERSION,
        "native_schema_version": NATIVE_SCHEMA_VERSION,
        "native_policy_version": NATIVE_POLICY_VERSION,
        "native_serializer_version": NATIVE_SERIALIZER_VERSION,
        "source_provenance": scope.provenance,
        "period_id": scope.period_id,
        "start": scope.start,
        "end_exclusive": scope.end_exclusive,
        "analysis_as_of": scope.analysis_as_of,
        "intended_use": scope.intended_use,
        "origin_set_sha256": scope.origin_set_sha256,
        "source_origin_identity_set_sha256": (scope.source_origin_identity_set_sha256),
        "audit_only_identity_set_sha256": source_origin_identity_set_sha256(
            scope.audit_only_origins
        ),
        "model_ids": scope.model_ids,
        "sample_policies": scope.sample_policies,
        "frozen_ridge_selection_id": scope.frozen_ridge_selection_id,
        "forecast_statuses": FORECAST_STATUSES,
        "score_statuses": SCORE_STATUSES,
        "forecast_reason_priorities": {
            f"{model_id}:{sample_policy}": forecast_reason_order(
                model_id, sample_policy
            )
            for model_id in MODELS
            for sample_policy in SAMPLES
        },
        "target_reason_priority": TARGET_REASON_PRIORITY,
        "score_reason_priority": SCORE_PRIORITY,
        "source_modes": SOURCE_MODES,
        "anomaly_evidence_statuses": EVIDENCE_STATUSES,
        "conservation_policy": "full_declared_origin_universe_v1",
        "fixed_readiness_flags": {
            "research_only": True,
            "execution_ready": False,
            "point_in_time_verified": False,
            "decision_eligible": False,
        },
    }


def scoring_spec_id(scope: HistoricalScopeSpec) -> str:
    """Hash semantic scope input without reading ``scope.scoring_spec_id``."""
    if type(scope) is not HistoricalScopeSpec:
        raise ValueError("typed historical scope required")
    return hashlib.sha256(canonical_json(_logical_specification(scope))).hexdigest()


def validate_scope(
    value: HistoricalScopeSpec,
    *,
    source_ledger_origins: tuple[HistoricalOriginRef, ...] | None = None,
) -> None:
    if type(value) is not HistoricalScopeSpec:
        raise ValueError("typed historical scope required")
    value.__post_init__()
    if source_ledger_origins is None:
        return
    if type(source_ledger_origins) is not tuple:
        raise ValueError("source ledger identities must be an immutable tuple")
    for origin in source_ledger_origins:
        validate_origin(origin)
        if origin.provenance != value.provenance:
            raise ValueError("source ledger provenance mismatch")
    expected = tuple(
        origin
        for origin in source_ledger_origins
        if origin.period_id == value.period_id
        and value.start <= origin.origin < value.end_exclusive
    )
    audit_only = tuple(
        origin
        for origin in source_ledger_origins
        if origin.period_id == "outside_approved_evaluation_window"
    )
    if value.origins != expected or value.audit_only_origins != audit_only:
        raise ValueError("scope differs from exact source-ledger identity set")


def _optional_digest(value: str | None, name: str) -> None:
    if value is not None:
        _digest(value, name)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalForecast:
    schema_version: str
    scoring_spec_id: str
    scoring_build_id: str
    execution_instance_id: str | None
    origin_ref: HistoricalOriginRef
    model_id: str
    sample_policy: str
    forecast_status: str
    prediction: float | None
    abstention_reasons: tuple[str, ...]
    producer_trace_ref: str
    model_version: str
    history_count: int
    history_cutoff: datetime | None
    scheduled_refit_at: datetime | None
    fit_ref: str | None
    alpha_selection_ref: str | None
    selected_alpha: float | None
    forecast_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unknown scoring schema version")
        _digest(self.scoring_spec_id, "scoring specification SHA-256")
        _digest(self.scoring_build_id, "scoring build SHA-256")
        _optional_digest(self.execution_instance_id, "execution instance SHA-256")
        validate_origin(self.origin_ref)
        protocol.require_evaluation_origin(self.origin_ref.origin)
        identity(self.model_id, self.sample_policy)
        if self.forecast_status not in FORECAST_STATUSES:
            raise ValueError("unknown forecast status")
        reason_order = forecast_reason_order(self.model_id, self.sample_policy)
        if ordered_reasons(self.abstention_reasons, reason_order) != (
            self.abstention_reasons
        ):
            raise ValueError("forecast reasons must follow approved priority")
        if self.forecast_status == "emitted":
            finite(self.prediction)
            if self.abstention_reasons:
                raise ValueError("emitted forecast cannot have abstention reasons")
        elif self.prediction is not None or not self.abstention_reasons:
            raise ValueError("abstention requires null prediction and reasons")
        if self.model_id == "zero_return" and self.prediction != 0.0:
            raise ValueError("Zero Return must emit exactly 0.0")
        _text(self.producer_trace_ref, "producer trace reference")
        _text(self.model_version, "model version")
        _integer(self.history_count, "history count")
        if self.model_id == "zero_return":
            if self.history_count or self.history_cutoff is not None:
                raise ValueError("Zero Return has no training history")
        else:
            if (self.history_count == 0) != (self.history_cutoff is None):
                raise ValueError("history count and cutoff must be present together")
            if self.history_cutoff is not None:
                _utc(self.history_cutoff, "history cutoff")
                if self.history_cutoff > self.origin_ref.origin:
                    raise ValueError("history cutoff exceeds forecast origin")
            if self.forecast_status == "emitted" and self.history_count < 720:
                raise ValueError("emission requires 720 eligible history rows")
        if self.model_id in {"ar_1", "ridge_7"}:
            _utc(self.scheduled_refit_at, "scheduled refit")
            if self.scheduled_refit_at.hour or (
                self.scheduled_refit_at > self.origin_ref.origin
            ):
                raise ValueError("scheduled refit must be prior UTC midnight")
            if self.forecast_status == "emitted":
                _text(self.fit_ref, "fit reference")
        elif self.scheduled_refit_at is not None or self.fit_ref is not None:
            raise ValueError("fit metadata applies only to AR or Ridge")
        if self.model_id == "ridge_7" and self.forecast_status == "emitted":
            if self.origin_ref.period_id != "test":
                raise ValueError("selected-alpha Ridge emission is Test-only")
            _digest(self.alpha_selection_ref, "alpha selection SHA-256")
            if type(self.selected_alpha) not in (int, float) or (
                self.selected_alpha not in ALPHAS
            ):
                raise ValueError("unknown frozen Ridge alpha")
        elif self.alpha_selection_ref is not None or self.selected_alpha is not None:
            raise ValueError("frozen alpha metadata applies only to Ridge emissions")
        expected = _record_sha256(self, "forecast_id")
        if self.forecast_id is None:
            object.__setattr__(self, "forecast_id", expected)
        elif _digest(self.forecast_id, "forecast SHA-256") != expected:
            raise ValueError("forecast ID mismatch")

    @property
    def historical_execution_authenticated(self) -> bool:
        return False


def validate_forecast(
    value: HistoricalForecast, *, scope: HistoricalScopeSpec | None = None
) -> None:
    if type(value) is not HistoricalForecast:
        raise ValueError("typed historical forecast required")
    value.__post_init__()
    if scope is not None:
        validate_scope(scope)
        if (
            value.scoring_spec_id != scope.scoring_spec_id
            or value.origin_ref not in scope.origins
            or value.model_id not in scope.model_ids
            or value.sample_policy not in scope.sample_policies
        ):
            raise ValueError("forecast does not belong to parent scope")
        if (
            value.model_id == "ridge_7"
            and value.forecast_status == "emitted"
            and value.alpha_selection_ref != scope.frozen_ridge_selection_id
        ):
            raise ValueError("forecast differs from frozen Ridge selection")


def _occurrence_matches_origin(
    occurrence: NativeOccurrence, origin: HistoricalOriginRef
) -> bool:
    ref = occurrence.source_ref
    return (
        ref.dataset_spec_id == origin.provenance.dataset_spec_id
        and ref.artifact_build_id == origin.provenance.source_artifact_build_id
        and ref.receipt_sha256 == origin.provenance.source_receipt_sha256
        and ref.source_identifier == origin.source_identifier
        and ref.source_row_index == origin.source_row_index
        and ref.origin == origin.origin
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalOutcomeView:
    origin_ref: HistoricalOriginRef
    target: float | None
    target_valid: bool
    original_invalid_reasons: tuple[str, ...]
    ordered_invalid_reasons: tuple[str, ...]
    target_primary_null_reason: str | None
    target_manifest_anomaly: bool
    target_value_sensitive: bool | None
    target_endpoint_occurrences: tuple[NativeOccurrence, ...]
    feature_window_occurrences: tuple[NativeOccurrence, ...]
    unresolved_occurrences: tuple[NativeOccurrence, ...]
    anomaly_evidence_status: str
    source_authentication: str
    native_schema_version: str
    native_policy_version: str
    theoretical_close_at: datetime
    checked_at: datetime
    closure: str
    native_envelope_sha256: str

    def __post_init__(self) -> None:
        validate_origin(self.origin_ref)
        _boolean(self.target_valid, "target validity")
        _boolean(self.target_manifest_anomaly, "target anomaly flag")
        if self.target_value_sensitive is not None:
            _boolean(self.target_value_sensitive, "target value sensitivity")
        original = _ordered_unique_strings(
            self.original_invalid_reasons,
            "original target reasons",
            allowed=TARGET_REASON_PRIORITY,
        )
        ordered = ordered_reasons(original, TARGET_REASON_PRIORITY)
        if self.ordered_invalid_reasons != ordered:
            raise ValueError("ordered target reasons do not match source reasons")
        if self.target_valid:
            finite(self.target)
            if original or self.target_primary_null_reason is not None:
                raise ValueError("valid target cannot have invalid reasons")
        elif (
            self.target is not None
            or not original
            or self.target_primary_null_reason != ordered[0]
        ):
            raise ValueError("invalid target requires null value and primary reason")
        collections = (
            (self.target_endpoint_occurrences, "target_endpoint_anomalies"),
            (self.feature_window_occurrences, "feature_window_anomalies"),
            (self.unresolved_occurrences, "unresolved_anomalies"),
        )
        for occurrences, collection in collections:
            if type(occurrences) is not tuple or any(
                type(item) is not NativeOccurrence
                or item.collection != collection
                or not _occurrence_matches_origin(item, self.origin_ref)
                for item in occurrences
            ):
                raise ValueError("native occurrence/source identity mismatch")
            positions = tuple(item.position for item in occurrences)
            if positions != tuple(sorted(set(positions))):
                raise ValueError("native occurrences must retain unique source order")
        if self.target_manifest_anomaly != bool(self.target_endpoint_occurrences):
            raise ValueError("target anomaly flag disagrees with endpoint records")
        any_occurrences = any(values for values, _ in collections)
        expected_evidence = (
            "recorded_references_unverified" if any_occurrences else "no_occurrences"
        )
        if (
            self.anomaly_evidence_status != expected_evidence
            or self.anomaly_evidence_status not in EVIDENCE_STATUSES
        ):
            raise ValueError("anomaly evidence status mismatch")
        if self.source_authentication not in SOURCE_MODES:
            raise ValueError("unknown outcome source mode")
        if self.source_authentication != self.origin_ref.provenance.source_mode:
            raise ValueError("outcome source mode differs from provenance")
        if (
            self.native_schema_version != NATIVE_SCHEMA_VERSION
            or self.native_policy_version != NATIVE_POLICY_VERSION
        ):
            raise ValueError("unknown native outcome contract version")
        _utc(self.theoretical_close_at, "target theoretical close")
        _utc(self.checked_at, "outcome checked at")
        if (
            self.theoretical_close_at != self.origin_ref.origin + protocol.HOUR
            or self.checked_at < self.theoretical_close_at
            or self.closure != "closed"
        ):
            raise ValueError("outcome is not theoretically closed")
        _digest(self.native_envelope_sha256, "native envelope SHA-256")

    @property
    def historical_outcome_authenticated(self) -> bool:
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreClassification:
    """Pure data classification; ``forecast_id`` is the exact parent binding."""

    forecast_id: str
    origin_ref: HistoricalOriginRef
    model_id: str
    sample_policy: str
    forecast_status: str
    score_status: str
    prediction: float | None
    target: float | None
    abstention_reasons: tuple[str, ...]
    original_target_reasons: tuple[str, ...]
    score_exclusion_reasons: tuple[str, ...]
    primary_score_reason: str
    all_diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.forecast_id, "parent forecast SHA-256")
        validate_origin(self.origin_ref)
        identity(self.model_id, self.sample_policy)
        if self.forecast_status not in FORECAST_STATUSES:
            raise ValueError("unknown forecast status")
        if self.score_status not in SCORE_STATUSES:
            raise ValueError("unknown score status")
        forecast_order = forecast_reason_order(self.model_id, self.sample_policy)
        if ordered_reasons(self.abstention_reasons, forecast_order) != (
            self.abstention_reasons
        ):
            raise ValueError("classification forecast reasons are not canonical")
        expected_score = (
            "not_scored_no_forecast"
            if self.forecast_status == "abstained"
            else "emitted_but_not_scored"
            if self.score_exclusion_reasons
            else "scored"
        )
        if self.score_status != expected_score:
            raise ValueError("forecast and score statuses are inconsistent")
        if self.forecast_status == "emitted":
            finite(self.prediction)
            if self.abstention_reasons:
                raise ValueError("emitted classification has abstention reasons")
        elif self.prediction is not None or not self.abstention_reasons:
            raise ValueError("abstained classification is malformed")
        _ordered_unique_strings(
            self.original_target_reasons,
            "original target reasons",
            allowed=TARGET_REASON_PRIORITY,
        )
        if ordered_reasons(self.score_exclusion_reasons, SCORE_PRIORITY) != (
            self.score_exclusion_reasons
        ):
            raise ValueError("score exclusions must follow approved priority")
        if self.score_status == "scored":
            finite(self.target)
            if self.original_target_reasons or self.primary_score_reason != "scored":
                raise ValueError("scored classification requires scored primary reason")
        elif self.target is not None or (
            self.primary_score_reason
            != (
                self.score_exclusion_reasons[0]
                if self.score_exclusion_reasons
                else self.abstention_reasons[0]
            )
        ):
            raise ValueError("unscored classification value/reason mismatch")
        required_exclusions = {
            *self.abstention_reasons,
            *self.original_target_reasons,
        }
        if not required_exclusions <= set(self.score_exclusion_reasons):
            raise ValueError("classification omits required exclusion reasons")
        expected_diagnostics = tuple(
            dict.fromkeys((*self.score_exclusion_reasons, UNKNOWN_AVAILABILITY))
        )
        if self.all_diagnostics != expected_diagnostics:
            raise ValueError("classification diagnostics are not canonical")

    @property
    def authenticated_historical_score(self) -> bool:
        return False


def validate_classification_parent(
    classification: ScoreClassification, forecast: HistoricalForecast
) -> None:
    """Bind a data classification to the exact immutable forecast payload."""
    if type(classification) is not ScoreClassification:
        raise ValueError("typed score classification required")
    classification.__post_init__()
    validate_forecast(forecast)
    expected = (
        forecast.forecast_id,
        forecast.origin_ref,
        forecast.model_id,
        forecast.sample_policy,
        forecast.forecast_status,
        forecast.prediction,
        forecast.abstention_reasons,
    )
    observed = (
        classification.forecast_id,
        classification.origin_ref,
        classification.model_id,
        classification.sample_policy,
        classification.forecast_status,
        classification.prediction,
        classification.abstention_reasons,
    )
    if observed != expected:
        raise ValueError("score classification parent forecast mismatch")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalScore:
    """Validated data schema only; construction never authenticates issuance."""

    schema_version: str
    scoring_spec_id: str
    scoring_build_id: str
    execution_instance_id: str
    forecast_id: str
    outcome_view_sha256: str
    origin_ref: HistoricalOriginRef
    model_id: str
    sample_policy: str
    period_id: str
    checked_at: datetime
    forecast_status: str
    score_status: str
    prediction: float | None
    target: float | None
    abstention_reasons: tuple[str, ...]
    original_target_reasons: tuple[str, ...]
    score_exclusion_reasons: tuple[str, ...]
    primary_score_reason: str
    all_diagnostics: tuple[str, ...]
    score_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unknown scoring schema version")
        for value, name in (
            (self.scoring_spec_id, "scoring specification SHA-256"),
            (self.scoring_build_id, "scoring build SHA-256"),
            (self.execution_instance_id, "execution instance SHA-256"),
            (self.forecast_id, "forecast SHA-256"),
            (self.outcome_view_sha256, "outcome view SHA-256"),
        ):
            _digest(value, name)
        classification = ScoreClassification(
            forecast_id=self.forecast_id,
            origin_ref=self.origin_ref,
            model_id=self.model_id,
            sample_policy=self.sample_policy,
            forecast_status=self.forecast_status,
            score_status=self.score_status,
            prediction=self.prediction,
            target=self.target,
            abstention_reasons=self.abstention_reasons,
            original_target_reasons=self.original_target_reasons,
            score_exclusion_reasons=self.score_exclusion_reasons,
            primary_score_reason=self.primary_score_reason,
            all_diagnostics=self.all_diagnostics,
        )
        classification.__post_init__()
        if self.period_id != self.origin_ref.period_id or self.period_id not in PERIODS:
            raise ValueError("score period mismatch")
        _utc(self.checked_at, "score checked at")
        if self.checked_at < self.origin_ref.target_theoretical_close_at:
            raise ValueError("score precedes target closure")
        expected = _record_sha256(self, "score_id")
        if self.score_id is None:
            object.__setattr__(self, "score_id", expected)
        elif _digest(self.score_id, "score SHA-256") != expected:
            raise ValueError("score ID mismatch")

    @property
    def authenticated_historical_issuance(self) -> bool:
        return False


def validate_score(
    value: HistoricalScore,
    *,
    parent: HistoricalForecast,
    scope: HistoricalScopeSpec,
    classification: ScoreClassification | None = None,
    outcome: HistoricalOutcomeView | None = None,
) -> None:
    if type(value) is not HistoricalScore:
        raise ValueError("typed historical score required")
    value.__post_init__()
    validate_forecast(parent, scope=scope)
    if (
        value.scoring_spec_id != scope.scoring_spec_id
        or value.scoring_spec_id != parent.scoring_spec_id
        or value.scoring_build_id != parent.scoring_build_id
        or value.execution_instance_id != parent.execution_instance_id
        or value.execution_instance_id is None
        or value.forecast_id != parent.forecast_id
    ):
        raise ValueError("score parent identity mismatch")
    if classification is not None:
        validate_classification_parent(classification, parent)
        copied = (
            value.origin_ref,
            value.model_id,
            value.sample_policy,
            value.forecast_status,
            value.score_status,
            value.prediction,
            value.target,
            value.abstention_reasons,
            value.original_target_reasons,
            value.score_exclusion_reasons,
            value.primary_score_reason,
            value.all_diagnostics,
        )
        expected = tuple(
            getattr(classification, field.name)
            for field in fields(ScoreClassification)
            if field.name != "forecast_id"
        )
        if copied != expected:
            raise ValueError("score differs from pure classification")
    if outcome is not None:
        outcome.__post_init__()
        if (
            value.origin_ref != outcome.origin_ref
            or value.outcome_view_sha256 != payload_sha256(outcome)
        ):
            raise ValueError("score outcome identity mismatch")


_COUNT_KEYS = (
    "origin_count",
    "forecast_count",
    "abstention_count",
    "scored_count",
    "emitted_but_not_scored_count",
    "not_scored_no_forecast_count",
    "exclusive_abstention_reason_counts",
    "primary_score_reason_counts",
    "overlapping_diagnostic_counts",
    "forecast_coverage",
)


def _count_pairs(value: object, name: str) -> tuple[tuple[str, int], ...]:
    if (
        type(value) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or not item[0]
            or type(item[1]) is not int
            or item[1] < 0
            for item in value
        )
        or len(dict(value)) != len(value)
    ):
        raise ValueError(f"{name} must be canonical nonnegative count pairs")
    return value


def _validate_reason_counts(
    values: tuple[tuple[str, int], ...],
    *,
    name: str,
    order: tuple[str, ...],
) -> None:
    keys = tuple(key for key, _ in values)
    if any(key not in order for key in keys) or keys != tuple(
        key for key in order if key in keys
    ):
        raise ValueError(f"{name} contains an unknown or out-of-order reason")


def _validate_counts_and_reasons(
    value: Mapping[str, object], *, model_id: str, sample_policy: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(_COUNT_KEYS):
        raise ValueError("counts-and-reasons schema mismatch")
    counts = {name: _integer(value[name], name) for name in _COUNT_KEYS[:6]}
    protocol.validate_counts(
        origins=counts["origin_count"],
        emitted=counts["forecast_count"],
        abstained=counts["abstention_count"],
        scored=counts["scored_count"],
        emitted_but_not_scored=counts["emitted_but_not_scored_count"],
        not_scored_no_forecast=counts["not_scored_no_forecast_count"],
    )
    exclusive = _count_pairs(
        value["exclusive_abstention_reason_counts"], "exclusive abstention counts"
    )
    primary = _count_pairs(value["primary_score_reason_counts"], "primary score counts")
    overlapping = _count_pairs(
        value["overlapping_diagnostic_counts"], "overlapping diagnostic counts"
    )
    _validate_reason_counts(
        exclusive,
        name="exclusive abstention counts",
        order=forecast_reason_order(model_id, sample_policy),
    )
    _validate_reason_counts(
        primary,
        name="primary score counts",
        order=SCORE_PRIORITY,
    )
    _validate_reason_counts(
        overlapping,
        name="overlapping diagnostic counts",
        order=(*SCORE_PRIORITY, UNKNOWN_AVAILABILITY),
    )
    if sum(count for _, count in exclusive) != counts["abstention_count"]:
        raise ValueError("exclusive abstention count conservation failure")
    if (
        sum(count for _, count in primary) + counts["scored_count"]
        != counts["origin_count"]
    ):
        raise ValueError("primary score count conservation failure")
    coverage = value["forecast_coverage"]
    expected = (
        counts["forecast_count"] / counts["origin_count"]
        if counts["origin_count"]
        else None
    )
    if (coverage is not None and type(coverage) is not float) or coverage != expected:
        raise ValueError("forecast coverage mismatch")
    _ = overlapping
    return _freeze(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountingReconciliation:
    scoring_spec_id: str
    scoring_build_id: str
    scope: HistoricalScopeSpec
    model_id: str
    sample_policy: str
    forecast_ids: tuple[str, ...]
    classification_keys: tuple[str, ...]
    counts_and_reasons: Mapping[str, object]
    scored_origins: tuple[datetime, ...]
    scored_timestamp_set_sha256: str | None = None
    historical_execution_verified: bool = False
    reconciliation_id: str | None = None

    def __post_init__(self) -> None:
        validate_scope(self.scope)
        if self.scoring_spec_id != self.scope.scoring_spec_id:
            raise ValueError("reconciliation scoring specification mismatch")
        _digest(self.scoring_build_id, "scoring build SHA-256")
        identity(self.model_id, self.sample_policy)
        if (
            self.model_id not in self.scope.model_ids
            or self.sample_policy not in self.scope.sample_policies
        ):
            raise ValueError("reconciliation model/sample outside scope")
        for name, values in (
            ("forecast IDs", self.forecast_ids),
            ("classification keys", self.classification_keys),
        ):
            if type(values) is not tuple:
                raise ValueError(f"{name} must be a tuple")
            for value in values:
                _digest(value, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates")
        frozen_counts = _validate_counts_and_reasons(
            self.counts_and_reasons,
            model_id=self.model_id,
            sample_policy=self.sample_policy,
        )
        object.__setattr__(self, "counts_and_reasons", frozen_counts)
        origin_count = frozen_counts["origin_count"]
        if origin_count != len(self.scope.origins):
            raise ValueError("reconciliation must cover the complete scope")
        if len(self.forecast_ids) != origin_count or len(self.classification_keys) != (
            origin_count
        ):
            raise ValueError("reconciliation identity count mismatch")
        if self.classification_keys != self.forecast_ids:
            raise ValueError("classification keys must bind exact forecast IDs")
        if type(self.scored_origins) is not tuple or self.scored_origins != tuple(
            sorted(set(self.scored_origins))
        ):
            raise ValueError("scored origins must be sorted and unique")
        scope_times = {origin.origin for origin in self.scope.origins}
        if not set(self.scored_origins) <= scope_times:
            raise ValueError("scored origin outside declared scope")
        expected_digest = reporting.timestamp_digest(self.scored_origins)
        if self.scored_timestamp_set_sha256 is None:
            object.__setattr__(self, "scored_timestamp_set_sha256", expected_digest)
        elif (
            _digest(self.scored_timestamp_set_sha256, "scored timestamp-set SHA-256")
            != expected_digest
        ):
            raise ValueError("scored timestamp-set digest mismatch")
        if self.historical_execution_verified is not False:
            raise ValueError("pure reconciliation cannot verify historical execution")
        expected_id = _record_sha256(self, "reconciliation_id")
        if self.reconciliation_id is None:
            object.__setattr__(self, "reconciliation_id", expected_id)
        elif _digest(self.reconciliation_id, "reconciliation SHA-256") != expected_id:
            raise ValueError("reconciliation ID mismatch")

    @property
    def historical_completion_authenticated(self) -> bool:
        return False


def validate_reconciliation(
    value: AccountingReconciliation,
    *,
    forecasts: tuple[HistoricalForecast, ...] | None = None,
    classifications: tuple[ScoreClassification, ...] | None = None,
) -> None:
    if type(value) is not AccountingReconciliation:
        raise ValueError("typed accounting reconciliation required")
    value.__post_init__()
    if forecasts is None and classifications is None:
        return
    if forecasts is None or classifications is None:
        raise ValueError("forecasts and classifications must be supplied together")
    if type(forecasts) is not tuple or type(classifications) is not tuple:
        raise ValueError("immutable forecast/classification collections required")
    if len(forecasts) != len(classifications):
        raise ValueError("forecast/classification count mismatch")
    for forecast, classification in zip(forecasts, classifications, strict=True):
        validate_forecast(forecast, scope=value.scope)
        validate_classification_parent(classification, forecast)
        if forecast.scoring_build_id != value.scoring_build_id:
            raise ValueError("reconciliation contains a different scoring build")
        if (
            forecast.model_id != value.model_id
            or forecast.sample_policy != value.sample_policy
        ):
            raise ValueError("reconciliation contains a different model/sample")
    if tuple(item.origin_ref for item in forecasts) != value.scope.origins:
        raise ValueError("reconciliation differs from exact scope origin order")
    if tuple(item.forecast_id for item in forecasts) != value.forecast_ids:
        raise ValueError("reconciliation forecast identity-set mismatch")
    if tuple(item.forecast_id for item in classifications) != (
        value.classification_keys
    ):
        raise ValueError("reconciliation classification identity-set mismatch")

    forecast_statuses = Counter(item.forecast_status for item in forecasts)
    score_statuses = Counter(item.score_status for item in classifications)
    abstention_reasons = Counter(
        item.abstention_reasons[0]
        for item in classifications
        if item.forecast_status == "abstained"
    )
    primary_score_reasons = Counter(
        item.primary_score_reason
        for item in classifications
        if item.score_status != "scored"
    )
    overlapping_diagnostics = Counter(
        reason for item in classifications for reason in item.all_diagnostics
    )
    forecast_order = forecast_reason_order(value.model_id, value.sample_policy)
    diagnostic_order = (*SCORE_PRIORITY, UNKNOWN_AVAILABILITY)
    scored_origins = tuple(
        sorted(
            item.origin_ref.origin
            for item in classifications
            if item.score_status == "scored"
        )
    )
    expected = {
        "origin_count": len(forecasts),
        "forecast_count": forecast_statuses["emitted"],
        "abstention_count": forecast_statuses["abstained"],
        "scored_count": score_statuses["scored"],
        "emitted_but_not_scored_count": score_statuses["emitted_but_not_scored"],
        "not_scored_no_forecast_count": score_statuses["not_scored_no_forecast"],
        "exclusive_abstention_reason_counts": tuple(
            (reason, abstention_reasons[reason])
            for reason in forecast_order
            if abstention_reasons[reason]
        ),
        "primary_score_reason_counts": tuple(
            (reason, primary_score_reasons[reason])
            for reason in SCORE_PRIORITY
            if primary_score_reasons[reason]
        ),
        "overlapping_diagnostic_counts": tuple(
            (reason, overlapping_diagnostics[reason])
            for reason in diagnostic_order
            if overlapping_diagnostics[reason]
        ),
        "forecast_coverage": (
            forecast_statuses["emitted"] / len(forecasts) if forecasts else None
        ),
    }
    for name, expected_value in expected.items():
        if value.counts_and_reasons[name] != expected_value:
            raise ValueError(f"reconciliation {name} differs from supplied records")
    if value.scored_origins != scored_origins:
        raise ValueError("reconciliation scored origins differ from supplied records")
    if value.scored_timestamp_set_sha256 != reporting.timestamp_digest(scored_origins):
        raise ValueError(
            "reconciliation scored timestamp-set digest differs from supplied records"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalAccountingResult:
    """Data schema only; no Stage A constructor authenticates completion."""

    schema_version: str
    scoring_spec_id: str
    scoring_build_id: str
    execution_instance_id: str
    execution_completion_ref: str
    scope: HistoricalScopeSpec
    model_id: str
    sample_policy: str
    forecast_ids: tuple[str, ...]
    score_ids: tuple[str, ...]
    origin_count: int
    forecast_count: int
    abstention_count: int
    scored_count: int
    emitted_but_not_scored_count: int
    not_scored_no_forecast_count: int
    exclusive_abstention_reason_counts: tuple[tuple[str, int], ...]
    primary_score_reason_counts: tuple[tuple[str, int], ...]
    overlapping_diagnostic_counts: tuple[tuple[str, int], ...]
    forecast_coverage: float | None
    scored_origins: tuple[datetime, ...]
    scored_timestamp_set_sha256: str
    audit_only_origins: tuple[HistoricalOriginRef, ...]
    reconciliation_id: str
    accounting_complete: bool
    research_only: bool
    execution_ready: bool
    point_in_time_verified: bool
    decision_eligible: bool
    accounting_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unknown scoring schema version")
        validate_scope(self.scope)
        for value, name in (
            (self.scoring_spec_id, "scoring specification SHA-256"),
            (self.scoring_build_id, "scoring build SHA-256"),
            (self.execution_instance_id, "execution instance SHA-256"),
            (self.reconciliation_id, "reconciliation SHA-256"),
        ):
            _digest(value, name)
        if self.scoring_spec_id != self.scope.scoring_spec_id:
            raise ValueError("accounting scoring specification mismatch")
        _text(self.execution_completion_ref, "execution completion reference")
        identity(self.model_id, self.sample_policy)
        if (
            self.model_id not in self.scope.model_ids
            or self.sample_policy not in self.scope.sample_policies
        ):
            raise ValueError("accounting model/sample outside scope")
        for name, values in (
            ("forecast IDs", self.forecast_ids),
            ("score IDs", self.score_ids),
        ):
            if type(values) is not tuple:
                raise ValueError(f"{name} must be a tuple")
            for value in values:
                _digest(value, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates")
        counts = {
            "origin_count": self.origin_count,
            "forecast_count": self.forecast_count,
            "abstention_count": self.abstention_count,
            "scored_count": self.scored_count,
            "emitted_but_not_scored_count": self.emitted_but_not_scored_count,
            "not_scored_no_forecast_count": self.not_scored_no_forecast_count,
            "exclusive_abstention_reason_counts": (
                self.exclusive_abstention_reason_counts
            ),
            "primary_score_reason_counts": self.primary_score_reason_counts,
            "overlapping_diagnostic_counts": self.overlapping_diagnostic_counts,
            "forecast_coverage": self.forecast_coverage,
        }
        _validate_counts_and_reasons(
            counts,
            model_id=self.model_id,
            sample_policy=self.sample_policy,
        )
        if self.origin_count != len(self.scope.origins):
            raise ValueError("accounting must cover the complete scope")
        if len(self.forecast_ids) != self.origin_count or len(self.score_ids) != (
            self.origin_count
        ):
            raise ValueError("accounting identity count mismatch")
        if self.scored_origins != tuple(sorted(set(self.scored_origins))):
            raise ValueError("accounting scored origins must be sorted and unique")
        if len(self.scored_origins) != self.scored_count or not set(
            self.scored_origins
        ) <= {origin.origin for origin in self.scope.origins}:
            raise ValueError("accounting scored-origin count or scope mismatch")
        if reporting.timestamp_digest(self.scored_origins) != (
            self.scored_timestamp_set_sha256
        ):
            raise ValueError("accounting scored timestamp-set digest mismatch")
        if self.audit_only_origins != self.scope.audit_only_origins:
            raise ValueError("accounting audit-only identities changed")
        if (
            self.accounting_complete is not True
            or self.research_only is not True
            or self.execution_ready is not False
            or self.point_in_time_verified is not False
            or self.decision_eligible is not False
        ):
            raise ValueError("historical accounting readiness flags are fixed")
        expected = _record_sha256(self, "accounting_id")
        if self.accounting_id is None:
            object.__setattr__(self, "accounting_id", expected)
        elif _digest(self.accounting_id, "accounting SHA-256") != expected:
            raise ValueError("accounting ID mismatch")

    @property
    def authenticated_historical_completion(self) -> bool:
        return False


def validate_accounting_result(
    value: HistoricalAccountingResult,
    *,
    reconciliation: AccountingReconciliation,
    forecasts: tuple[HistoricalForecast, ...] = (),
    scores: tuple[HistoricalScore, ...] = (),
) -> None:
    if type(value) is not HistoricalAccountingResult:
        raise ValueError("typed historical accounting result required")
    value.__post_init__()
    validate_reconciliation(reconciliation)
    if (
        value.reconciliation_id != reconciliation.reconciliation_id
        or value.scoring_spec_id != reconciliation.scoring_spec_id
        or value.scoring_build_id != reconciliation.scoring_build_id
        or value.scope != reconciliation.scope
        or value.model_id != reconciliation.model_id
        or value.sample_policy != reconciliation.sample_policy
        or value.forecast_ids != reconciliation.forecast_ids
    ):
        raise ValueError("accounting result differs from parent reconciliation")
    if forecasts or scores:
        if len(forecasts) != value.origin_count or len(scores) != value.origin_count:
            raise ValueError("accounting child count mismatch")
        for forecast, score in zip(forecasts, scores, strict=True):
            validate_score(score, parent=forecast, scope=value.scope)
            if (
                forecast.execution_instance_id != value.execution_instance_id
                or score.execution_instance_id != value.execution_instance_id
            ):
                raise ValueError("accounting child execution identity mismatch")
        if tuple(forecast.forecast_id for forecast in forecasts) != value.forecast_ids:
            raise ValueError("accounting forecast identity-set mismatch")
        if tuple(score.score_id for score in scores) != value.score_ids:
            raise ValueError("accounting score identity-set mismatch")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalScopeBlock:
    scope: HistoricalScopeSpec
    classification: str
    execution_state: str
    diagnostic_codes: tuple[str, ...]
    affected_origin_refs: tuple[HistoricalOriginRef, ...]
    executed_forecast_ids: tuple[str, ...]
    finalized_score_ids: tuple[str, ...]
    missing_origin_refs: tuple[HistoricalOriginRef, ...]
    research_only: bool = True
    execution_ready: bool = False
    point_in_time_verified: bool = False
    decision_eligible: bool = False
    scope_block_id: str | None = None

    def __post_init__(self) -> None:
        validate_scope(self.scope)
        allowed = {
            ("blocked", "not_run"),
            ("failed", "not_run"),
            ("failed", "interrupted"),
        }
        if (self.classification, self.execution_state) not in allowed:
            raise ValueError("invalid scope block lifecycle")
        _ordered_unique_strings(
            self.diagnostic_codes, "diagnostic codes", allow_empty=False
        )
        if self.diagnostic_codes != tuple(sorted(self.diagnostic_codes)):
            raise ValueError("diagnostic codes must use deterministic order")
        for name, values in (
            ("affected origins", self.affected_origin_refs),
            ("missing origins", self.missing_origin_refs),
        ):
            if type(values) is not tuple or values != tuple(
                sorted(values, key=_origin_key)
            ):
                raise ValueError(f"{name} must be canonical")
            if len({_origin_key(value) for value in values}) != len(values):
                raise ValueError(f"{name} contains duplicates")
            if any(value not in self.scope.origins for value in values):
                raise ValueError(f"{name} includes an origin outside scope")
        for name, values in (
            ("executed forecast IDs", self.executed_forecast_ids),
            ("finalized score IDs", self.finalized_score_ids),
        ):
            if type(values) is not tuple:
                raise ValueError(f"{name} must be a tuple")
            for value in values:
                _digest(value, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates")
        if self.execution_state == "not_run" and (
            self.executed_forecast_ids or self.finalized_score_ids
        ):
            raise ValueError("not-run scope cannot contain execution records")
        if len(self.finalized_score_ids) > len(self.executed_forecast_ids):
            raise ValueError("score progress cannot exceed forecast progress")
        for field in (
            "research_only",
            "execution_ready",
            "point_in_time_verified",
            "decision_eligible",
        ):
            _boolean(getattr(self, field), field)
        if (
            self.research_only is not True
            or self.execution_ready is not False
            or self.point_in_time_verified is not False
            or self.decision_eligible is not False
        ):
            raise ValueError("scope block readiness flags are fixed")
        expected = _record_sha256(self, "scope_block_id")
        if self.scope_block_id is None:
            object.__setattr__(self, "scope_block_id", expected)
        elif _digest(self.scope_block_id, "scope block SHA-256") != expected:
            raise ValueError("scope block ID mismatch")


_BUNDLE_RECORD_TYPES = {
    "accounting_reconciliation",
    "historical_accounting_result",
    "historical_scope_block",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalScoringBundle:
    """Exact data-only §12 bundle; serialization grants no live authority."""

    schema_version: str
    policy_version: str
    serializer_version: str
    scoring_spec_id: str
    scoring_build_id: str
    execution_instance_id: str | None
    record_type: str
    source_provenance: HistoricalProvenanceRef
    scope: HistoricalScopeSpec
    forecasts: tuple[HistoricalForecast, ...]
    outcomes: tuple[HistoricalOutcomeView, ...]
    score_classifications: tuple[ScoreClassification, ...]
    scores: tuple[HistoricalScore, ...]
    reconciliation: AccountingReconciliation | None
    accounting: HistoricalAccountingResult | None
    scope_block: HistoricalScopeBlock | None
    research_only: bool
    execution_ready: bool
    point_in_time_verified: bool
    decision_eligible: bool
    payload_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            self.schema_version != SCHEMA_VERSION
            or self.policy_version != POLICY_VERSION
            or self.serializer_version != SERIALIZER_VERSION
        ):
            raise ValueError("unknown canonical bundle contract version")
        validate_scope(self.scope)
        validate_provenance(self.source_provenance)
        if self.source_provenance != self.scope.provenance:
            raise ValueError("bundle source provenance differs from scope")
        if self.scoring_spec_id != self.scope.scoring_spec_id:
            raise ValueError("bundle scoring specification differs from scope")
        _digest(self.scoring_build_id, "scoring build SHA-256")
        _optional_digest(self.execution_instance_id, "execution instance SHA-256")
        if self.record_type not in _BUNDLE_RECORD_TYPES:
            raise ValueError("unknown canonical bundle record type")
        terminals = (
            self.reconciliation,
            self.accounting,
            self.scope_block,
        )
        if sum(item is not None for item in terminals) != 1:
            raise ValueError("canonical bundle requires exactly one terminal record")
        for name, values, expected_type in (
            ("forecasts", self.forecasts, HistoricalForecast),
            ("outcomes", self.outcomes, HistoricalOutcomeView),
            ("score classifications", self.score_classifications, ScoreClassification),
            ("scores", self.scores, HistoricalScore),
        ):
            if type(values) is not tuple or any(
                type(item) is not expected_type for item in values
            ):
                raise ValueError(f"{name} must be an immutable typed collection")
        self._validate_children()
        expected_record_type = (
            "accounting_reconciliation"
            if self.reconciliation is not None
            else "historical_accounting_result"
            if self.accounting is not None
            else "historical_scope_block"
        )
        if self.record_type != expected_record_type:
            raise ValueError("bundle record type differs from terminal record")
        for field in (
            "research_only",
            "execution_ready",
            "point_in_time_verified",
            "decision_eligible",
        ):
            _boolean(getattr(self, field), field)
        if (
            self.research_only is not True
            or self.execution_ready is not False
            or self.point_in_time_verified is not False
            or self.decision_eligible is not False
        ):
            raise ValueError("canonical bundle readiness flags are fixed")
        expected_payload = _record_sha256(self, "payload_sha256")
        if self.payload_sha256 is None:
            object.__setattr__(self, "payload_sha256", expected_payload)
        elif _digest(self.payload_sha256, "payload SHA-256") != expected_payload:
            raise ValueError("canonical bundle payload SHA-256 mismatch")

    def _validate_children(self) -> None:
        forecast_by_id = {}
        for forecast in self.forecasts:
            validate_forecast(forecast, scope=self.scope)
            if (
                forecast.scoring_build_id != self.scoring_build_id
                or forecast.execution_instance_id != self.execution_instance_id
                or forecast.forecast_id in forecast_by_id
            ):
                raise ValueError("bundle forecast identity mismatch")
            forecast_by_id[forecast.forecast_id] = forecast
        outcome_by_origin = {}
        for outcome in self.outcomes:
            outcome.__post_init__()
            if (
                outcome.origin_ref not in self.scope.origins
                or outcome.origin_ref in outcome_by_origin
            ):
                raise ValueError("bundle outcome identity mismatch")
            outcome_by_origin[outcome.origin_ref] = outcome
        seen_classifications = set()
        for classification in self.score_classifications:
            parent = forecast_by_id.get(classification.forecast_id)
            if parent is None or classification.forecast_id in seen_classifications:
                raise ValueError("bundle classification parent mismatch")
            validate_classification_parent(classification, parent)
            seen_classifications.add(classification.forecast_id)
        seen_scores = set()
        for score in self.scores:
            parent = forecast_by_id.get(score.forecast_id)
            if parent is None or score.score_id in seen_scores:
                raise ValueError("bundle score parent mismatch")
            validate_score(
                score,
                parent=parent,
                scope=self.scope,
                outcome=outcome_by_origin.get(score.origin_ref),
            )
            seen_scores.add(score.score_id)
        if self.reconciliation is not None:
            if self.execution_instance_id is not None or self.scores:
                raise ValueError("pure reconciliation bundle cannot claim issuance")
            validate_reconciliation(
                self.reconciliation,
                forecasts=self.forecasts,
                classifications=self.score_classifications,
            )
            if (
                self.reconciliation.scoring_build_id != self.scoring_build_id
                or self.reconciliation.scope != self.scope
            ):
                raise ValueError("bundle reconciliation identity mismatch")
        elif self.accounting is not None:
            self.accounting.__post_init__()
            if (
                self.execution_instance_id is None
                or self.accounting.execution_instance_id != self.execution_instance_id
                or self.accounting.scoring_build_id != self.scoring_build_id
                or self.accounting.scope != self.scope
                or self.accounting.forecast_ids
                != tuple(forecast.forecast_id for forecast in self.forecasts)
                or self.accounting.score_ids
                != tuple(score.score_id for score in self.scores)
            ):
                raise ValueError("bundle accounting identity mismatch")
        else:
            self.scope_block.__post_init__()
            if self.scope_block.scope != self.scope:
                raise ValueError("bundle scope block identity mismatch")
            if self.scope_block.execution_state == "not_run" and any(
                (
                    self.forecasts,
                    self.outcomes,
                    self.score_classifications,
                    self.scores,
                )
            ):
                raise ValueError("not-run bundle cannot contain execution records")

    @property
    def authenticated_historical_bundle(self) -> bool:
        return False


def canonical_scoring_payload(value: CanonicalScoringBundle) -> bytes:
    """Serialize an exact validated bundle; bytes do not recreate authority."""
    if type(value) is not CanonicalScoringBundle:
        raise ValueError("typed canonical scoring bundle required")
    value.__post_init__()
    return canonical_json(value)


def record_from_mapping(record_type: type, value: Mapping[str, object]):
    """Strict keyword construction; unknown or missing schema fields fail."""
    if not isinstance(value, Mapping) or not is_dataclass(record_type):
        raise ValueError("dataclass record type and mapping required")
    expected = {field.name for field in fields(record_type)}
    if set(value) != expected:
        raise ValueError("record fields differ from the approved schema")
    return record_type(**dict(value))


def public_authority_issuers() -> tuple[str, ...]:
    """Stage A intentionally exports no historical authority issuer."""
    return ()
