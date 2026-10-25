"""Invented pinned files exercise Stage D authority without historical execution."""

from __future__ import annotations

import copy
import hashlib
import json
import pickle
from dataclasses import replace
from pathlib import Path

import pytest
from test_historical_adapter import AS_OF, HOUR
from test_historical_adapter import source_frames as _source_frames

from quant.features import engine
from quant.research import forecast_dataset as fd
from quant.research import historical_adapter as ha
from quant.research import historical_authority as authority
from quant.research import historical_representation as native
from quant.research import historical_scoring_contract as contract
from quant.research import model_evaluation, ridge_regression, statistical_baselines


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def source_frames():
    return _source_frames.__wrapped__()


@pytest.fixture
def pinned_files(source_frames, tmp_path, monkeypatch):
    """Publish invented fixture files before installing any read-only guards."""
    silver, _, _, manifest, _ = source_frames
    silver_bytes = fd._parquet_bytes(silver)
    gold = engine.calculate_features(
        silver,
        manifest,
        analysis_as_of=AS_OF,
        generated_at=AS_OF + 2 * HOUR,
        source_snapshot_sha256=_sha(silver_bytes),
    )
    gold_bytes = fd._parquet_bytes(gold)
    ledger = fd.build_origin_ledger(
        silver,
        gold,
        manifest,
        analysis_as_of=AS_OF,
        silver_sha256=_sha(silver_bytes),
        gold_sha256=_sha(gold_bytes),
    )
    directory = fd.publish_ledger(
        ledger,
        root=tmp_path / "invented_publication",
        silver_rows=silver.height,
        silver_sha256=_sha(silver_bytes),
        gold_sha256=_sha(gold_bytes),
        manifest_sha256=manifest.sha256,
        code_revision=fd._code_revision(),
        dependency_versions={"python": "synthetic", "polars": "synthetic"},
    )
    for relative, data in (
        (ha.SILVER_PATH, silver_bytes),
        (ha.GOLD_PATH, gold_bytes),
        (ha.MANIFEST_PATH, manifest.to_bytes()),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name, value in (
        ("SILVER_SHA256", _sha(silver_bytes)),
        ("GOLD_SHA256", _sha(gold_bytes)),
        ("MANIFEST_SHA256", manifest.sha256),
        ("ANALYSIS_AS_OF", AS_OF),
    ):
        monkeypatch.setattr(fd, name, value)
    monkeypatch.setattr(contract, "ANALYSIS_AS_OF", AS_OF)
    monkeypatch.setattr(ha, "SPEC_ID", directory.parent.name)
    monkeypatch.setattr(ha, "BUILD_ID", directory.name)
    monkeypatch.setattr(ha, "ORIGIN_DIRECTORY", str(directory.relative_to(tmp_path)))
    monkeypatch.setattr(
        ha,
        "ARTIFACT_HASHES",
        {p.name: _sha(p.read_bytes()) for p in directory.iterdir()},
    )
    return tmp_path


@pytest.fixture
def context(pinned_files):
    return authority.open_verified_native_source(pinned_files)


def _scope(context, **changes):
    provenance = authority.source_provenance(context)
    values = dict(
        provenance=provenance,
        period_id="training_history",
        start=contract.PERIODS["training_history"][0],
        end_exclusive=contract.PERIODS["training_history"][1],
        analysis_as_of=AS_OF,
        intended_use=contract.INTENDED_USES["training_history"],
        origins=authority.evaluation_origins(context, "training_history"),
        model_ids=("zero_return",),
        sample_policies=("a_primary",),
    )
    values.update(changes)
    return contract.HistoricalScopeSpec(**values)


def _issue(context, *, index=0, scope=None, checked_at=AS_OF):
    scope = scope or _scope(context)
    return authority.issue_closed_outcome(
        context, scope, scope.origins[index], checked_at=checked_at
    )


def _native_source(context):
    return authority._SOURCES[context].source


def test_pinned_reader_authenticates_invented_bytes_and_preserves_full_universe(
    context,
):
    provenance = authority.source_provenance(context)
    assert provenance.source_mode == "authenticated_pinned_history"
    assert provenance.manifest_raw_sha256 == provenance.manifest_canonical_sha256
    # The data record is still incapable of granting authority by itself.
    assert not provenance.historical_source_authenticated
    origins = authority.evaluation_origins(context, "training_history")
    assert len(origins) == 7
    assert tuple(o.source_row_index for o in origins) == tuple(range(7))
    assert origins[4].origin - origins[3].origin == HOUR  # Missing candle retained.
    authority.validate_historical_scope(context, _scope(context))


@pytest.mark.parametrize(
    "relative",
    [
        "origin_ledger.parquet",
        "dataset_validation.json",
        "provenance.json",
        "provenance.sha256",
        "silver",
        "gold",
        "manifest",
    ],
)
def test_tampered_source_bytes_fail_authentication(pinned_files, relative):
    path = (
        pinned_files
        / {
            "silver": ha.SILVER_PATH,
            "gold": ha.GOLD_PATH,
            "manifest": ha.MANIFEST_PATH,
        }[relative]
        if relative in {"silver", "gold", "manifest"}
        else pinned_files / ha.ORIGIN_DIRECTORY / relative
    )
    path.write_bytes(path.read_bytes() + b"!")
    with pytest.raises(ValueError):
        authority.open_verified_native_source(pinned_files)


def test_incorrect_supplied_digest_cannot_authenticate_bytes(pinned_files, monkeypatch):
    hashes = dict(ha.ARTIFACT_HASHES)
    hashes["origin_ledger.parquet"] = "f" * 64
    monkeypatch.setattr(ha, "ARTIFACT_HASHES", hashes)
    with pytest.raises(ValueError):
        authority.open_verified_native_source(pinned_files)


@pytest.mark.parametrize("defect", ["missing", "extra", "duplicate", "reordered"])
def test_scope_requires_exact_source_identity_set(context, defect):
    origins = authority.evaluation_origins(context, "training_history")
    if defect == "missing":
        altered = origins[1:]
    elif defect == "extra":
        altered = (*origins, replace(origins[-1], source_row_index=100))
    elif defect == "duplicate":
        altered = (origins[0], *origins)
    else:
        altered = tuple(reversed(origins))
    with pytest.raises(ValueError):
        scope = _scope(context, origins=altered)
        authority.validate_historical_scope(context, scope)


def test_scope_source_substitution_is_rejected(context):
    provenance = replace(authority.source_provenance(context), dataset_spec_id="f" * 64)
    origins = tuple(
        replace(origin, provenance=provenance)
        for origin in authority.evaluation_origins(context, "training_history")
    )
    with pytest.raises(ValueError):
        authority.validate_historical_scope(
            context, _scope(context, provenance=provenance, origins=origins)
        )


@pytest.mark.parametrize("operation", ["scope", "issue", "inspect"])
def test_wrong_policy_fails_closed(context, operation):
    scope = _scope(context)
    with pytest.raises(ValueError):
        if operation == "scope":
            authority.validate_historical_scope(context, scope, policy_version="wrong")
        elif operation == "issue":
            authority.issue_closed_outcome(
                context,
                scope,
                scope.origins[0],
                checked_at=AS_OF,
                policy_version="wrong",
            )
        else:
            cap = _issue(context, scope=scope)
            authority.inspect_closed_outcome(
                context, scope, cap, policy_version="wrong"
            )


def test_exact_theoretical_closure_allows_minimal_read_only_view(context):
    scope = _scope(context)
    origin = scope.origins[0]
    cap = _issue(context, scope=scope, checked_at=origin.target_theoretical_close_at)
    view = authority.inspect_closed_outcome(context, scope, cap)
    assert view.origin_ref == origin
    assert view.checked_at == origin.target_theoretical_close_at
    assert view.closure == "closed"
    assert not view.historical_outcome_authenticated
    features = _native_source(context).binding.records[0].features
    assert features.available_at is None
    assert features.decision_eligible is False


def test_preclosure_never_reads_future_outcome(context):
    scope = _scope(context)
    source = _native_source(context)
    row = source.binding.records[0]
    original = row.outcome

    class FutureOutcome:
        def __getattribute__(self, name):
            raise AssertionError("future target or outcome flag inspected")

    object.__setattr__(row, "outcome", FutureOutcome())
    try:
        with pytest.raises(ValueError):
            _issue(context, scope=scope, checked_at=scope.origins[0].origin)
    finally:
        object.__setattr__(row, "outcome", original)


def test_unbound_and_audit_only_origins_cannot_receive_capability(context):
    scope = _scope(context)
    last = scope.origins[-1]
    outside = contract.PERIODS["test"][1]
    audit_only = replace(
        last,
        origin=outside,
        feature_open_t=outside - HOUR,
        target_theoretical_close_at=outside + HOUR,
        period_id="outside_approved_evaluation_window",
    )
    for origin in (replace(last, source_row_index=100), audit_only):
        with pytest.raises(ValueError):
            authority.issue_closed_outcome(
                context, scope, origin, checked_at=outside + 2 * HOUR
            )


def test_invalid_null_target_with_reasons_is_preserved(context):
    scope = _scope(context)
    cap = _issue(context, index=3, scope=scope)
    view = authority.inspect_closed_outcome(context, scope, cap)
    assert view.target is None
    assert view.target_valid is False
    assert view.original_invalid_reasons


def test_native_unknown_candle_order_and_multiplicity_are_preserved(context):
    scope = _scope(context)
    cap = _issue(context, index=3, scope=scope)
    view = authority.inspect_closed_outcome(context, scope, cap)
    represented = native.represent_closed(
        _native_source(context), scope.origins[3].origin, checked_at=AS_OF
    )
    assert represented.dimensions.legacy_4a_compatibility == "blocked"
    all_view = (
        *view.target_endpoint_occurrences,
        *view.feature_window_occurrences,
        *view.unresolved_occurrences,
    )
    assert all_view == represented.envelope.occurrences
    tokens = tuple(token for o in all_view for token in o.raw["affected_fields"])
    assert "candle" in tokens and "unknown" in tokens
    assert len(all_view) > len({contract.payload_sha256(o.raw) for o in all_view})
    assert view.anomaly_evidence_status == "recorded_references_unverified"


@pytest.mark.parametrize("defect", ["missing", "unresolved", "linkage", "blocked"])
def test_unavailable_or_unresolved_native_outcome_cannot_mint_capability(
    context, monkeypatch, defect
):
    real = native.represent_closed

    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        if defect == "missing":
            return replace(result, envelope=None)
        if defect == "linkage":
            occurrence = replace(
                result.envelope.occurrences[0],
                linkage="missing",
                manifest_record_index=None,
                manifest_record_sha256=None,
                manifest_record=None,
            )
            return replace(
                result,
                envelope=replace(
                    result.envelope,
                    occurrences=(occurrence, *result.envelope.occurrences[1:]),
                ),
            )
        dimensions = replace(
            result.dimensions,
            **(
                {"association_resolution": "unresolved"}
                if defect == "unresolved"
                else {"native_representability": "blocked"}
                if defect == "blocked"
                else {"evidence_completeness": "unresolved_linkage"}
            ),
        )
        return replace(result, dimensions=dimensions)

    monkeypatch.setattr(native, "represent_closed", changed)
    with pytest.raises(ValueError):
        _issue(context, index=2)


@pytest.mark.parametrize("kind", ["context", "capability"])
@pytest.mark.parametrize(
    "operation", ["construct", "copy", "deepcopy", "pickle", "replace"]
)
def test_authority_cannot_be_constructed_copied_or_deserialized(
    context, kind, operation
):
    value = context if kind == "context" else _issue(context)
    with pytest.raises((TypeError, ValueError, AttributeError)):
        if operation == "construct":
            type(value)()
        elif operation == "copy":
            copy.copy(value)
        elif operation == "deepcopy":
            copy.deepcopy(value)
        elif operation == "replace":
            replace(value)
        else:
            pickle.loads(pickle.dumps(value))


def test_descriptor_cannot_be_used_as_outcome_authority(context):
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    descriptor = authority.describe_closed_outcome(cap)
    encoded = contract.canonical_json(descriptor)
    decoded = json.loads(encoded)
    assert b"untrusted_closed_outcome_descriptor" in encoded
    assert b"nonce" not in encoded
    assert b"target_valid" not in encoded
    for forged in (descriptor, decoded):
        with pytest.raises(ValueError):
            authority.inspect_closed_outcome(context, scope, forged)


def test_equal_bytes_in_another_context_do_not_transfer_capability(
    context, pinned_files
):
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    other = authority.open_verified_native_source(pinned_files)
    with pytest.raises(ValueError):
        authority.inspect_closed_outcome(other, _scope(other), cap)


def test_capability_is_bound_to_exact_scope_specification(context):
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    different = _scope(context, sample_policies=("a_primary", "a_sensitivity"))
    with pytest.raises(ValueError):
        authority.inspect_closed_outcome(context, different, cap)


@pytest.mark.parametrize(
    "field,value",
    [("outcome_view_sha256", "f" * 64), ("native_result_sha256", "f" * 64)],
)
def test_inplace_capability_digest_tampering_is_rejected(context, field, value):
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    original = getattr(cap, field)
    object.__setattr__(cap, field, value)
    try:
        with pytest.raises(ValueError):
            authority.inspect_closed_outcome(context, scope, cap)
    finally:
        object.__setattr__(cap, field, original)


def test_source_revocation_invalidates_existing_capabilities(context):
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    authority.invalidate_source(context)
    with pytest.raises(ValueError):
        authority.source_provenance(context)
    with pytest.raises(ValueError):
        authority.inspect_closed_outcome(context, scope, cap)


@pytest.mark.parametrize("field", ["raw_sha256", "canonical_sha256"])
def test_manifest_reference_tampering_revokes_outcome_access(context, field):
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    reference = _native_source(context).manifest_reference
    original = getattr(reference, field)
    object.__setattr__(reference, field, "f" * 64)
    try:
        with pytest.raises(ValueError):
            authority.inspect_closed_outcome(context, scope, cap)
    finally:
        object.__setattr__(reference, field, original)


def test_receipt_flag_tampering_cannot_authenticate_source(context):
    receipt = _native_source(context).binding.receipt
    object.__setattr__(receipt, "authenticated_source_bytes", False)
    try:
        with pytest.raises(ValueError):
            authority.source_provenance(context)
    finally:
        object.__setattr__(receipt, "authenticated_source_bytes", True)


def test_unregistered_objects_with_copied_fields_do_not_resolve(context):
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    forged = object.__new__(type(cap))
    for name in cap.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(cap, name))
    with pytest.raises(ValueError):
        authority.inspect_closed_outcome(context, scope, forged)
    with pytest.raises(ValueError):
        authority.source_provenance(object.__new__(type(context)))


def test_synthetic_native_context_cannot_gain_pinned_authority(
    source_frames, monkeypatch, tmp_path
):
    silver, gold, ledger, manifest, identity = source_frames
    adapter = ha.audit_frames(silver, gold, ledger, manifest, identity=identity).adapter
    synthetic = native.bind_synthetic_representation(adapter)
    monkeypatch.setattr(
        native, "verify_pinned_representation_source", lambda root: synthetic
    )
    with pytest.raises(ValueError):
        authority.open_verified_native_source(tmp_path)


def test_authority_does_not_write_or_execute_models(context, pinned_files, monkeypatch):
    before = {
        str(p): _sha(p.read_bytes()) for p in pinned_files.rglob("*") if p.is_file()
    }

    def forbidden(*args, **kwargs):
        pytest.fail("Stage D attempted a write or historical execution")

    for module, name in (
        (Path, "write_bytes"),
        (Path, "write_text"),
        (fd, "publish_ledger"),
        (fd, "build_origin_ledger"),
        (engine, "calculate_features"),
        (statistical_baselines, "fit_ar"),
        (ridge_regression, "fit_ridge"),
        (model_evaluation, "run_synthetic"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    scope = _scope(context)
    cap = _issue(context, scope=scope)
    authority.inspect_closed_outcome(context, scope, cap)
    assert before == {
        str(p): _sha(p.read_bytes()) for p in pinned_files.rglob("*") if p.is_file()
    }
    for prohibited in (
        "score_historical",
        "complete_historical_accounting",
        "classify_native_score",
        "reconcile_native_accounting",
        "run_historical",
    ):
        assert not hasattr(authority, prohibited)
    assert contract.public_authority_issuers() == ()
