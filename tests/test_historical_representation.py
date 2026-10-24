"""Synthetic-only tests for native lossless audit representation, not scoring."""

from __future__ import annotations

import builtins
import copy
import hashlib
import json
import math
import socket
from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest
from test_historical_projection import (
    AS_OF,
    HOUR,
    START,
    _edited,
    _make_adapter,
)
from test_historical_projection import (
    _annotation as _base_annotation,
)

from quant.features import engine
from quant.features.manifest import AnomalyManifest
from quant.research import evaluation_reporting as reporting
from quant.research import forecast_accounting as accounting
from quant.research import forecast_dataset as fd
from quant.research import historical_adapter as ha
from quant.research import historical_projection as hp
from quant.research import historical_representation as native
from quant.research import model_evaluation, ridge_regression, statistical_baselines


def _annotation(hour, fields=("close",), kind="source_discrepancy"):
    original = _base_annotation(hour, fields, kind)
    return replace(
        original,
        source_evidence=tuple(
            replace(item, observed_at=START + 8 * HOUR)
            for item in original.source_evidence
        ),
    )


@pytest.fixture(scope="module")
def clean_adapter():
    return _make_adapter(count=8)


@pytest.fixture
def clean_source(clean_adapter):
    return native.bind_synthetic_representation(clean_adapter)


def _source(*, field="close", kind="source_discrepancy", missing=()):
    anomaly = _annotation(2, (field,), kind)
    return native.bind_synthetic_representation(
        _make_adapter(count=8, missing=missing, anomalies=(anomaly,))
    )


def _result(source, index=2, checked_at=AS_OF):
    return native.represent_closed(
        source, source.binding.records[index].origin, checked_at=checked_at
    )


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _changed_endpoint(adapter, index=2, *, changes=None, remove=()):
    record = adapter.records[index]
    annotation = record.outcome.target_endpoint_anomalies[0]
    raw = dict(annotation.raw)
    raw.update(changes or {})
    for key in remove:
        raw.pop(key)
    annotation = replace(annotation, raw=ha._freeze(raw))
    endpoints = (annotation, *record.outcome.target_endpoint_anomalies[1:])
    return _edited(
        adapter,
        index,
        outcome_changes={"target_endpoint_anomalies": endpoints},
        raw={"target_endpoint_anomalies": tuple(a.raw for a in endpoints)},
    )


def test_versions_and_synthetic_source_remain_explicit(clean_source):
    assert native.SCHEMA_VERSION == "pqta-historical-anomaly-representation-v1"
    assert native.POLICY_VERSION == "pqta-003d-5d-representation-v1"
    assert native.SERIALIZER_VERSION == "pqta-003d-5e-canonical-v1"
    result = _result(clean_source)
    assert result.dimensions.source_authentication == "synthetic_fixture"
    assert result.dimensions.native_representability == "represented"
    assert result.dimensions.evidence_completeness == "no_occurrences"
    assert result.envelope.record is clean_source.binding.records[2]


@pytest.mark.parametrize(
    "field", ["open", "high", "low", "close", "volume", "candle", "unknown"]
)
def test_all_seven_literal_tokens_preserved_without_expansion(field):
    kind = (
        "missing_hour"
        if field == "candle"
        else "shortened_close"
        if field == "unknown"
        else "source_discrepancy"
    )
    source = _source(field=field, kind=kind, missing=(2,) if field == "candle" else ())
    result = _result(source)
    assert result.dimensions.native_representability == "represented", result.findings
    assert result.envelope is not None
    assert result.envelope.occurrences
    for occurrence in result.envelope.occurrences:
        assert occurrence.source_ref == result.source_ref
        assert occurrence.source_ref.source_row_index == 2
        assert occurrence.source_ref.origin == source.binding.records[2].origin
        assert occurrence.raw["affected_fields"] == (field,)
        assert occurrence.linkage == "matched"
        assert occurrence.manifest_record["affected_fields"] == (field,)
    if field in ("candle", "unknown"):
        assert result.dimensions.legacy_4a_compatibility == "blocked"
    else:
        assert result.dimensions.legacy_4a_compatibility == "compatible"
    assert result.dimensions.evidence_completeness == "recorded_references_unverified"


@pytest.mark.parametrize(
    "kind,fields_value",
    [
        ("missing_hour", ("close",)),
        ("source_discrepancy", ("candle",)),
        ("shortened_close", ("candle",)),
        ("source_discrepancy", ()),
        ("source_discrepancy", ("close", "close")),
        ("source_discrepancy", (None,)),
        ("source_discrepancy", ("",)),
    ],
)
def test_known_invalid_type_token_combinations_fail(kind, fields_value):
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    changed = _changed_endpoint(
        adapter, changes={"anomaly_type": kind, "affected_fields": fields_value}
    )
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "failed"


@pytest.mark.parametrize(
    "changes",
    [{"anomaly_type": "future_anomaly"}, {"affected_fields": ("future_field",)}],
)
def test_future_vocabulary_remains_opaque_and_blocked(changes):
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    changed = _changed_endpoint(adapter, changes=changes)
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "blocked"
    assert result.envelope is not None
    occurrence = result.envelope.occurrences[0]
    assert occurrence.linkage == "unknown_vocabulary"
    for key, value in changes.items():
        assert occurrence.raw[key] == value


def test_endpoint_window_unresolved_roles_are_distinct_and_not_inferred():
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    record = adapter.records[2]
    unresolved = replace(
        record.outcome.target_endpoint_anomalies[0],
        association="unresolved",
        source_column="unattributed_original",
    )
    changed = _edited(
        adapter, 2, outcome_changes={"unresolved_anomalies": (unresolved,)}
    )
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "represented"
    assert result.dimensions.association_resolution == "unresolved"
    assert result.envelope is not None
    assert tuple(o.collection for o in result.envelope.occurrences) == (
        "target_endpoint_anomalies",
        "feature_window_anomalies",
        "unresolved_anomalies",
    )
    assert tuple(o.association for o in result.envelope.occurrences) == (
        "target_endpoint",
        "feature_window",
        "unresolved",
    )
    assert result.envelope.occurrences[-1].source_column == "unattributed_original"
    assert result.envelope.occurrences[-1].raw == unresolved.raw


def test_duplicate_occurrences_keep_collection_order_and_original_positions():
    adapter = _make_adapter(
        count=8, anomalies=(_annotation(1), _annotation(2, ("volume",)))
    )
    record = adapter.records[2]
    first, second = record.outcome.feature_window_anomalies
    window = (second, first, second)
    changed = _edited(
        adapter,
        2,
        feature_changes={"anomalies": window},
        outcome_changes={"feature_window_anomalies": window},
        raw={"involved_anomalies": tuple(a.raw for a in window)},
    )
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "represented", result.findings
    occurrences = tuple(
        o
        for o in result.envelope.occurrences
        if o.collection == "feature_window_anomalies"
    )
    assert tuple(o.position for o in occurrences) == (0, 1, 2)
    assert tuple(o.raw for o in occurrences) == tuple(a.raw for a in window)
    assert (
        occurrences[0].manifest_record_sha256 == occurrences[2].manifest_record_sha256
    )


def test_manifest_link_retains_original_raw_timestamp_text_and_record_digest():
    anomaly = _annotation(2)
    adapter = _make_adapter(count=8, anomalies=(anomaly,))
    manifest = AnomalyManifest("projection-synthetic-v1", None, (anomaly,))
    raw_manifest = manifest.to_dict()
    raw_manifest["records"][0]["timestamp"] = "2025-01-01T02:00:00Z"
    raw_bytes = json.dumps(raw_manifest, ensure_ascii=False, indent=2).encode()
    source = native.bind_synthetic_representation(adapter, manifest_bytes=raw_bytes)
    result = _result(source)
    occurrence = result.envelope.occurrences[0]
    assert occurrence.manifest_record_index == 0
    assert occurrence.manifest_record["timestamp"] == "2025-01-01T02:00:00Z"
    assert (
        occurrence.manifest_record_sha256
        == hashlib.sha256(
            native.canonical_payload(raw_manifest["records"][0])
        ).hexdigest()
    )
    assert source.manifest_reference.raw_sha256 == hashlib.sha256(raw_bytes).hexdigest()
    assert source.manifest_reference.canonical_sha256 == manifest.sha256


@pytest.mark.parametrize(
    "removed", ["severity", "review_status", "evidence_references", "affected_fields"]
)
def test_missing_reduced_linkage_information_blocks_without_enrichment(removed):
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    changed = _changed_endpoint(adapter, remove=(removed,))
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "blocked"
    assert result.dimensions.evidence_completeness == "unresolved_linkage"
    assert result.envelope is not None
    assert removed not in result.envelope.occurrences[0].raw
    assert result.envelope.occurrences[0].manifest_record is None


def test_absent_manifest_key_blocks_without_positional_fallback():
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    changed = _changed_endpoint(adapter, changes={"timestamp": START + 3 * HOUR})
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "blocked"
    assert result.envelope.occurrences[0].linkage == "missing"
    assert result.envelope.occurrences[0].manifest_record_index is None


@pytest.mark.parametrize(
    "changes",
    [
        {"severity": "invented"},
        {"review_status": "resolved"},
        {"evidence_references": ("data/verification/different.json",)},
        {"affected_fields": ("high",)},
    ],
)
def test_contradictory_known_manifest_link_is_integrity_failure(changes):
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    changed = _changed_endpoint(adapter, changes=changes)
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "failed"
    assert result.envelope is not None
    assert result.envelope.occurrences[0].linkage == "contradictory"


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate_key",
        "duplicate_identity",
        "nonfinite",
        "invalid_schema",
        "wrong_manifest",
    ],
)
def test_strict_manifest_parser_rejects_ambiguity_and_invalid_evidence(
    clean_adapter, defect
):
    manifest = clean_adapter.manifest.to_dict()
    if defect == "duplicate_key":
        data = b'{"manifest_version":"a","manifest_version":"b"}'
    elif defect == "nonfinite":
        data = b'{"manifest_version":NaN}'
    elif defect == "invalid_schema":
        data = b'{"manifest_version":"projection-synthetic-v1"}'
    else:
        anomaly = _annotation(2)
        manifest = AnomalyManifest(
            "projection-synthetic-v1", None, (anomaly,)
        ).to_dict()
        if defect == "duplicate_identity":
            manifest["records"].append(dict(manifest["records"][0]))
        data = json.dumps(manifest).encode()
    with pytest.raises(ValueError):
        native.bind_synthetic_representation(clean_adapter, manifest_bytes=data)


@pytest.mark.parametrize(
    "operation", ["copy", "replace", "binding_substitution", "forged_receipt"]
)
def test_copied_or_substituted_context_cannot_authenticate(clean_source, operation):
    if operation == "copy":
        forged = copy.copy(clean_source)
    elif operation == "replace":
        forged = replace(clean_source)
    elif operation == "binding_substitution":
        forged = replace(
            clean_source, binding=hp.bind_synthetic(_make_adapter(count=8))
        )
    else:
        receipt = replace(clean_source.binding.receipt, authenticated_source_bytes=True)
        forged = replace(
            clean_source, binding=replace(clean_source.binding, receipt=receipt)
        )
    with pytest.raises(ValueError):
        _result(forged)


def test_inplace_manifest_reference_tampering_is_detected(clean_source):
    reference = clean_source.manifest_reference
    original = reference.raw_sha256
    object.__setattr__(reference, "raw_sha256", "f" * 64)
    try:
        with pytest.raises(ValueError):
            _result(clean_source)
    finally:
        object.__setattr__(reference, "raw_sha256", original)


def test_postclosure_source_record_tampering_fails_without_trusted_envelope(
    clean_source,
):
    record = clean_source.binding.records[2]
    original = record.outcome
    object.__setattr__(record, "outcome", replace(original, target=42.0))
    try:
        with pytest.raises(ValueError, match="bound native source row changed"):
            _result(clean_source)
    finally:
        object.__setattr__(record, "outcome", original)


def test_pinned_factory_cannot_promote_an_existing_synthetic_receipt(
    clean_source, monkeypatch, tmp_path
):
    monkeypatch.setattr(hp, "verify_pinned_source", lambda root: clean_source.binding)
    with pytest.raises(ValueError):
        native.verify_pinned_representation_source(tmp_path)
    assert clean_source.binding.receipt.mode == "synthetic_fixture"


def test_missing_pinned_source_fails_instead_of_accepting_asserted_identity(tmp_path):
    with pytest.raises(ValueError):
        native.verify_pinned_representation_source(tmp_path)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize(
    "version", ["schema_version", "policy_version", "serializer_version"]
)
def test_unapproved_schema_policy_and_serializer_are_rejected(clean_source, version):
    with pytest.raises(ValueError):
        policy = replace(native.NativePolicy(), **{version: "unapproved"})
        native.represent_closed(
            clean_source,
            clean_source.binding.records[2].origin,
            checked_at=AS_OF,
            policy=policy,
        )


def test_canonical_encoding_retains_signed_zero_null_absence_and_array_order():
    value = {"z": -0.0, "n": None, "a": [3, 1, 3], "t": START, "integer": 1}
    payload = native.canonical_payload(value)
    assert (
        payload == b'{"a":[3,1,3],"integer":1,"n":null,'
        b'"t":"2025-01-01T00:00:00.000000Z","z":-0.0}\n'
    )
    assert "missing" not in json.loads(payload)
    assert math.copysign(1, json.loads(payload)["z"]) == -1
    assert native.canonical_payload(dict(reversed(tuple(value.items())))) == payload
    assert native.canonical_payload({"integer": 1}) != native.canonical_payload(
        {"integer": 1.0}
    )


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        b"bytes",
        {1: "nonstring"},
        datetime(2025, 1, 1),
    ],
)
def test_invalid_canonical_values_are_rejected(value):
    with pytest.raises(ValueError):
        native.canonical_payload(value)


def test_raw_annotation_extras_absent_null_and_negative_zero_survive():
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    changed = _changed_endpoint(
        adapter,
        changes={
            "original_extra": {
                "null": None,
                "signed": -0.0,
                "list": ["candle", "unknown", "candle"],
            }
        },
    )
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "represented"
    raw = result.envelope.occurrences[0].raw
    assert "absent" not in raw
    assert raw["original_extra"]["null"] is None
    assert math.copysign(1, raw["original_extra"]["signed"]) == -1
    assert raw["original_extra"]["list"] == ("candle", "unknown", "candle")
    with pytest.raises(TypeError):
        raw["original_extra"]["null"] = 1


def test_audit_payload_determinism_complete_schema_and_digest(clean_source):
    first = native.audit_native(clean_source, checked_at=AS_OF)
    second = native.audit_native(clean_source, checked_at=AS_OF)
    assert first.canonical_report == second.canonical_report
    report = json.loads(first.canonical_report)
    assert set(report) == {
        "target_schema",
        "policy",
        "schema_version",
        "policy_version",
        "serializer_version",
        "source_identity",
        "source_receipt_sha256",
        "source_authentication",
        "manifest_reference",
        "scope",
        "representation_spec_id",
        "representation_build_id",
        "build",
        "dimension_counts",
        "rows",
        "research_only",
        "execution_ready",
        "point_in_time_verified",
        "decision_eligible",
        "anomaly_evidence_verified",
        "limitations",
        "payload_sha256",
    }
    assert report["target_schema"] == native.SCHEMA_VERSION
    assert report["policy"] == native.POLICY_VERSION
    assert report["payload_sha256"] == first.payload_sha256
    assert (
        first.payload_sha256
        == hashlib.sha256(
            native.canonical_payload(
                {k: v for k, v in report.items() if k != "payload_sha256"}
            )
        ).hexdigest()
    )
    assert report["source_authentication"] == "synthetic_fixture"
    assert report["research_only"] is True
    assert report["execution_ready"] is False
    assert report["point_in_time_verified"] is False
    assert report["decision_eligible"] is False
    assert report["anomaly_evidence_verified"] is False


def test_spec_build_and_payload_identities_are_distinct(clean_source):
    report = native.audit_native(clean_source, checked_at=AS_OF).report
    spec = {
        "schema_version": native.SCHEMA_VERSION,
        "source": "a" * 64,
        "scope": {"checked_at": AS_OF},
    }
    spec_id = native.representation_spec_id(spec)
    assert spec_id == native.representation_spec_id(dict(reversed(tuple(spec.items()))))
    first = native.representation_build_id(
        spec_id, code_sha256="b" * 64, dependency_versions={"python": "3.12"}
    )
    changed_code = native.representation_build_id(
        spec_id, code_sha256="c" * 64, dependency_versions={"python": "3.12"}
    )
    changed_deps = native.representation_build_id(
        spec_id, code_sha256="b" * 64, dependency_versions={"python": "3.12.1"}
    )
    changed_serializer = native.representation_build_id(
        spec_id,
        code_sha256="b" * 64,
        dependency_versions={"python": "3.12"},
        serializer_version="synthetic-next",
    )
    assert len({first, changed_code, changed_deps, changed_serializer}) == 4
    assert (
        report["representation_spec_id"]
        != clean_source.binding.identity.dataset_spec_id
    )
    assert (
        report["representation_build_id"]
        != clean_source.binding.identity.artifact_build_id
    )


def test_code_change_alters_build_not_logical_source_spec(clean_source, monkeypatch):
    monkeypatch.setattr(native, "_code_digest", lambda: "b" * 64)
    first = native.audit_native(clean_source, checked_at=AS_OF).report
    monkeypatch.setattr(native, "_code_digest", lambda: "c" * 64)
    second = native.audit_native(clean_source, checked_at=AS_OF).report
    assert first["representation_spec_id"] == second["representation_spec_id"]
    assert first["representation_build_id"] != second["representation_build_id"]
    assert first["payload_sha256"] != second["payload_sha256"]


class _ForbiddenOutcome:
    def __getattribute__(self, name):
        pytest.fail("native pre-closure inspection accessed an outcome")


class _ForbiddenSourceValues(Mapping):
    def __getitem__(self, key):
        pytest.fail(
            "native pre-closure inspection accessed raw outcome-bearing metadata"
        )

    def __iter__(self):
        pytest.fail("native pre-closure inspection traversed the full source row")

    def __len__(self):
        pytest.fail("native pre-closure inspection traversed the full source row")


def test_preclosure_never_reads_target_flags_anomalies_or_full_row(clean_source):
    record = clean_source.binding.records[2]
    original, original_values = record.outcome, record.source_values
    object.__setattr__(record, "outcome", _ForbiddenOutcome())
    object.__setattr__(record, "source_values", _ForbiddenSourceValues())
    try:
        result = _result(clean_source, checked_at=record.origin)
        assert result.envelope is None
        assert result.dimensions.temporal_closure == "not_closed"
        assert result.dimensions.native_representability == "not_inspected"
        assert result.dimensions.evidence_completeness == "not_inspected"
        assert result.dimensions.association_resolution == "not_inspected"
        assert result.dimensions.legacy_4a_compatibility == "not_closed"
        audit = native.audit_native(
            clean_source, checked_at=record.origin, origins=(record.origin,)
        )
        assert len(audit.report["rows"]) == 1
    finally:
        object.__setattr__(record, "outcome", original)
        object.__setattr__(record, "source_values", original_values)


def test_exact_close_is_inclusive_and_utc_equivalent(clean_source):
    record = clean_source.binding.records[2]
    assert _result(clean_source, checked_at=record.origin).envelope is None
    closed = _result(clean_source, checked_at=record.origin + HOUR)
    assert closed.dimensions.temporal_closure == "closed"
    assert closed.envelope.record is record
    equivalent = (record.origin + HOUR).astimezone(
        timezone(timedelta(0), "custom-zero")
    )
    assert native.canonical_payload(closed) == native.canonical_payload(
        _result(clean_source, checked_at=equivalent)
    )


def test_out_of_split_origin_is_audit_only_without_envelope_even_after_close():
    adapter = _make_adapter(start=fd.TEST_END - 2 * HOUR, count=3)
    source = native.bind_synthetic_representation(adapter)
    record = source.binding.records[-1]
    before = _result(source, -1, checked_at=record.origin)
    after = _result(source, -1, checked_at=record.origin + HOUR)
    assert before.period == "outside_approved_evaluation_window"
    assert before.dimensions.legacy_4a_compatibility == "audit_only"
    assert before.dimensions.temporal_closure == "not_closed"
    assert after.dimensions.temporal_closure == "closed"
    assert before.envelope is after.envelope is None


def test_gap_nulls_reasons_and_ar_adjacency_remain_authoritative():
    source = _source(field="candle", kind="missing_hour", missing=(2,))
    result = _result(source)
    record = result.envelope.record
    assert record.source_values["missing_hour"] is True
    assert record.outcome.target_valid is False
    assert record.outcome.target is None
    assert "current_missing" in record.outcome.invalid_reasons
    assert record.features.ar_lag_valid is False
    following = _result(source, 3).envelope.record
    assert following.features.ar_lag_valid is False
    assert following.features.values[0] is None
    assert following.features.null_reasons[0] == "gap_in_window"
    assert _result(source, 4).envelope.record.features.ar_lag_valid is True


def test_full_universe_dimensions_conserve_all_origins_and_legacy_is_independent():
    source = _source(field="unknown", kind="shortened_close")
    audit = native.audit_native(source, checked_at=AS_OF)
    count = len(source.binding.records)
    assert len(audit.report["rows"]) == count
    for counts in audit.report["dimension_counts"].values():
        assert sum(counts.values()) == count
    assert audit.report["dimension_counts"]["native_representability"] == {
        "represented": count
    }
    assert audit.report["dimension_counts"]["legacy_4a_compatibility"]["blocked"] > 0
    assert "rmse" not in audit.report
    assert "forecast_count" not in audit.report


def test_empty_scope_and_sorted_origin_scope_are_deterministic(clean_source):
    empty = native.audit_native(clean_source, checked_at=AS_OF, origins=())
    assert tuple(empty.report["rows"]) == ()
    assert all(
        sum(values.values()) == 0
        for values in empty.report["dimension_counts"].values()
    )
    origins = tuple(r.origin for r in clean_source.binding.records[:3])
    first = native.audit_native(clean_source, checked_at=AS_OF, origins=origins)
    second = native.audit_native(
        clean_source, checked_at=AS_OF, origins=tuple(reversed(origins))
    )
    assert first.canonical_report == second.canonical_report
    with pytest.raises(ValueError):
        native.audit_native(
            clean_source, checked_at=AS_OF, origins=(origins[0], origins[0])
        )


def test_forecast_plan_has_no_native_context_envelope_or_resolver(clean_source):
    binding = clean_source.binding
    record = binding.records[2]
    plan = hp.plan_forecast_fields(
        record.features, source=binding, reference=hp.source_ref(binding, record.origin)
    ).value
    assert plan is not None
    assert (
        set(plan.forecast_fields())
        & {
            "target",
            "target_valid",
            "target_manifest_anomaly",
            "envelope",
            "native_source",
            "resolver",
        }
        == set()
    )
    assert not {f.name for f in fields(plan)} & {
        "envelope",
        "source",
        "binding",
        "manifest",
        "outcome",
    }
    with pytest.raises(ValueError):
        model_evaluation.SyntheticFixture(
            synthetic=True, features=(record.features,), outcomes=()
        )
    with pytest.raises(ValueError):
        model_evaluation.run_synthetic(
            clean_source,
            accounting.OriginUniverse("test", START, START + HOUR),
            provenance=None,
            evidence=None,
            evaluated_at_utc=AS_OF,
        )


def test_native_audit_never_invokes_io_models_scoring_or_reporting(
    clean_source, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail(
            "native representation attempted I/O, model execution or evaluation"
        )

    for module, name in (
        (engine, "calculate_features"),
        (fd, "build_origin_ledger"),
        (fd, "publish_ledger"),
        (model_evaluation, "run_synthetic"),
        (statistical_baselines, "fit_ar"),
        (statistical_baselines, "predict_mean"),
        (ridge_regression, "fit_ridge"),
        (ridge_regression, "select_alpha"),
        (accounting, "Score"),
        (reporting, "build_report"),
        (pl, "read_parquet"),
        (builtins, "open"),
        (Path, "write_bytes"),
        (Path, "write_text"),
        (socket, "socket"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    # Build-content hashing may read implementation bytes; no source datasets.
    original_read = Path.read_bytes

    def implementation_bytes(path):
        assert str(path).endswith(".py"), f"unexpected data read: {path}"
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", implementation_bytes)
    audit = native.audit_native(clean_source, checked_at=AS_OF)
    assert audit.report["execution_ready"] is False
    assert audit.report["point_in_time_verified"] is False


@pytest.fixture
def annotated_result():
    return _result(_source())


@pytest.mark.parametrize(
    "change",
    [
        {"dataset_spec_id": "not-a-digest"},
        {"artifact_build_id": "not-a-digest"},
        {"receipt_sha256": "not-a-digest"},
        {"source_identifier": ""},
        {"source_row_index": -1},
        {"source_row_index": True},
        {"origin": datetime(2025, 1, 1)},
        {"origin": START + timedelta(minutes=1)},
    ],
)
def test_occurrence_rejects_malformed_manual_source_reference(annotated_result, change):
    occurrence = annotated_result.envelope.occurrences[0]
    with pytest.raises(ValueError):
        replace(occurrence, source_ref=replace(occurrence.source_ref, **change))


@pytest.mark.parametrize(
    "change",
    [
        {"source_ref": "untyped"},
        {"collection": "unrecognized"},
        {"association": "feature_window"},
        {"source_column": "involved_anomalies"},
        {"source_column": ""},
        {"position": -1},
        {"position": True},
    ],
)
def test_occurrence_rejects_invalid_manual_role_and_key_structure(
    annotated_result, change
):
    with pytest.raises(ValueError):
        replace(annotated_result.envelope.occurrences[0], **change)


@pytest.mark.parametrize(
    "change",
    [
        {"source_row_index": 3},
        {"source_identifier": "different-source"},
        {"origin": START + 4 * HOUR},
        {"dataset_spec_id": "f" * 64},
        {"artifact_build_id": "f" * 64},
    ],
)
def test_envelope_rejects_occurrence_from_different_row_or_source(
    annotated_result, change
):
    envelope = annotated_result.envelope
    original = envelope.occurrences[0]
    changed = replace(original, source_ref=replace(original.source_ref, **change))
    with pytest.raises(ValueError):
        replace(envelope, occurrences=(changed, *envelope.occurrences[1:]))


@pytest.mark.parametrize(
    "defect", ["collection_order", "first_position", "position_gap"]
)
def test_envelope_rejects_noncanonical_collection_or_position_order(
    annotated_result, defect
):
    envelope = annotated_result.envelope
    endpoint, window = envelope.occurrences
    if defect == "collection_order":
        occurrences = (window, endpoint)
    elif defect == "first_position":
        occurrences = (endpoint, replace(window, position=1))
    else:
        occurrences = (endpoint, window, replace(window, position=2))
    with pytest.raises(ValueError):
        replace(envelope, occurrences=occurrences)


def test_manually_constructed_envelope_retains_valid_duplicate_occurrences(
    annotated_result,
):
    envelope = annotated_result.envelope
    endpoint, window = envelope.occurrences
    duplicate = replace(window, position=1)
    result = replace(envelope, occurrences=(endpoint, window, duplicate))
    assert len(result.occurrences) == 3
    assert result.occurrences[1].raw == result.occurrences[2].raw
    assert result.occurrences[1].position != result.occurrences[2].position


@pytest.mark.parametrize(
    "change",
    [
        {"source_ref": "not-a-reference"},
        {"period": "unrecognized"},
        {"period": "training_history"},
        {"dimensions": {}},
        {"findings": ["not-immutable"]},
        {"findings": ("duplicate", "duplicate")},
        {"findings": (None,)},
        {"envelope": None},
    ],
)
def test_result_rejects_malformed_manual_structure(annotated_result, change):
    with pytest.raises(ValueError):
        replace(annotated_result, **change)


def test_result_reference_must_match_its_envelope_source(annotated_result):
    changed = replace(annotated_result.source_ref, source_identifier="different-source")
    with pytest.raises(ValueError):
        replace(annotated_result, source_ref=changed)


@pytest.mark.parametrize(
    "dimension,value",
    [
        ("native_representability", "not_inspected"),
        ("temporal_closure", "not_closed"),
        ("legacy_4a_compatibility", "audit_only"),
    ],
)
def test_result_cannot_attach_envelope_to_uninspected_unclosed_or_audit_only_row(
    annotated_result, dimension, value
):
    dimensions = replace(annotated_result.dimensions, **{dimension: value})
    with pytest.raises(ValueError):
        replace(annotated_result, dimensions=dimensions)


def test_failed_result_may_have_no_envelope_and_constructors_prove_no_authentication(
    annotated_result,
):
    dimensions = replace(annotated_result.dimensions, native_representability="failed")
    failed = replace(
        annotated_result,
        dimensions=dimensions,
        envelope=None,
        findings=("synthetic_structure_failure",),
    )
    assert failed.envelope is None
    assert failed.dimensions.source_authentication == "synthetic_fixture"
    assert "authenticated_source_bytes" not in {f.name for f in fields(failed)}


@pytest.mark.parametrize(
    "field,kind,key,value",
    [
        ("close", "source_discrepancy", "manifest_version", "contradictory-v2"),
        (
            "unknown",
            "shortened_close",
            "recorded_source_close_at",
            "2025-01-01T02:45:00Z",
        ),
        ("candle", "missing_hour", "coverage_basis", "unsupported_other_range"),
        (
            "close",
            "source_discrepancy",
            "source_evidence",
            (
                {
                    "reference": "data/verification/synthetic-only.json",
                    "sha256": "f" * 64,
                    "observed_at": "2025-01-01T08:00:00Z",
                },
            ),
        ),
        (
            "close",
            "source_discrepancy",
            "source_evidence",
            (
                {
                    "reference": "data/verification/synthetic-only.json",
                    "sha256": "e" * 64,
                    "observed_at": "2025-01-01T09:00:00Z",
                },
            ),
        ),
    ],
)
def test_supplied_full_manifest_fields_cannot_contradict_matched_record(
    field, kind, key, value
):
    adapter = _make_adapter(
        count=8,
        missing=(2,) if field == "candle" else (),
        anomalies=(_annotation(2, (field,), kind),),
    )
    changed = _changed_endpoint(adapter, changes={key: value})
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "failed"
    assert result.envelope is not None
    occurrence = result.envelope.occurrences[0]
    assert occurrence.linkage == "contradictory"
    assert _plain(occurrence.raw[key]) == _plain(value)
    assert occurrence.manifest_record is None


@pytest.mark.parametrize(
    "field,kind",
    [
        ("close", "source_discrepancy"),
        ("unknown", "shortened_close"),
        ("candle", "missing_hour"),
    ],
)
def test_matching_full_manifest_details_accept_semantic_utc_text_without_rewriting(
    field, kind
):
    annotation = _annotation(2, (field,), kind)
    adapter = _make_adapter(
        count=8,
        missing=(2,) if field == "candle" else (),
        anomalies=(annotation,),
    )
    complete = adapter.manifest.to_dict()["records"][0]
    original_evidence_time = complete["source_evidence"][0]["observed_at"]
    extras = {
        key: value
        for key, value in complete.items()
        if key
        not in {
            "timestamp",
            "anomaly_type",
            "affected_fields",
            "severity",
            "review_status",
            "evidence_references",
        }
    }
    extras["source_evidence"][0]["observed_at"] = "2025-01-01T08:00:00Z"
    if kind == "shortened_close":
        extras["recorded_source_close_at"] = "2025-01-01T02:40:00Z"
    changed = _changed_endpoint(adapter, changes=extras)
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "represented", result.findings
    occurrence = result.envelope.occurrences[0]
    assert occurrence.linkage == "matched"
    assert occurrence.raw["source_evidence"][0]["observed_at"] == (
        "2025-01-01T08:00:00Z"
    )
    if kind == "shortened_close":
        assert occurrence.raw["recorded_source_close_at"] == "2025-01-01T02:40:00Z"
    assert (
        occurrence.manifest_record["source_evidence"][0]["observed_at"]
        == original_evidence_time
    )
    assert result.dimensions.evidence_completeness == "recorded_references_unverified"


@pytest.mark.parametrize("key", ["timestamp", "anomaly_type"])
def test_absent_linkage_key_blocks_native_without_guessing_and_preserves_legacy_failure(
    key,
):
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    changed = _changed_endpoint(adapter, remove=(key,))
    result = _result(native.bind_synthetic_representation(changed))
    assert result.dimensions.native_representability == "blocked"
    assert result.dimensions.legacy_4a_compatibility == "failed"
    assert result.dimensions.evidence_completeness == "unresolved_linkage"
    assert result.envelope is not None
    occurrence = result.envelope.occurrences[0]
    assert key not in occurrence.raw
    assert occurrence.linkage == "missing"
    assert occurrence.manifest_record_index is None


def test_conflicting_payload_cannot_overwrite_same_immutable_build_identity():
    adapter = _make_adapter(count=8, anomalies=(_annotation(2),))
    original_source = native.bind_synthetic_representation(adapter)
    origin = adapter.records[2].origin
    boundary = START + 7 * HOUR
    original = native.audit_native(
        original_source, checked_at=boundary, origins=(origin,)
    )
    changed_adapter = _changed_endpoint(
        adapter, changes={"opaque_original_annotation": "different retained bytes"}
    )
    changed_source = native.bind_synthetic_representation(changed_adapter)
    assert original_source.binding.identity == changed_source.binding.identity
    assert original_source.manifest_reference == changed_source.manifest_reference
    # Caller assertions cannot create two immutable payloads under the same
    # source/spec/code identity. No on-disk artifact or registry is accessed.
    with pytest.raises(ValueError, match="conflicting"):
        native.audit_native(changed_source, checked_at=boundary, origins=(origin,))
    repeated = native.audit_native(
        original_source, checked_at=boundary, origins=(origin,)
    )
    assert repeated.canonical_report == original.canonical_report
    assert repeated.payload_sha256 == original.payload_sha256
    assert (
        repeated.report["representation_build_id"]
        == (original.report["representation_build_id"])
    )
