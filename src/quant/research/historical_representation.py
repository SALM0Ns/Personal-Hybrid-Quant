"""Lossless native anomaly inspection, never a historical execution bridge.

Source capabilities reuse 5C's pinned verifier and private binding. Native
contexts add exact observed manifest bytes; neither hashes nor constructors
authenticate caller input. No forecast, training, score, report-engine or
writer interface exists here. See the 5E implementation contract.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from weakref import WeakKeyDictionary

from quant.features.manifest import ANOMALY_TYPES, AnomalyManifest
from quant.research import evaluation_protocol as p
from quant.research import forecast_dataset as fd
from quant.research import historical_adapter as ha
from quant.research import historical_projection as hp

SCHEMA_VERSION = "pqta-historical-anomaly-representation-v1"
POLICY_VERSION = "pqta-003d-5d-representation-v1"
SERIALIZER_VERSION = "pqta-003d-5e-canonical-v1"
TOKENS = frozenset({"open", "high", "low", "close", "volume", "candle", "unknown"})
COLLECTIONS = (
    "target_endpoint_anomalies",
    "feature_window_anomalies",
    "unresolved_anomalies",
)
ROLES = ("target_endpoint", "feature_window", "unresolved")
LIMITATIONS = (
    "historical_execution_not_authorized",
    "historical_scoring_accounting_reporting_deferred",
    "anomaly_evidence_not_independently_verified",
    "historical_publication_availability_unverified",
    "native_representability_is_not_model_eligibility",
)


def _plain(value):
    if isinstance(value, datetime):
        fd.require_utc(value, "native timestamp")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise ValueError("canonical keys must be strings")
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite native value")
        return value
    if value is None or type(value) in (str, bool, int):
        return value
    raise ValueError("unsupported canonical native value")


def canonical_payload(value) -> bytes:
    """Sorted compact UTF-8 JSON + LF; preserve arrays, nulls and signed zero."""
    return fd.canonical_json(_plain(value))


def _digest(value):
    return hashlib.sha256(canonical_payload(value)).hexdigest()


def _require_digest(value):
    if not fd._valid_digest(value):
        raise ValueError("invalid native SHA-256 syntax")


def _validate_ref(ref):
    if not isinstance(ref, hp.OpaqueSourceRef):
        raise ValueError("typed native source reference required")
    for value in (ref.dataset_spec_id, ref.artifact_build_id, ref.receipt_sha256):
        _require_digest(value)
    p.validate_hour(ref.origin)
    if (
        type(ref.source_row_index) is not int
        or ref.source_row_index < 0
        or type(ref.source_identifier) is not str
        or not ref.source_identifier
    ):
        raise ValueError("invalid native source row reference")


@dataclass(frozen=True)
class NativePolicy:
    schema_version: str = SCHEMA_VERSION
    policy_version: str = POLICY_VERSION
    serializer_version: str = SERIALIZER_VERSION

    def __post_init__(self):
        if tuple(vars(self).values()) != (
            SCHEMA_VERSION,
            POLICY_VERSION,
            SERIALIZER_VERSION,
        ):
            raise ValueError("unapproved native schema/policy/serializer version")


POLICY = NativePolicy()


@dataclass(frozen=True)
class ManifestReference:
    source_identifier: str
    canonical_sha256: str
    raw_sha256: str
    manifest_version: str

    def __post_init__(self):
        for value in (self.canonical_sha256, self.raw_sha256):
            _require_digest(value)
        if any(
            type(v) is not str or not v
            for v in (self.source_identifier, self.manifest_version)
        ):
            raise ValueError("manifest identifier/version required")


@dataclass(frozen=True, eq=False)
class NativeSource:
    """Audit-side context, not a forecast capability. Constructors prove nothing."""

    binding: hp.SourceBinding
    manifest_reference: ManifestReference


@dataclass(frozen=True)
class _NativeState:
    binding: hp.SourceBinding
    manifest_reference: ManifestReference
    reference_sha256: str
    raw_bytes: bytes
    raw_manifest: Mapping
    manifest: AnomalyManifest
    by_key: Mapping


_SOURCES: WeakKeyDictionary = WeakKeyDictionary()
# No files or persistent artifact store: this rejects conflicting canonical
# bytes for one immutable build only within the current process.
_BUILD_PAYLOADS: dict[str, str] = {}


def _decode_manifest(raw_bytes):
    if type(raw_bytes) is not bytes:
        raise ValueError("exact manifest bytes required")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate manifest JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite manifest JSON")

    try:
        raw = json.loads(raw_bytes, object_pairs_hook=unique, parse_constant=nonfinite)
        canonical_payload(raw)  # Also reject exponent overflow, e.g. 1e999.
        return raw, AnomalyManifest.from_dict(raw)
    except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid raw manifest JSON") from exc


def _register(binding, raw_bytes):
    hp._state(binding)
    raw, manifest = _decode_manifest(raw_bytes)
    ha._check_identity(binding.identity, manifest)
    reference = ManifestReference(
        ha.MANIFEST_PATH
        if binding.receipt.authenticated_source_bytes
        else "in_memory:anomaly_manifest",
        manifest.sha256,
        hashlib.sha256(raw_bytes).hexdigest(),
        manifest.manifest_version,
    )
    by_key = {}
    for i, record in enumerate(manifest.records):
        key = record.timestamp, record.anomaly_type
        if key in by_key:
            raise ValueError("ambiguous manifest record identity")
        by_key[key] = i
    source = NativeSource(binding, reference)
    _SOURCES[source] = _NativeState(
        binding,
        reference,
        _digest(reference),
        raw_bytes,
        ha._freeze(raw),
        manifest,
        ha._freeze(by_key),
    )
    return source


def verify_pinned_representation_source(root: Path) -> NativeSource:
    """Reuse pinned byte authentication; independently bind observed manifest bytes.

    The legacy receipt pins the canonical manifest, not its raw serialization.
    Reading these bytes separately does not claim a pre-approved raw-byte hash.
    """
    root = Path(root)
    binding = hp.verify_pinned_source(root)
    hp._state(binding)
    if (
        binding.receipt.mode != "authenticated_pinned_history"
        or binding.receipt.authenticated_source_bytes is not True
        or binding.identity.dataset_spec_id != ha.SPEC_ID
        or binding.identity.artifact_build_id != ha.BUILD_ID
    ):
        raise ValueError("authenticated approved pinned source required")
    try:
        raw = (root / ha.MANIFEST_PATH).read_bytes()
    except OSError as exc:
        raise ValueError("pinned manifest bytes unavailable") from exc
    return _register(binding, raw)


def bind_synthetic_representation(
    adapter: ha.HistoricalAdapter, *, manifest_bytes: bytes | None = None
) -> NativeSource:
    """Explicit synthetic fixtures never authenticate approved historical bytes."""
    return _register(
        hp.bind_synthetic(adapter),
        adapter.manifest.to_bytes() if manifest_bytes is None else manifest_bytes,
    )


def _state(source, policy=POLICY):
    if type(policy) is not NativePolicy or policy != POLICY:
        raise ValueError("approved native policy required")
    if type(source) is not NativeSource or source not in _SOURCES:
        raise ValueError("factory-issued native source required")
    state = _SOURCES[source]
    if (
        source.binding is not state.binding
        or source.manifest_reference is not state.manifest_reference
        or _digest(source.manifest_reference) != state.reference_sha256
        or hashlib.sha256(state.raw_bytes).hexdigest()
        != source.manifest_reference.raw_sha256
    ):
        raise ValueError("native source/manifest binding tampered")
    hp._state(source.binding)
    return state


@dataclass(frozen=True)
class NativeOccurrence:
    source_ref: hp.OpaqueSourceRef
    collection: str
    position: int
    association: str
    source_column: str
    raw: Mapping
    linkage: str
    manifest_record_index: int | None
    manifest_record_sha256: str | None
    manifest_record: Mapping | None

    def __post_init__(self):
        _validate_ref(self.source_ref)
        if (
            not isinstance(self.source_ref, hp.OpaqueSourceRef)
            or self.collection not in COLLECTIONS
            or type(self.position) is not int
            or self.position < 0
            or self.association != ROLES[COLLECTIONS.index(self.collection)]
            or type(self.source_column) is not str
            or not self.source_column
            or not isinstance(self.raw, Mapping)
            or self.linkage
            not in {"matched", "missing", "contradictory", "unknown_vocabulary"}
        ):
            raise ValueError("invalid native occurrence schema")
        expected_role = {
            "target_endpoint_anomalies": "target_endpoint",
            "involved_anomalies": "feature_window",
        }.get(self.source_column, "unresolved")
        if self.association != expected_role:
            raise ValueError("native occurrence source column/role mismatch")
        matched = self.linkage == "matched"
        if matched:
            if (
                type(self.manifest_record_index) is not int
                or self.manifest_record_index < 0
                or not isinstance(self.manifest_record, Mapping)
            ):
                raise ValueError("matched manifest record required")
            _require_digest(self.manifest_record_sha256)
            if _digest(self.manifest_record) != self.manifest_record_sha256:
                raise ValueError("manifest record digest mismatch")
        elif any(
            v is not None
            for v in (
                self.manifest_record_index,
                self.manifest_record_sha256,
                self.manifest_record,
            )
        ):
            raise ValueError("unmatched occurrence cannot claim manifest evidence")
        canonical_payload(self.raw)
        object.__setattr__(self, "raw", ha._freeze(self.raw))
        if matched:
            object.__setattr__(
                self, "manifest_record", ha._freeze(self.manifest_record)
            )


@dataclass(frozen=True)
class NativeDimensions:
    native_representability: str
    legacy_4a_compatibility: str
    source_authentication: str
    association_resolution: str
    evidence_completeness: str
    temporal_closure: str

    def __post_init__(self):
        allowed = (
            {"represented", "blocked", "failed", "not_inspected"},
            set(hp.CLASSIFICATIONS),
            {"authenticated_pinned_history", "synthetic_fixture"},
            {"resolved", "unresolved", "not_inspected"},
            {
                "recorded_references_unverified",
                "unresolved_linkage",
                "no_occurrences",
                "not_inspected",
            },
            {"closed", "not_closed"},
        )
        if any(
            value not in choices
            for value, choices in zip(vars(self).values(), allowed, strict=True)
        ):
            raise ValueError("invalid native audit dimension")


@dataclass(frozen=True)
class NativeEnvelope:
    record: ha.HistoricalRecord
    occurrences: tuple[NativeOccurrence, ...]

    def __post_init__(self):
        if (
            not isinstance(self.record, ha.HistoricalRecord)
            or type(self.occurrences) is not tuple
            or any(not isinstance(a, NativeOccurrence) for a in self.occurrences)
        ):
            raise ValueError("typed immutable native envelope required")
        p.validate_hour(self.record.origin)
        expected_positions = Counter()
        order = []
        first_ref = self.occurrences[0].source_ref if self.occurrences else None
        for occurrence in self.occurrences:
            ref = occurrence.source_ref
            if (
                ref != first_ref
                or ref.origin != self.record.origin
                or ref.source_row_index != self.record.source_row_index
                or ref.source_identifier != self.record.source_identifier
                or occurrence.position != expected_positions[occurrence.collection]
            ):
                raise ValueError("native envelope occurrence/source identity mismatch")
            expected_positions[occurrence.collection] += 1
            order.append(COLLECTIONS.index(occurrence.collection))
        if order != sorted(order):
            raise ValueError("native envelope collection order mismatch")


@dataclass(frozen=True)
class NativeResult:
    source_ref: hp.OpaqueSourceRef
    period: str
    dimensions: NativeDimensions
    findings: tuple[str, ...]
    envelope: NativeEnvelope | None = None

    def __post_init__(self):
        _validate_ref(self.source_ref)
        if (
            self.period != p.evaluation_split(self.source_ref.origin)
            or type(self.dimensions) is not NativeDimensions
            or type(self.findings) is not tuple
            or any(type(f) is not str or not f for f in self.findings)
            or len(set(self.findings)) != len(self.findings)
        ):
            raise ValueError("invalid native result schema")
        guarded = (
            self.dimensions.temporal_closure != "closed"
            or self.dimensions.legacy_4a_compatibility == "audit_only"
            or self.dimensions.native_representability == "not_inspected"
        )
        if guarded and self.envelope is not None:
            raise ValueError("uninspected native result cannot expose an envelope")
        if (
            self.dimensions.native_representability == "represented"
            and self.envelope is None
        ):
            raise ValueError("represented native result requires an envelope")
        if self.envelope is not None:
            if not isinstance(self.envelope, NativeEnvelope):
                raise ValueError("typed native envelope required")
            row = self.envelope.record
            if (
                row.origin != self.source_ref.origin
                or row.source_row_index != self.source_ref.source_row_index
                or row.source_identifier != self.source_ref.source_identifier
                or any(
                    a.source_ref != self.source_ref for a in self.envelope.occurrences
                )
            ):
                raise ValueError("native result/envelope source identity mismatch")

    @property
    def execution_ready(self):
        return False

    @property
    def point_in_time_verified(self):
        return False

    @property
    def decision_eligible(self):
        return False


def _occurrence(state, row, ref, collection, position, annotation):
    if not isinstance(annotation, ha.HistoricalAnomaly) or (
        annotation.source_row_index != row.source_row_index
        or annotation.association != ROLES[COLLECTIONS.index(collection)]
    ):
        raise ValueError("anomaly source identity/association mismatch")
    expected_role = {
        "target_endpoint_anomalies": "target_endpoint",
        "involved_anomalies": "feature_window",
    }.get(annotation.source_column, "unresolved")
    if annotation.association != expected_role:
        raise ValueError("anomaly source column/role contradiction")
    raw = annotation.raw
    names, kind = raw.get("affected_fields"), raw.get("anomaly_type")
    if "timestamp" in raw:
        p.validate_hour(raw["timestamp"])
    if (
        "affected_fields" in raw
        and (
            not isinstance(names, (tuple, list))
            or not names
            or any(type(f) is not str or not f for f in names)
            or len(set(names)) != len(names)
        )
        or "anomaly_type" in raw
        and (type(kind) is not str or not kind)
    ):
        raise ValueError("invalid original anomaly vocabulary structure")
    if (
        "timestamp" in raw
        and annotation.association == "target_endpoint"
        and raw["timestamp"]
        not in (
            row.origin - p.HOUR,
            row.origin,
        )
    ):
        raise ValueError("anomaly outside target endpoints")
    if (
        "timestamp" in raw
        and annotation.association == "feature_window"
        and not (row.origin - 169 * p.HOUR <= raw["timestamp"] <= row.origin - p.HOUR)
    ):
        raise ValueError("anomaly outside feature window")
    if not {"timestamp", "anomaly_type", "affected_fields"} <= raw.keys():
        linkage = "missing"
    elif kind not in ANOMALY_TYPES or not set(names) <= TOKENS:
        linkage = "unknown_vocabulary"
    else:
        allowed = {"candle"} if kind == "missing_hour" else TOKENS - {"candle"}
        if not set(names) <= allowed:
            raise ValueError("invalid manifest type/token combination")
        index = state.by_key.get((raw["timestamp"], kind))
        linkage = "missing" if index is None else "matched"
        if index is not None:
            summary = fd._anomaly_record(state.manifest.records[index])
            for key, value in summary.items():
                if key not in raw:
                    linkage = "missing"
                    continue
                supplied = raw[key]
                if key in {"affected_fields", "evidence_references"}:
                    if (
                        not isinstance(supplied, (tuple, list))
                        or any(type(v) is not str for v in supplied)
                        or len(set(supplied)) != len(supplied)
                    ):
                        linkage = "contradictory"
                        break
                    supplied = sorted(supplied)
                if canonical_payload(supplied) != canonical_payload(value):
                    linkage = "contradictory"
                    break
            full = state.manifest.records[index]
            for key in state.raw_manifest["records"][index].keys() - summary.keys():
                if key not in raw:
                    continue
                supplied = raw[key]
                expected = getattr(full, key)
                if key == "recorded_source_close_at":
                    supplied = _evidence_time(supplied)
                elif key == "source_evidence":
                    supplied = _evidence_records(supplied)
                    expected = sorted(_plain(expected), key=lambda v: v["reference"])
                if canonical_payload(supplied) != canonical_payload(expected):
                    linkage = "contradictory"
                    break
    if linkage == "matched":
        manifest_record = state.raw_manifest["records"][index]
        record_digest = _digest(manifest_record)
    else:
        index = manifest_record = record_digest = None
    return NativeOccurrence(
        ref,
        collection,
        position,
        annotation.association,
        annotation.source_column,
        raw,
        linkage,
        index,
        record_digest,
        manifest_record,
    )


def _evidence_time(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    fd.require_utc(value, "native evidence timestamp")
    return _plain(value)


def _evidence_records(value):
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError("invalid supplied source evidence")
    result = []
    for record in value:
        if not isinstance(record, Mapping) or set(record) != {
            "reference",
            "sha256",
            "observed_at",
        }:
            raise ValueError("invalid supplied evidence schema")
        result.append({**record, "observed_at": _evidence_time(record["observed_at"])})
    return sorted(result, key=lambda v: v["reference"])


def _validate_core(row, binding_state):
    """Check source structure independently of 4A's anomaly vocabulary/schema.

    These are binding/copy/clock/null invariants, not new target arithmetic or
    feature calculations. Partial anomaly records are assessed separately.
    """
    raw, features, outcome = row.source_values, row.features, row.outcome
    if not isinstance(features, ha.HistoricalFeatures) or not isinstance(
        outcome, ha.HistoricalOutcome
    ):
        raise ValueError("typed original feature/outcome record required")
    p.validate_hour(features.feature_open_t)
    if (
        features.origin != row.origin
        or features.feature_open_t + p.HOUR != row.origin
        or outcome.origin != row.origin
        or set(raw) != set(fd.LEDGER_SCHEMA)
        or raw["forecast_origin_utc"] != row.origin
        or raw["feature_open_t"] != features.feature_open_t
        or raw["split_id"] != row.period
        or features.available_at is not None
        or features.decision_eligible is not False
    ):
        raise ValueError("native source clock/schema/availability mismatch")
    flags = (
        "feature_complete",
        "current_candle_valid",
        "current_candle_present",
        "current_candle_complete",
        "source_present",
        "missing_hour",
        "ar_lag_valid",
        "ar_lag_manifest_anomaly",
        "feature_manifest_anomaly",
        "target_valid",
        "target_manifest_anomaly",
    )
    for name in flags:
        p._boolean(raw[name])
    for flag in (
        outcome.target_valid,
        outcome.target_manifest_anomaly,
        features.feature_manifest_anomaly,
        features.ar_lag_valid,
        features.ar_lag_manifest_anomaly,
    ):
        p._boolean(flag)
    if len(features.values) != len(hp.FEATURES) or len(features.null_reasons) != len(
        hp.FEATURES
    ):
        raise ValueError("native feature order/length mismatch")
    for f, value, reason in zip(
        hp.FEATURES, features.values, features.null_reasons, strict=True
    ):
        if value is not None:
            hp.accounting.finite(value)
        if (
            (value is None) != (reason is not None)
            or reason is not None
            and reason not in fd.GOLD_NULL_REASONS
            or canonical_payload(raw[f]) != canonical_payload(value)
            or raw[f"null_reason__{f}"] != reason
        ):
            raise ValueError("native feature value/null-state mismatch")
    ordered = hp.accounting.ordered_reasons(
        outcome.invalid_reasons, fd.TARGET_REASON_PRIORITY
    )
    if (
        outcome.target_primary_null_reason != (ordered[0] if ordered else None)
        or raw["target_primary_null_reason"] != outcome.target_primary_null_reason
        or tuple(raw["target_null_reasons"]) != outcome.invalid_reasons
        or canonical_payload(raw["target_next_1h_log_return"])
        != canonical_payload(outcome.target)
        or raw["target_valid"] is not outcome.target_valid
        or raw["target_manifest_anomaly"] is not outcome.target_manifest_anomaly
        or outcome.target_manifest_anomaly != bool(outcome.target_endpoint_anomalies)
    ):
        raise ValueError("native target/flag/reason identity mismatch")
    if outcome.target_valid:
        hp.accounting.finite(outcome.target)
        if outcome.invalid_reasons:
            raise ValueError("valid target has invalid reasons")
    elif outcome.target is not None or not outcome.invalid_reasons:
        raise ValueError("invalid target must preserve null and reasons")
    for column, records in (
        ("involved_anomalies", outcome.feature_window_anomalies),
        ("target_endpoint_anomalies", outcome.target_endpoint_anomalies),
    ):
        if canonical_payload(raw[column]) != canonical_payload(
            tuple(a.raw for a in records)
        ):
            raise ValueError("native raw annotation collection mismatch")
    previous = binding_state.by_origin.get(row.origin - p.HOUR)
    previous_valid = (
        previous.source_values["current_candle_valid"] if previous else False
    )
    p._boolean(previous_valid)
    names = features.anomaly_involved_features
    if (
        outcome.feature_window_anomalies != features.anomalies
        or raw["feature_complete"] != all(v is not None for v in features.values)
        or raw["source_present"] != raw["current_candle_present"]
        or raw["current_candle_valid"] != raw["source_present"]
        or raw["missing_hour"] == raw["source_present"]
        or raw["current_candle_complete"]
        != (
            raw["source_present"]
            and row.origin <= binding_state.receipt.identity.analysis_as_of
        )
        or features.ar_lag_valid
        != (
            raw["current_candle_valid"]
            and previous_valid
            and raw["current_candle_complete"]
        )
        or features.ar_lag_valid
        and features.values[0] is None
        or features.feature_manifest_anomaly != bool(names)
        or tuple(f for f in hp.FEATURES if f in names) != names
        or tuple(raw["anomaly_involved_features"]) != names
        or raw["feature_manifest_anomaly"] is not features.feature_manifest_anomaly
        or raw["ar_lag_valid"] is not features.ar_lag_valid
        or raw["ar_lag_manifest_anomaly"] is not features.ar_lag_manifest_anomaly
    ):
        raise ValueError("native source feature/adjacency masks mismatch")


def represent_closed(
    source: NativeSource, origin: datetime, *, checked_at: datetime, policy=POLICY
) -> NativeResult:
    """Inspect only closed outcomes; clocks precede all row/outcome traversal."""
    state = _state(source, policy)
    p.validate_hour(origin)
    p.validate_hour(checked_at)
    ref = hp.source_ref(state.binding, origin)
    row = hp._bound_row(state.binding, ref)
    closed = origin + p.HOUR <= checked_at
    period = p.evaluation_split(origin)
    outside = period == "outside_approved_evaluation_window"
    auth = state.binding.receipt.mode
    if outside or not closed:
        return NativeResult(
            ref,
            period,
            NativeDimensions(
                "not_inspected",
                "audit_only" if outside else "not_closed",
                auth,
                "not_inspected",
                "not_inspected",
                "closed" if closed else "not_closed",
            ),
            ("audit_only",) if outside else ("target_not_closed",),
        )
    binding_state = hp._state(state.binding)
    if hp._digest(row) != binding_state.row_digests[row.source_row_index]:
        raise ValueError("bound native source row changed")
    legacy = hp.project_closed_outcome(row, source=state.binding, checked_at=checked_at)
    try:
        _validate_core(row, binding_state)
        occurrences = tuple(
            _occurrence(state, row, ref, collection, position, annotation)
            for collection in COLLECTIONS
            for position, annotation in enumerate(getattr(row.outcome, collection))
        )
        links = {a.linkage for a in occurrences}
        representation = (
            "failed"
            if "contradictory" in links
            else "blocked"
            if links - {"matched"}
            else "represented"
        )
        association = "unresolved" if row.outcome.unresolved_anomalies else "resolved"
        evidence = (
            "no_occurrences"
            if not occurrences
            else "unresolved_linkage"
            if links != {"matched"}
            else "recorded_references_unverified"
        )
        findings = tuple(
            sorted(
                (
                    {"unresolved_anomaly_association"}
                    if association == "unresolved"
                    else set()
                )
                | {"manifest_linkage:" + link for link in links if link != "matched"}
            )
        )
        return NativeResult(
            ref,
            period,
            NativeDimensions(
                representation,
                legacy.classification,
                auth,
                association,
                evidence,
                "closed",
            ),
            findings,
            NativeEnvelope(row, occurrences),
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return NativeResult(
            ref,
            period,
            NativeDimensions(
                "failed",
                legacy.classification,
                auth,
                "not_inspected",
                "not_inspected",
                "closed",
            ),
            (str(exc),),
        )


def representation_spec_id(spec: Mapping) -> str:
    """Hash a logical specification; this helper does not authenticate inputs."""
    if not isinstance(spec, Mapping):
        raise ValueError("representation specification mapping required")
    return _digest(spec)


def representation_build_id(
    spec_id, *, code_sha256, dependency_versions, serializer_version=SERIALIZER_VERSION
) -> str:
    _require_digest(spec_id)
    _require_digest(code_sha256)
    if (
        not isinstance(dependency_versions, Mapping)
        or not dependency_versions
        or any(
            type(k) is not str or not k or type(v) is not str or not v
            for k, v in dependency_versions.items()
        )
        or type(serializer_version) is not str
        or not serializer_version
    ):
        raise ValueError("explicit build versions required")
    return _digest(
        {
            "representation_spec_id": spec_id,
            "code_sha256": code_sha256,
            "dependency_versions": dependency_versions,
            "serializer_version": serializer_version,
        }
    )


def _code_digest():
    root = Path(__file__).resolve().parents[1]
    names = (
        "research/historical_representation.py",
        "research/historical_adapter.py",
        "research/historical_projection.py",
        "research/forecast_dataset.py",
        "research/evaluation_protocol.py",
        "research/forecast_accounting.py",
        "features/manifest.py",
        "features/engine.py",
    )
    return _digest(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    )


@dataclass(frozen=True)
class NativeAudit:
    report: Mapping
    canonical_report: bytes
    payload_sha256: str


def audit_native(source, *, checked_at, origins=None, policy=POLICY) -> NativeAudit:
    """Conserve a declared read-only audit universe; never execute or persist it."""
    state = _state(source, policy)
    p.validate_hour(checked_at)
    bound = hp._state(state.binding).by_origin
    requested = tuple(bound) if origins is None else tuple(origins)
    for origin in requested:
        p.validate_hour(origin)
    if len(set(requested)) != len(requested) or not set(requested) <= bound.keys():
        raise ValueError("duplicate or unbound native audit origin")
    requested = tuple(sorted(requested))
    scope = {"origins": requested, "checked_at": checked_at}
    spec = {
        "schema_version": policy.schema_version,
        "policy_version": policy.policy_version,
        "protocol_version": fd.PROTOCOL_VERSION,
        "dataset_contract_version": fd.DATASET_CONTRACT_VERSION,
        "source_identity": state.binding.identity,
        "source_hashes": state.binding.receipt.source_hashes,
        "source_mode": state.binding.receipt.mode,
        "manifest_reference": source.manifest_reference,
        "scope": scope,
        "preservation_rules": "literal_roles_order_nulls_v1",
    }
    spec_id = representation_spec_id(spec)
    build = {
        "code_sha256": _code_digest(),
        "dependency_versions": fd._dependency_versions(),
        "serializer_version": policy.serializer_version,
    }
    rows = tuple(
        represent_closed(source, o, checked_at=checked_at, policy=policy)
        for o in requested
    )
    counts = {
        f.name: dict(
            sorted(Counter(getattr(r.dimensions, f.name) for r in rows).items())
        )
        for f in fields(NativeDimensions)
    }
    if any(sum(c.values()) != len(requested) for c in counts.values()):
        raise ValueError("native audit universe conservation failure")
    report = {
        "target_schema": policy.schema_version,
        "policy": policy.policy_version,
        "schema_version": policy.schema_version,
        "policy_version": policy.policy_version,
        "serializer_version": policy.serializer_version,
        "source_identity": state.binding.identity,
        "source_receipt_sha256": state.binding.receipt.sha256,
        "source_authentication": state.binding.receipt.mode,
        "manifest_reference": source.manifest_reference,
        "scope": scope,
        "representation_spec_id": spec_id,
        "representation_build_id": representation_build_id(spec_id, **build),
        "build": build,
        "dimension_counts": counts,
        "rows": rows,
        "research_only": True,
        "execution_ready": False,
        "point_in_time_verified": False,
        "decision_eligible": False,
        "anomaly_evidence_verified": False,
        "limitations": LIMITATIONS,
    }
    digest = _digest(report)
    report["payload_sha256"] = digest
    result = NativeAudit(ha._freeze(_plain(report)), canonical_payload(report), digest)
    build_id = report["representation_build_id"]
    if build_id in _BUILD_PAYLOADS and _BUILD_PAYLOADS[build_id] != digest:
        raise ValueError(
            "conflicting payload bytes under immutable representation build"
        )
    _BUILD_PAYLOADS[build_id] = digest
    return result
