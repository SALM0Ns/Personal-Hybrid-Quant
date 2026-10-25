"""Process-local, read-only authority to inspect theoretically closed outcomes.

This is an audit-side boundary, not a model/producer/execution authority. It
reuses the pinned 5A/5C/5E readers. Private registries protect against accidental
substitution through normal APIs, not hostile Python code in the same process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from weakref import WeakKeyDictionary

from quant.research import evaluation_protocol as protocol
from quant.research import historical_projection as projection
from quant.research import historical_representation as native
from quant.research import historical_scoring_contract as contract

POLICY_VERSION = contract.POLICY_VERSION


class _NonTransferable:
    def __new__(cls, *args, **kwargs):
        raise TypeError("authority requires the verified factory")

    def __copy__(self):
        raise TypeError("process-local authority cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("process-local authority cannot be copied")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local authority cannot be serialized")


@dataclass(frozen=True, eq=False, init=False)
class HistoricalSourceContext(_NonTransferable):
    """Opaque verified-read context; never contains public outcome accessors."""


@dataclass(frozen=True, eq=False, init=False)
class ClosedHistoricalOutcomeRef(_NonTransferable):
    """Only the registered object can resolve its particular closed outcome."""

    origin_ref: contract.HistoricalOriginRef
    checked_at: datetime
    theoretical_close_at: datetime
    native_result_sha256: str
    outcome_view_sha256: str
    capability_nonce: object = field(repr=False)


@dataclass(frozen=True)
class _SourceState:
    source: native.NativeSource
    provenance: contract.HistoricalProvenanceRef
    provenance_sha256: str
    origins: tuple[contract.HistoricalOriginRef, ...]
    by_origin: dict[datetime, contract.HistoricalOriginRef]


@dataclass(frozen=True)
class _OutcomeState:
    context: HistoricalSourceContext
    scope: contract.HistoricalScopeSpec
    scoring_spec_id: str
    origin_ref: contract.HistoricalOriginRef
    checked_at: datetime
    theoretical_close_at: datetime
    native_result_sha256: str
    outcome_view_sha256: str
    nonce: object


_SOURCES: WeakKeyDictionary = WeakKeyDictionary()
_OUTCOMES: WeakKeyDictionary = WeakKeyDictionary()


def _policy(policy_version):
    if policy_version != POLICY_VERSION or type(policy_version) is not str:
        raise ValueError("unapproved historical authority policy")


def _source_state(context, policy_version=POLICY_VERSION):
    _policy(policy_version)
    if type(context) is not HistoricalSourceContext or context not in _SOURCES:
        raise ValueError("registered historical source context required")
    state = _SOURCES[context]
    native._state(state.source)
    receipt = state.source.binding.receipt
    if (
        receipt.mode != "authenticated_pinned_history"
        or receipt.authenticated_source_bytes is not True
        or contract.payload_sha256(state.provenance) != state.provenance_sha256
        or state.provenance.source_receipt_sha256 != receipt.sha256
    ):
        raise ValueError("historical source authority binding changed")
    contract.validate_provenance(state.provenance)
    return state


def open_verified_native_source(
    root: Path, *, policy_version: str = POLICY_VERSION
) -> HistoricalSourceContext:
    """Authenticate approved bytes read, not later disk state or publication.

    No caller digest, receipt, adapter or authenticated Boolean is accepted.
    Opening/reopening invokes the full existing pinned reader and native binder.
    """
    _policy(policy_version)
    source = native.verify_pinned_representation_source(Path(root))
    native._state(source)
    receipt = source.binding.receipt
    if (
        receipt.mode != "authenticated_pinned_history"
        or receipt.authenticated_source_bytes is not True
    ):
        raise ValueError("verified pinned historical source required")
    identity = source.binding.identity
    hashes = dict(receipt.source_hashes)
    provenance = contract.HistoricalProvenanceRef(
        dataset_spec_id=identity.dataset_spec_id,
        source_artifact_build_id=identity.artifact_build_id,
        silver_sha256=identity.silver_sha256,
        gold_sha256=identity.gold_sha256,
        origin_ledger_sha256=hashes["origin_ledger.parquet"],
        dataset_validation_sha256=hashes["dataset_validation.json"],
        provenance_json_sha256=hashes["provenance.json"],
        provenance_sidecar_sha256=hashes["provenance.sha256"],
        manifest_canonical_sha256=source.manifest_reference.canonical_sha256,
        manifest_raw_sha256=source.manifest_reference.raw_sha256,
        manifest_version=identity.manifest_version,
        feature_version=identity.feature_version,
        feature_order=tuple(contract.FEATURES),
        source_receipt_sha256=receipt.sha256,
        source_mode="authenticated_pinned_history",
    )
    # Identity-only traversal: no target, validity or anomaly fields are read.
    origins = tuple(
        contract.HistoricalOriginRef(
            provenance=provenance,
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            source_identifier=row.source_identifier,
            source_row_index=row.source_row_index,
            origin=row.origin,
            feature_open_t=row.origin - protocol.HOUR,
            target_theoretical_close_at=row.origin + protocol.HOUR,
            period_id=row.period,
        )
        for row in source.binding.records
    )
    if len({ref.origin for ref in origins}) != len(origins):
        raise ValueError("duplicate source-ledger origin")
    context = object.__new__(HistoricalSourceContext)
    _SOURCES[context] = _SourceState(
        source,
        provenance,
        contract.payload_sha256(provenance),
        origins,
        {ref.origin: ref for ref in origins},
    )
    return context


def source_provenance(context: HistoricalSourceContext):
    """Data-only descriptor; possession of this record confers no authority."""
    return _source_state(context).provenance


def evaluation_origins(
    context: HistoricalSourceContext, period_id: str
) -> tuple[contract.HistoricalOriginRef, ...]:
    """Exact pinned-ledger identities, including invalid and missing-hour rows.

    The audit-only period can be inspected separately but never authorized for
    outcome access. No hourly range or target/quality filtering is substituted.
    """
    state = _source_state(context)
    if period_id not in (*contract.PERIODS, "outside_approved_evaluation_window"):
        raise ValueError("unknown source-ledger period")
    return tuple(ref for ref in state.origins if ref.period_id == period_id)


def validate_historical_scope(
    context: HistoricalSourceContext,
    scope: contract.HistoricalScopeSpec,
    *,
    policy_version: str = POLICY_VERSION,
) -> None:
    """Compare the full scope to verified ledger identities, without execution."""
    state = _source_state(context, policy_version)
    if type(scope) is not contract.HistoricalScopeSpec:
        raise ValueError("typed historical scope required")
    if scope.provenance != state.provenance:
        raise ValueError("scope/source provenance mismatch")
    if any(
        getattr(scope, name) is None
        for name in (
            "origin_set_sha256",
            "source_origin_identity_set_sha256",
            "scoring_spec_id",
        )
    ):
        raise ValueError("complete scope identities required")
    contract.validate_scope(scope, source_ledger_origins=state.origins)


def _closed_view(state, origin_ref, checked_at):
    # Caller has already established identity, split and closure. The native
    # reader repeats its own clock guard before full-row hashing/target access.
    result = native.represent_closed(
        state.source, origin_ref.origin, checked_at=checked_at
    )
    dimensions = result.dimensions
    if (
        dimensions.source_authentication != "authenticated_pinned_history"
        or dimensions.native_representability != "represented"
        or dimensions.association_resolution != "resolved"
        or dimensions.temporal_closure != "closed"
        or result.envelope is None
        or dimensions.evidence_completeness
        != (
            "recorded_references_unverified"
            if result.envelope.occurrences
            else "no_occurrences"
        )
        or any(o.linkage != "matched" for o in result.envelope.occurrences)
    ):
        raise ValueError("closed native outcome representation/linkage required")
    envelope = result.envelope
    row = envelope.record
    if row.outcome is None:
        raise ValueError("bound historical outcome required")
    expected = projection.source_ref(state.source.binding, origin_ref.origin)
    if result.source_ref != expected:
        raise ValueError("native result source identity mismatch")
    collections = {
        name: tuple(o for o in envelope.occurrences if o.collection == name)
        for name in native.COLLECTIONS
    }
    outcome = row.outcome
    view = contract.HistoricalOutcomeView(
        origin_ref=origin_ref,
        target=outcome.target,
        target_valid=outcome.target_valid,
        original_invalid_reasons=outcome.invalid_reasons,
        ordered_invalid_reasons=contract.ordered_reasons(
            outcome.invalid_reasons, contract.TARGET_REASON_PRIORITY
        ),
        target_primary_null_reason=outcome.target_primary_null_reason,
        target_manifest_anomaly=outcome.target_manifest_anomaly,
        target_value_sensitive=row.source_values.get("target_value_sensitive"),
        target_endpoint_occurrences=collections["target_endpoint_anomalies"],
        feature_window_occurrences=collections["feature_window_anomalies"],
        unresolved_occurrences=collections["unresolved_anomalies"],
        anomaly_evidence_status=(
            "recorded_references_unverified"
            if envelope.occurrences
            else "no_occurrences"
        ),
        source_authentication="authenticated_pinned_history",
        native_schema_version=native.SCHEMA_VERSION,
        native_policy_version=native.POLICY_VERSION,
        theoretical_close_at=origin_ref.target_theoretical_close_at,
        checked_at=checked_at,
        closure="closed",
        native_envelope_sha256=native._digest(envelope),
    )
    return view, native._digest(result)


def issue_closed_outcome(
    context: HistoricalSourceContext,
    scope: contract.HistoricalScopeSpec,
    origin_ref: contract.HistoricalOriginRef,
    *,
    checked_at: datetime,
    policy_version: str = POLICY_VERSION,
) -> ClosedHistoricalOutcomeRef:
    """Issue inspection authority only after membership and theoretical closure.

    A failed boundary raises without returning target values/flags/diagnostics.
    This grants neither producer authority nor historical scoring authority.
    """
    state = _source_state(context, policy_version)
    validate_historical_scope(context, scope, policy_version=policy_version)
    contract.validate_origin(origin_ref)
    if (
        origin_ref.period_id == "outside_approved_evaluation_window"
        or state.by_origin.get(origin_ref.origin) != origin_ref
        or origin_ref not in scope.origins
    ):
        raise ValueError("exact in-scope evaluation origin required")
    protocol.validate_hour(checked_at)
    if checked_at < origin_ref.target_theoretical_close_at:
        raise ValueError("historical outcome is not theoretically closed")
    view, result_digest = _closed_view(state, origin_ref, checked_at)
    capability = object.__new__(ClosedHistoricalOutcomeRef)
    nonce = object()
    values = {
        "origin_ref": origin_ref,
        "checked_at": checked_at,
        "theoretical_close_at": origin_ref.target_theoretical_close_at,
        "native_result_sha256": result_digest,
        "outcome_view_sha256": contract.payload_sha256(view),
        "capability_nonce": nonce,
    }
    for name, value in values.items():
        object.__setattr__(capability, name, value)
    _OUTCOMES[capability] = _OutcomeState(
        context,
        scope,
        scope.scoring_spec_id,
        origin_ref,
        checked_at,
        origin_ref.target_theoretical_close_at,
        result_digest,
        values["outcome_view_sha256"],
        nonce,
    )
    return capability


def _outcome_state(capability):
    if (
        type(capability) is not ClosedHistoricalOutcomeRef
        or capability not in _OUTCOMES
    ):
        raise ValueError("registered closed-outcome capability required")
    state = _OUTCOMES[capability]
    _source_state(state.context)
    if (
        capability.capability_nonce is not state.nonce
        or capability.origin_ref != state.origin_ref
        or capability.checked_at != state.checked_at
        or capability.theoretical_close_at != state.theoretical_close_at
        or capability.native_result_sha256 != state.native_result_sha256
        or capability.outcome_view_sha256 != state.outcome_view_sha256
    ):
        raise ValueError("closed-outcome capability binding changed")
    return state


def inspect_closed_outcome(
    context: HistoricalSourceContext,
    scope: contract.HistoricalScopeSpec,
    capability: ClosedHistoricalOutcomeRef,
    *,
    policy_version: str = POLICY_VERSION,
) -> contract.HistoricalOutcomeView:
    """Explicit read-only post-closure view; the returned data grants no authority."""
    state = _outcome_state(capability)
    source_state = _source_state(context, policy_version)
    if state.context is not context or state.scope is not scope:
        raise ValueError("closed-outcome context/scope mismatch")
    validate_historical_scope(context, scope, policy_version=policy_version)
    if scope.scoring_spec_id != state.scoring_spec_id:
        raise ValueError("closed-outcome specification mismatch")
    view, result_digest = _closed_view(source_state, state.origin_ref, state.checked_at)
    if (
        result_digest != state.native_result_sha256
        or contract.payload_sha256(view) != state.outcome_view_sha256
    ):
        raise ValueError("bound closed-outcome payload changed")
    return view


def describe_closed_outcome(capability: ClosedHistoricalOutcomeRef):
    """Safe data-only descriptor, never a deserialization/authority interface."""
    _outcome_state(capability)
    return MappingProxyType(
        {
            "descriptor_type": "untrusted_closed_outcome_descriptor",
            **{
                name: getattr(capability, name)
                for name in (
                    "origin_ref",
                    "checked_at",
                    "theoretical_close_at",
                    "native_result_sha256",
                    "outcome_view_sha256",
                )
            },
        }
    )


def invalidate_source(context: HistoricalSourceContext) -> None:
    """Revoke this context and all dependent outcome capabilities in this process."""
    _source_state(context)
    del _SOURCES[context]
