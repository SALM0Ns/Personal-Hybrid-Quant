"""Read-only 5B compatibility plans, not a historical execution bridge.

Only verify_pinned_source authenticates the snapshot read by the approved 5A
verifier. Synthetic bindings attest fixtures, never historical bytes. Factory
membership and per-row canonical digests bind receipts to immutable records;
this is an in-process integrity boundary, not a hostile-Python security sandbox.
No models, forecasts, scores, evaluation reports or output files are produced.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from weakref import WeakKeyDictionary

from quant.features.engine import FEATURES
from quant.features.manifest import ANOMALY_TYPES
from quant.research import evaluation_protocol as p
from quant.research import forecast_accounting as accounting
from quant.research import forecast_dataset as fd
from quant.research import historical_adapter as ha

SERIALIZER_VERSION = "pqta-003d-5c-canonical-v1"
CLASSIFICATIONS = ("compatible", "blocked", "failed", "audit_only", "not_closed")
OHLCV = frozenset({"open", "high", "low", "close", "volume"})


def _plain(value):
    if isinstance(value, datetime):
        fd.require_utc(value, "projection timestamp")
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise ValueError("canonical object keys must be strings")
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("unsupported canonical projection value")


def canonical_payload(value) -> bytes:
    """Sorted UTF-8 JSON, final LF, UTC microseconds; retain -0.0 and nulls."""
    return fd.canonical_json(_plain(value))


def _digest(value) -> str:
    return hashlib.sha256(canonical_payload(value)).hexdigest()


@dataclass(frozen=True)
class HistoricalProjectionPolicy:
    version: str = "pqta-003d-5b-projection-v1"
    quality_scope: str = "target_endpoint_only"
    unsupported_field_action: str = "block_exact_projection"
    unresolved_association_action: str = "block_exact_projection"

    def __post_init__(self):
        if tuple(vars(self).values()) != (
            "pqta-003d-5b-projection-v1",
            "target_endpoint_only",
            "block_exact_projection",
            "block_exact_projection",
        ):
            raise ValueError("only approved Strict Fail-Closed v1 is supported")


POLICY = HistoricalProjectionPolicy()


@dataclass(frozen=True)
class SourceReceipt:
    mode: str
    authenticated_source_bytes: bool
    identity: ha.SourceIdentity
    source_hashes: tuple[tuple[str, str], ...]
    source_audit_sha256: str
    record_set_sha256: str
    anomaly_evidence_status: str = "unverified"

    @property
    def sha256(self):
        return _digest(self)


@dataclass(frozen=True, eq=False)
class SourceBinding:
    """Audit-side context. Construction alone cannot authenticate its contents."""

    identity: ha.SourceIdentity
    records: tuple[ha.HistoricalRecord, ...]
    receipt: SourceReceipt


@dataclass(frozen=True)
class _BindingState:
    receipt: SourceReceipt
    receipt_sha256: str
    records: tuple[ha.HistoricalRecord, ...]
    by_origin: Mapping
    row_digests: tuple[str, ...]
    feature_digests: tuple[str, ...]


# Object identity matters: copying a receipt or dataclasses.replace(binding)
# cannot mint a historical capability, even with plausible hashes/Booleans.
_BINDINGS: WeakKeyDictionary = WeakKeyDictionary()


def _mint(adapter, *, mode, source_hashes=(), source_audit_sha256):
    if not isinstance(adapter, ha.HistoricalAdapter):
        raise ValueError("typed historical adapter required")
    ha._check_identity(adapter.identity, adapter.manifest)
    if (
        type(adapter.records) is not tuple
        or adapter.research_only is not True
        or adapter.point_in_time_verified is not False
        or adapter.decision_eligible is not False
    ):
        raise ValueError("immutable research-only historical records required")
    by_origin = {}
    for i, row in enumerate(adapter.records):
        if not isinstance(row, ha.HistoricalRecord):
            raise ValueError("typed historical record required")
        p.validate_hour(row.origin)
        if (
            row.source_row_index != i
            or type(row.source_row_index) is not int
            or not row.source_identifier
            or row.origin in by_origin
            or i
            and row.origin != adapter.records[i - 1].origin + p.HOUR
            or row.period != p.evaluation_split(row.origin)
        ):
            raise ValueError("inconsistent source row identity or hourly timeline")
        by_origin[row.origin] = row
    rows = tuple(_digest(r) for r in adapter.records)
    receipt = SourceReceipt(
        mode,
        mode == "authenticated_pinned_history",
        adapter.identity,
        tuple(sorted(source_hashes)),
        source_audit_sha256,
        _digest(rows),
    )
    binding = SourceBinding(adapter.identity, adapter.records, receipt)
    _BINDINGS[binding] = _BindingState(
        receipt,
        receipt.sha256,
        adapter.records,
        MappingProxyType(by_origin),
        rows,
        tuple(_digest(r.features) for r in adapter.records),
    )
    return binding


def verify_pinned_source(root: Path) -> SourceBinding:
    """Mint a receipt only by invoking 5A's pinned-byte verification path.

    A caller-supplied HistoricalAudit/receipt/verification flag is not accepted.
    The receipt authenticates the snapshot read, not later filesystem state,
    referenced anomaly evidence, publication availability or tradability.
    """
    audit = ha.audit_pinned_history(Path(root))
    if audit.adapter is None:
        raise ValueError(f"pinned source verification failed: {audit.report}")
    identity = audit.adapter.identity
    if (
        identity.dataset_spec_id != ha.SPEC_ID
        or identity.artifact_build_id != ha.BUILD_ID
        or identity.silver_sha256 != fd.SILVER_SHA256
        or identity.gold_sha256 != fd.GOLD_SHA256
        or identity.manifest_sha256 != fd.MANIFEST_SHA256
    ):
        raise ValueError("unapproved pinned source identity")
    return _mint(
        audit.adapter,
        mode="authenticated_pinned_history",
        source_hashes=(
            *((name, digest) for name, digest in ha.ARTIFACT_HASHES.items()),
            ("silver", identity.silver_sha256),
            ("gold", identity.gold_sha256),
            ("manifest_canonical", identity.manifest_sha256),
        ),
        source_audit_sha256=hashlib.sha256(audit.canonical_report).hexdigest(),
    )


def bind_synthetic(adapter: ha.HistoricalAdapter) -> SourceBinding:
    """Bind explicit in-memory test fixtures, never authenticated history."""
    return _mint(
        adapter,
        mode="synthetic_fixture",
        source_audit_sha256=_digest({"mode": "synthetic_fixture"}),
    )


def _state(source, policy=POLICY):
    if type(policy) is not HistoricalProjectionPolicy or policy != POLICY:
        raise ValueError("approved projection policy required")
    if not isinstance(source, SourceBinding) or source not in _BINDINGS:
        raise ValueError("factory-issued source binding required")
    state = _BINDINGS[source]
    if (
        source.receipt is not state.receipt
        or source.identity != state.receipt.identity
        or source.records is not state.records
        or source.receipt.sha256 != state.receipt_sha256
    ):
        raise ValueError("source binding/receipt tampered")
    return state


@dataclass(frozen=True)
class OpaqueSourceRef:
    dataset_spec_id: str
    artifact_build_id: str
    receipt_sha256: str
    source_identifier: str
    source_row_index: int
    origin: datetime


def source_ref(source: SourceBinding, origin: datetime) -> OpaqueSourceRef:
    state = _state(source)
    p.validate_hour(origin)
    row = state.by_origin.get(origin)
    if row is None:
        raise ValueError("origin is not bound to source")
    return OpaqueSourceRef(
        source.identity.dataset_spec_id,
        source.identity.artifact_build_id,
        state.receipt_sha256,
        row.source_identifier,
        row.source_row_index,
        origin,
    )


def _bound_row(source, reference):
    state = _state(source)
    if not isinstance(reference, OpaqueSourceRef):
        raise ValueError("opaque source reference required")
    expected = source_ref(source, reference.origin)
    if reference != expected:
        raise ValueError("source key/reference mismatch")
    return state.by_origin[reference.origin]


@dataclass(frozen=True)
class LosslessRowAttachment:
    record: ha.HistoricalRecord
    source_ref: OpaqueSourceRef
    source_row_sha256: str


@dataclass(frozen=True)
class ForecastFieldsPlan:
    origin: datetime
    feature_open_t: datetime
    values: tuple[float | None, ...]
    null_reasons: tuple[str | None, ...]
    anomaly_involved_features: tuple[str, ...]
    feature_complete: bool
    feature_manifest_anomaly: bool
    ar_lag_valid: bool
    ar_lag_manifest_anomaly: bool
    source_ref: OpaqueSourceRef

    def forecast_fields(self):
        return {
            "forecast_origin_utc": self.origin,
            "feature_open_t": self.feature_open_t,
            **dict(zip(FEATURES, self.values, strict=True)),
            "feature_complete": self.feature_complete,
            "feature_manifest_anomaly": self.feature_manifest_anomaly,
            "anomaly_involved_features": self.anomaly_involved_features,
            "ar_lag_valid": self.ar_lag_valid,
            "ar_lag_manifest_anomaly": self.ar_lag_manifest_anomaly,
            "gold_available_at": None,
            "gold_decision_eligible": False,
            "research_only": True,
        }


@dataclass(frozen=True)
class OutcomeEnvelope:
    outcome: accounting.Outcome
    attachment: LosslessRowAttachment


@dataclass(frozen=True)
class ProjectionResult[T]:
    classification: str
    source_ref: OpaqueSourceRef
    value: T | None = None
    findings: tuple[str, ...] = ()
    unsupported_fields: tuple[str, ...] = ()

    def __post_init__(self):
        if self.classification not in CLASSIFICATIONS:
            raise ValueError("unknown projection classification")
        if (self.classification == "compatible") != (self.value is not None):
            raise ValueError("only compatible projections may carry a value")

    @property
    def execution_ready(self):
        return False

    @property
    def point_in_time_verified(self):
        return False

    @property
    def decision_eligible(self):
        return False


def _anomalies(records, row, *, feature_only=False):
    blocked, unsupported = set(), set()
    for a in records:
        if not isinstance(a, ha.HistoricalAnomaly):
            raise ValueError("typed anomaly record required")
        if a.source_row_index != row.source_row_index:
            raise ValueError("anomaly row identity mismatch")
        expected_column = {
            "target_endpoint": "target_endpoint_anomalies",
            "feature_window": "involved_anomalies",
        }.get(a.association)
        if expected_column is None:
            blocked.add("unresolved_anomaly_association")
        elif a.source_column != expected_column:
            raise ValueError("anomaly source association mismatch")
        if feature_only and a.association != "feature_window":
            blocked.add("unresolved_anomaly_association")
        raw = a.raw
        p.validate_hour(raw["timestamp"])
        if raw["anomaly_type"] not in ANOMALY_TYPES:
            blocked.add("unknown_anomaly_type")
        names = raw["affected_fields"]
        if (
            not isinstance(names, (tuple, list))
            or not names
            or any(type(f) is not str for f in names)
            or len(set(names)) != len(names)
        ):
            raise ValueError("invalid original anomaly fields")
        unsupported.update(set(names) - OHLCV)
        if a.association == "target_endpoint" and raw["timestamp"] not in (
            row.origin - p.HOUR,
            row.origin,
        ):
            raise ValueError("anomaly is not at a target endpoint")
        if a.association == "feature_window" and not (
            row.origin - 169 * p.HOUR <= raw["timestamp"] <= row.origin - p.HOUR
        ):
            raise ValueError("anomaly is outside source feature window")
    blocked.update(f"unsupported_anomaly_field:{f}" for f in unsupported)
    return tuple(sorted(blocked)), tuple(sorted(unsupported))


def _feature_status(features, row, state):
    if (
        not isinstance(features, ha.HistoricalFeatures)
        or features is not row.features
        or _digest(features) != state.feature_digests[row.source_row_index]
        or features.origin != row.origin
        or features.feature_open_t + p.HOUR != row.origin
        or type(features.values) is not tuple
        or len(features.values) != len(FEATURES)
        or type(features.null_reasons) is not tuple
        or len(features.null_reasons) != len(FEATURES)
    ):
        raise ValueError("source feature identity/schema mismatch")
    p.validate_hour(features.feature_open_t)
    for value, reason in zip(features.values, features.null_reasons, strict=True):
        if value is not None:
            accounting.finite(value)
        if (value is None) != (reason is not None):
            raise ValueError("feature null state contradicts reason")
        if reason is not None and reason not in fd.GOLD_NULL_REASONS:
            raise ValueError("unknown feature null reason")
    for flag in (
        features.feature_manifest_anomaly,
        features.ar_lag_valid,
        features.ar_lag_manifest_anomaly,
    ):
        p._boolean(flag)
    names = features.anomaly_involved_features
    if (
        type(names) is not tuple
        or tuple(f for f in FEATURES if f in names) != names
        or features.feature_manifest_anomaly != bool(names)
        or features.available_at is not None
        or features.decision_eligible is not False
    ):
        raise ValueError("feature mask/availability mismatch")
    raw = row.source_values
    complete = all(v is not None for v in features.values)
    for key in (
        "feature_complete",
        "current_candle_valid",
        "current_candle_present",
        "current_candle_complete",
        "source_present",
        "missing_hour",
        "ar_lag_valid",
        "ar_lag_manifest_anomaly",
        "feature_manifest_anomaly",
    ):
        p._boolean(raw[key])
    if (
        raw["current_candle_valid"] != raw["current_candle_present"]
        or raw["current_candle_present"] != raw["source_present"]
        or raw["missing_hour"] == raw["source_present"]
        or raw["current_candle_complete"]
        != (
            raw["source_present"]
            and row.origin <= state.receipt.identity.analysis_as_of
        )
    ):
        raise ValueError("source presence/validity/completeness masks disagree")
    if (
        raw["feature_complete"] != complete
        or tuple(raw[f] for f in FEATURES) != features.values
        or tuple(raw[f"null_reason__{f}"] for f in FEATURES) != features.null_reasons
        or tuple(raw["anomaly_involved_features"]) != names
        or raw["feature_manifest_anomaly"] != features.feature_manifest_anomaly
        or raw["ar_lag_valid"] != features.ar_lag_valid
        or raw["ar_lag_manifest_anomaly"] != features.ar_lag_manifest_anomaly
        or canonical_payload(raw["involved_anomalies"])
        != canonical_payload(tuple(a.raw for a in features.anomalies))
    ):
        raise ValueError("inconsistent source feature metadata")
    previous = state.by_origin.get(row.origin - p.HOUR)
    previous_valid = (
        previous.source_values["current_candle_valid"]
        if previous is not None
        else False
    )
    p._boolean(previous_valid)
    exact_lag_valid = (
        raw["current_candle_valid"]
        and previous_valid
        and raw["current_candle_complete"]
    )
    if features.ar_lag_valid != exact_lag_valid or (
        features.ar_lag_valid and features.values[0] is None
    ):
        raise ValueError("AR lag lacks exact valid adjacent candles")
    return _anomalies(features.anomalies, row, feature_only=True)


def plan_forecast_fields(
    features: ha.HistoricalFeatures,
    *,
    source: SourceBinding,
    reference: OpaqueSourceRef,
    policy=POLICY,
) -> ProjectionResult[ForecastFieldsPlan]:
    """Feature-only plan; never inspect a current/future outcome or attachment."""
    state = _state(source, policy)
    row = _bound_row(source, reference)
    if p.evaluation_split(reference.origin) == "outside_approved_evaluation_window":
        return ProjectionResult("audit_only", reference)
    try:
        findings, unsupported = _feature_status(features, row, state)
        if findings:
            return ProjectionResult(
                "blocked", reference, findings=findings, unsupported_fields=unsupported
            )
        plan = ForecastFieldsPlan(
            features.origin,
            features.feature_open_t,
            features.values,
            features.null_reasons,
            features.anomaly_involved_features,
            all(v is not None for v in features.values),
            features.feature_manifest_anomaly,
            features.ar_lag_valid,
            features.ar_lag_manifest_anomaly,
            reference,
        )
        p.validate_forecast_fields(plan.forecast_fields())
        return ProjectionResult("compatible", reference, plan)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return ProjectionResult("failed", reference, findings=(str(exc),))


def project_closed_outcome(
    record: ha.HistoricalRecord,
    *,
    source: SourceBinding,
    checked_at: datetime,
    policy=POLICY,
) -> ProjectionResult[OutcomeEnvelope]:
    """Check clocks before target flags, raw attachments or row digests."""
    state = _state(source, policy)
    p.validate_hour(checked_at)
    reference = source_ref(source, record.origin)
    row = _bound_row(source, reference)
    if row is not record:
        return ProjectionResult("failed", reference, findings=("source_row_not_bound",))
    if row.period == "outside_approved_evaluation_window":
        return ProjectionResult("audit_only", reference)
    if row.origin + p.HOUR > checked_at:
        return ProjectionResult(
            "not_closed", reference, findings=("target_not_closed",)
        )
    try:
        if _digest(row) != state.row_digests[row.source_row_index]:
            raise ValueError("bound source row changed")
        feature_findings, feature_unsupported = _feature_status(
            row.features, row, state
        )
        outcome = row.outcome
        if (
            not isinstance(outcome, ha.HistoricalOutcome)
            or outcome.origin != row.origin
        ):
            raise ValueError("source outcome identity mismatch")
        raw = row.source_values
        if (
            raw["forecast_origin_utc"] != row.origin
            or raw["feature_open_t"] != row.features.feature_open_t
            or raw["split_id"] != row.period
            or tuple(raw[f] for f in FEATURES) != row.features.values
            or raw["target_next_1h_log_return"] != outcome.target
            or raw["target_valid"] is not outcome.target_valid
            or tuple(raw["target_null_reasons"]) != outcome.invalid_reasons
            or raw["target_primary_null_reason"] != outcome.target_primary_null_reason
            or raw["target_manifest_anomaly"] is not outcome.target_manifest_anomaly
            or raw["feature_complete"]
            != all(v is not None for v in row.features.values)
            or raw["ar_lag_valid"] is not row.features.ar_lag_valid
            or outcome.feature_window_anomalies != row.features.anomalies
        ):
            raise ValueError("inconsistent source metadata")
        reasons = accounting.ordered_reasons(
            outcome.invalid_reasons, fd.TARGET_REASON_PRIORITY
        )
        if outcome.target_primary_null_reason != (reasons[0] if reasons else None):
            raise ValueError("conflicting target primary reason")
        if outcome.target_manifest_anomaly != bool(outcome.target_endpoint_anomalies):
            raise ValueError("target anomaly mask inconsistent with endpoint records")
        if canonical_payload(raw["target_endpoint_anomalies"]) != canonical_payload(
            tuple(a.raw for a in outcome.target_endpoint_anomalies)
        ):
            raise ValueError("target endpoint records differ from original source")
        if any(
            a.association != "target_endpoint"
            for a in outcome.target_endpoint_anomalies
        ):
            raise ValueError(
                "target endpoint collection contains a different association"
            )
        p._boolean(outcome.target_valid)
        p._boolean(outcome.target_manifest_anomaly)
        if outcome.target_valid:
            accounting.finite(outcome.target)
            if reasons:
                raise ValueError("valid target has invalid reasons")
        elif outcome.target is not None or not reasons:
            raise ValueError("invalid target must retain null value and reasons")
        anomalies = (
            *outcome.target_endpoint_anomalies,
            *outcome.feature_window_anomalies,
            *outcome.unresolved_anomalies,
        )
        findings, unsupported = _anomalies(anomalies, row)
        findings = tuple(sorted(set(findings) | set(feature_findings)))
        unsupported = tuple(sorted(set(unsupported) | set(feature_unsupported)))
        if findings:
            return ProjectionResult(
                "blocked", reference, findings=findings, unsupported_fields=unsupported
            )
        endpoints = outcome.target_endpoint_anomalies
        quality = accounting.Quality(
            feature_complete=raw["feature_complete"],
            ar_lag_valid=row.features.ar_lag_valid,
            anomaly_types=tuple(sorted({a.raw["anomaly_type"] for a in endpoints})),
            affected_fields=tuple(
                sorted({f for a in endpoints for f in a.raw["affected_fields"]})
            ),
        )
        value = accounting.Outcome(
            row.origin,
            outcome.target,
            outcome.target_valid,
            reasons,
            outcome.target_manifest_anomaly,
            quality,
            "unverified",
        )
        return ProjectionResult(
            "compatible",
            reference,
            OutcomeEnvelope(
                value,
                LosslessRowAttachment(
                    row, reference, state.row_digests[row.source_row_index]
                ),
            ),
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return ProjectionResult("failed", reference, findings=(str(exc),))


@dataclass(frozen=True)
class HistorySelection:
    source_ref: OpaqueSourceRef
    classification: str
    eligible: bool | None
    findings: tuple[str, ...]


def plan_completed_history(
    source: SourceBinding, *, forecast_origin, method, sample, policy=POLICY
) -> tuple[HistorySelection, ...]:
    """Selection audit only; no fit, model-input conversion or evaluation."""
    _state(source, policy)
    p.require_evaluation_origin(forecast_origin)
    p._method(method)
    p._sample(sample)
    result = []
    for row in source.records:
        projection = project_closed_outcome(
            row, source=source, checked_at=forecast_origin, policy=policy
        )
        eligible = None
        if projection.classification == "compatible":
            outcome, features = projection.value.outcome, row.features
            eligible = p.historical_row_eligible(
                method,
                sample,
                label_origin=row.origin,
                current_origin=forecast_origin,
                target_valid=outcome.target_valid,
                target_manifest_anomaly=outcome.target_manifest_anomaly,
                feature_complete=outcome.quality.feature_complete,
                feature_manifest_anomaly=features.feature_manifest_anomaly,
                ar_lag_valid=features.ar_lag_valid,
                ar_lag_manifest_anomaly=features.ar_lag_manifest_anomaly,
            )
        result.append(
            HistorySelection(
                projection.source_ref,
                projection.classification,
                eligible,
                projection.findings,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class CompatibilityAudit:
    report: Mapping
    canonical_report: bytes
    payload_sha256: str


def audit_compatibility(
    source: SourceBinding, *, checked_at, origins=None, policy=POLICY
) -> CompatibilityAudit:
    """Classify every declared origin in memory, never shrink a blocked scope.

    The payload digest excludes its own field; canonical_report includes it.
    This is NOT pqta-model-evaluation-v1 or evidence of model performance.
    """
    state = _state(source, policy)
    p.validate_hour(checked_at)
    requested = tuple(state.by_origin) if origins is None else tuple(origins)
    for origin in requested:
        p.validate_hour(origin)
    if (
        len(set(requested)) != len(requested)
        or not set(requested) <= state.by_origin.keys()
    ):
        raise ValueError("declared scope has duplicate or unbound origins")
    requested = tuple(sorted(requested))
    rows, counts, reasons, unsupported = [], Counter(), Counter(), Counter()
    for origin in requested:
        item = project_closed_outcome(
            state.by_origin[origin], source=source, checked_at=checked_at, policy=policy
        )
        counts[item.classification] += 1
        reasons.update(item.findings)
        unsupported.update(item.unsupported_fields)
        rows.append(
            {
                "source_ref": _plain(item.source_ref),
                "classification": item.classification,
                "findings": item.findings,
                "unsupported_fields": item.unsupported_fields,
            }
        )
    scope = {"origins": requested, "checked_at": checked_at}
    spec = {"policy": policy, "source_receipt": state.receipt_sha256, "scope": scope}
    build = {
        "spec_id": _digest(spec),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dependencies": fd._dependency_versions(),
        "serializer": SERIALIZER_VERSION,
    }
    report = {
        "schema_version": "pqta-003d-5c-compatibility-v1",
        "policy_id": policy.version,
        "policy_sha256": _digest(policy),
        "projection_spec_id": _digest(spec),
        "projection_build_id": _digest(build),
        "serializer_version": SERIALIZER_VERSION,
        "source_identity": _plain(source.identity),
        "source_receipt": _plain(source.receipt),
        "source_receipt_sha256": state.receipt_sha256,
        "source_integrity_status": source.receipt.mode,
        "declared_scope": _plain(scope),
        "counts": {
            "total_origins": len(requested),
            **{name: counts[name] for name in CLASSIFICATIONS},
        },
        "blocking_reasons": dict(sorted(reasons.items())),
        "unsupported_fields": dict(sorted(unsupported.items())),
        "rows": rows,
        "scope_projectable": bool(requested)
        and source.receipt.authenticated_source_bytes
        and not any(counts[k] for k in ("blocked", "failed", "not_closed")),
        "execution_ready": False,
        "point_in_time_verified": False,
        "decision_eligible": False,
        "anomaly_evidence_status": "unverified",
        "execution_blockers": [
            "historical_execution_not_authorized",
            "historical_reporting_deferred",
            "historical_publication_unverified",
        ],
    }
    digest = _digest(report)
    report["payload_sha256"] = digest
    return CompatibilityAudit(ha._freeze(report), canonical_payload(report), digest)
