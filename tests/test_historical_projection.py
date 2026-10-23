"""Synthetic-only checks for the fail-closed historical projection boundary."""

from __future__ import annotations

import builtins
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

from quant.features import engine
from quant.features.manifest import Anomaly, AnomalyManifest, Evidence
from quant.research import evaluation_protocol as protocol
from quant.research import evaluation_reporting as reporting
from quant.research import forecast_accounting as accounting
from quant.research import forecast_dataset as fd
from quant.research import historical_adapter as ha
from quant.research import historical_projection as hp
from quant.research import model_evaluation, ridge_regression, statistical_baselines

HOUR = timedelta(hours=1)
START = datetime(2025, 1, 1, tzinfo=UTC)
AS_OF = START + 174 * HOUR


def _make_adapter(*, missing=(), anomalies=(), start=START, count=174):
    """Create source evidence from synthetic candles, never repository datasets."""
    as_of = start + count * HOUR
    manifest = AnomalyManifest("projection-synthetic-v1", None, tuple(anomalies))
    rows = []
    for hour in range(count):
        if hour in missing:
            continue
        close = float(100 + hour)
        rows.append(
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "timestamp": start + hour * HOUR,
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": float(10 + hour),
                "ingested_at": as_of + HOUR,
            }
        )
    silver = pl.DataFrame(rows, schema=ha.SILVER_SCHEMA)
    gold = engine.calculate_features(
        silver,
        manifest,
        analysis_as_of=as_of,
        generated_at=as_of + HOUR,
        source_snapshot_sha256="a" * 64,
    )
    ledger = fd.build_origin_ledger(
        silver,
        gold,
        manifest,
        analysis_as_of=as_of,
        silver_sha256="a" * 64,
        gold_sha256="b" * 64,
    )
    identity = ha.SourceIdentity(
        "a" * 64,
        "b" * 64,
        manifest.sha256,
        ledger["dataset_spec_id"][0],
        "d" * 64,
        as_of,
        engine.FEATURE_VERSION,
        manifest.manifest_version,
    )
    result = ha.audit_frames(silver, gold, ledger, manifest, identity=identity)
    assert result.adapter is not None, result.report
    return result.adapter


@pytest.fixture(scope="module")
def adapter():
    return _make_adapter()


@pytest.fixture
def source(adapter):
    return hp.bind_synthetic(adapter)


def _annotation(hour, fields=("close",), kind="source_discrepancy"):
    return Anomaly(
        START + hour * HOUR,
        kind,
        fields,
        (Evidence("data/verification/synthetic-only.json", "e" * 64, AS_OF),),
        "unrated",
        "unresolved",
        "projection-synthetic-v1",
        **(
            {
                "recorded_source_close_at": START + hour * HOUR + timedelta(minutes=40),
                "source_close_precision": "milliseconds",
            }
            if kind == "shortened_close"
            else {"coverage_basis": "synthetic_checked_range"}
            if kind == "missing_hour"
            else {}
        ),
    )


def _edited(adapter, index, *, feature_changes=None, outcome_changes=None, raw=None):
    records = list(adapter.records)
    record = records[index]
    records[index] = replace(
        record,
        features=replace(record.features, **(feature_changes or {})),
        outcome=replace(record.outcome, **(outcome_changes or {})),
        source_values=ha._freeze({**record.source_values, **(raw or {})}),
    )
    return replace(adapter, records=tuple(records))


def _project(source, index, *, checked_at=AS_OF):
    return hp.project_closed_outcome(
        source.records[index], source=source, checked_at=checked_at
    )


def _plan(source, index):
    record = source.records[index]
    return hp.plan_forecast_fields(
        record.features,
        source=source,
        reference=hp.source_ref(source, record.origin),
    )


def _plain(value):
    if isinstance(value, Mapping):
        return {name: _plain(item) for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def test_policy_identity_and_immutable_synthetic_receipt(source):
    assert hp.HistoricalProjectionPolicy().version == "pqta-003d-5b-projection-v1"
    assert source.receipt.mode == "synthetic_fixture"
    assert source.receipt.authenticated_source_bytes is False
    assert (
        source.identity.manifest_sha256
        == source.records[0].source_values["anomaly_manifest_sha256"]
    )
    with pytest.raises((AttributeError, TypeError)):
        source.receipt.authenticated_source_bytes = True


def test_compatible_closed_endpoint_projection_preserves_value(source):
    result = _project(source, 170)
    original = source.records[170]
    assert result.classification == "compatible"
    assert result.value.outcome.target == original.outcome.target
    assert result.value.outcome.target_valid is original.outcome.target_valid
    assert result.value.outcome.anomaly_evidence_status == "unverified"
    assert result.value.outcome.quality == accounting.Quality(True, True, (), ())
    assert result.value.attachment.record is original


def test_supported_endpoint_fields_and_feature_records_stay_separate():
    adapter = _make_adapter(
        anomalies=(
            _annotation(1, ("volume", "close")),
            _annotation(3, ("high",)),
        )
    )
    source = hp.bind_synthetic(adapter)
    result = _project(source, 3)
    assert result.classification == "compatible"
    quality = result.value.outcome.quality
    assert quality.anomaly_types == ("source_discrepancy",)
    assert quality.affected_fields == ("high",)
    record = result.value.attachment.record
    assert record.outcome.feature_window_anomalies != (
        record.outcome.target_endpoint_anomalies
    )
    assert any(
        a.raw["affected_fields"] == ("close", "volume")
        for a in record.outcome.feature_window_anomalies
    )
    assert result.value.outcome.target_manifest_anomaly is True


@pytest.mark.parametrize(
    "field,kind", [("candle", "missing_hour"), ("unknown", "shortened_close")]
)
def test_unsupported_field_blocks_without_loss_or_fabricated_outcome(field, kind):
    source = hp.bind_synthetic(
        _make_adapter(
            missing=(2,) if field == "candle" else (),
            anomalies=(_annotation(2, (field,), kind),),
        )
    )
    result = _project(source, 2)
    assert result.classification == "blocked"
    assert result.value is None
    assert field in result.unsupported_fields
    assert any(
        a.raw["affected_fields"] == (field,)
        for a in source.records[2].outcome.target_endpoint_anomalies
    )
    assert not hasattr(result, "attachment")


def test_unsupported_feature_window_alone_still_blocks_complete_projection():
    source = hp.bind_synthetic(
        _make_adapter(anomalies=(_annotation(2, ("unknown",), "shortened_close"),))
    )
    record = source.records[5]
    assert not record.outcome.target_endpoint_anomalies
    assert record.outcome.feature_window_anomalies
    assert _project(source, 5).classification == "blocked"


@pytest.mark.parametrize(
    "association,kind",
    [("unresolved", "source_discrepancy"), ("target_endpoint", "invented")],
)
def test_unresolved_association_and_unknown_anomaly_type_fail_closed(
    adapter, association, kind
):
    record = adapter.records[4]
    raw = {
        "timestamp": record.features.feature_open_t,
        "anomaly_type": kind,
        "affected_fields": ("close",),
        "evidence_references": ("data/verification/invented.json",),
    }
    annotation = ha.HistoricalAnomaly(
        association,
        "unspecified" if association == "unresolved" else "target_endpoint_anomalies",
        4,
        ha._freeze(raw),
    )
    changed = _edited(
        adapter,
        4,
        outcome_changes={
            "unresolved_anomalies": (annotation,)
            if association == "unresolved"
            else (),
            "target_endpoint_anomalies": (annotation,)
            if association != "unresolved"
            else (),
            "target_manifest_anomaly": association != "unresolved",
        },
        raw={
            "target_manifest_anomaly": association != "unresolved",
            "target_endpoint_anomalies": (raw,) if association != "unresolved" else (),
        },
    )
    result = _project(hp.bind_synthetic(changed), 4)
    assert result.classification == "blocked"
    assert result.value is None


def test_reason_priority_is_normalized_without_mutating_original():
    source = hp.bind_synthetic(_make_adapter(count=5))
    original = source.records[-1]
    assert original.outcome.invalid_reasons == ("next_incomplete", "next_missing")
    result = _project(source, -1, checked_at=original.origin + HOUR)
    assert result.classification == "compatible"
    assert result.value.outcome.invalid_reasons == ("next_missing", "next_incomplete")
    assert result.value.attachment.record.outcome.invalid_reasons == (
        "next_incomplete",
        "next_missing",
    )


@pytest.mark.parametrize(
    "change",
    [{"target_valid": False}, {"target": 99.0}, {"target_manifest_anomaly": True}],
)
def test_inconsistent_outcome_metadata_fails_closed(adapter, change):
    source = hp.bind_synthetic(_edited(adapter, 170, outcome_changes=change))
    result = _project(source, 170)
    assert result.classification == "failed"
    assert result.value is None


def test_forecast_plan_is_allowlisted_and_has_only_opaque_linkage(source):
    result = _plan(source, 170)
    assert result.classification == "compatible"
    plan = result.value
    mapping = plan.forecast_fields()
    protocol.validate_forecast_fields(mapping)
    assert mapping["feature_complete"] is True
    assert mapping["ar_lag_valid"] is True
    assert plan.values == source.records[170].features.values
    assert not set(mapping) & {
        "target",
        "target_valid",
        "target_manifest_anomaly",
        "next_candle_valid",
        "target_endpoint_anomalies",
        "lane_a_primary",
        "lane_a_sensitivity",
    }
    for value in (result, plan, result.source_ref):
        assert not any(
            hasattr(value, name)
            for name in (
                "outcome",
                "attachment",
                "record",
                "records",
                "resolve",
                "resolver",
            )
        )


class _ForbiddenOutcome:
    def __getattribute__(self, name):
        pytest.fail("current/future target information was accessed")


class _ForecastOnlySourceValues(Mapping):
    def __init__(self, original):
        self.original = original

    def __getitem__(self, key):
        if key.startswith(("target", "next_", "lane_")):
            pytest.fail("forecast interface read outcome-bearing source metadata")
        return self.original[key]

    def __iter__(self):
        pytest.fail("forecast interface traversed the whole outcome-bearing row")

    def __len__(self):
        return len(self.original)


def test_forecast_plan_and_preclosure_check_never_read_target(adapter):
    # Bind the lossless source audit first. Instrument later forecast-time
    # access, not the initial receipt construction that digests the full source.
    source = hp.bind_synthetic(adapter)
    record = source.records[170]
    original = record.outcome
    original_values = record.source_values
    object.__setattr__(record, "outcome", _ForbiddenOutcome())
    object.__setattr__(
        record, "source_values", _ForecastOnlySourceValues(original_values)
    )
    try:
        assert _plan(source, 170).classification == "compatible"
        result = _project(source, 170, checked_at=record.origin)
        assert result.classification == "not_closed"
        assert result.value is None
        assert not result.unsupported_fields
    finally:
        object.__setattr__(record, "outcome", original)
        object.__setattr__(record, "source_values", original_values)


def test_exact_theoretical_target_close_is_inclusive(source):
    record = source.records[170]
    assert (
        _project(source, 170, checked_at=record.origin).classification == "not_closed"
    )
    assert (
        _project(source, 170, checked_at=record.origin + HOUR).classification
        == "compatible"
    )


def test_closed_history_excludes_current_and_future_labels(source):
    origin = source.records[170].origin
    plans = hp.plan_completed_history(
        source, forecast_origin=origin, method="expanding_mean", sample="a_primary"
    )
    by_origin = {plan.source_ref.origin: plan for plan in plans}
    assert by_origin[origin - HOUR].eligible is True
    assert by_origin[origin].classification == "not_closed"
    assert by_origin[origin].eligible is None
    assert all(
        item.source_ref.origin + HOUR <= origin
        for item in plans
        if item.eligible is True
    )


def test_gap_breaks_ar_adjacency_without_compressing_timeline():
    source = hp.bind_synthetic(
        _make_adapter(
            missing=(170,), anomalies=(_annotation(170, ("candle",), "missing_hour"),)
        )
    )
    assert len(source.records) == 174
    assert source.records[170].features.ar_lag_valid is False
    assert source.records[171].features.ar_lag_valid is False
    assert source.records[172].features.ar_lag_valid is True
    # The coherent missing-hour manifest contains unsupported `candle`.
    # Keep the real lag flags, but never pretend this scope is projected.
    for index in (170, 171, 172):
        assert _plan(source, index).classification == "blocked"
    plans = hp.plan_completed_history(
        source, forecast_origin=AS_OF, method="ar_1", sample="a_primary"
    )
    indexed = {plan.source_ref.origin: plan for plan in plans}
    assert indexed[source.records[170].origin].eligible is None
    assert indexed[source.records[171].origin].eligible is None


def test_invalid_previous_candle_cannot_be_used_as_successful_current_ar_lag(adapter):
    changed = _edited(adapter, 169, raw={"current_candle_valid": False})
    source = hp.bind_synthetic(changed)
    result = _plan(source, 170)
    assert result.classification == "failed"
    assert result.value is None
    assert any("adjacent" in reason for reason in result.findings)


def test_raw_endpoint_array_cannot_disagree_with_lossless_associations():
    adapter = _make_adapter(anomalies=(_annotation(169),))
    source = hp.bind_synthetic(
        _edited(adapter, 169, raw={"target_endpoint_anomalies": []})
    )
    result = _project(source, 169)
    assert result.classification == "failed"
    assert result.value is None


def test_primary_and_sensitivity_training_masks_remain_method_specific():
    source = hp.bind_synthetic(_make_adapter(anomalies=(_annotation(169),)))
    for method in ("expanding_mean", "ar_1", "ridge_7"):
        primary = hp.plan_completed_history(
            source, forecast_origin=AS_OF, method=method, sample="a_primary"
        )
        sensitivity = hp.plan_completed_history(
            source, forecast_origin=AS_OF, method=method, sample="a_sensitivity"
        )
        assert primary[169].eligible is True
        assert sensitivity[169].eligible is False


def test_forecast_side_sensitivity_mask_does_not_become_score_only():
    source = hp.bind_synthetic(_make_adapter(anomalies=(_annotation(169),)))
    mapping = _plan(source, 170).value.forecast_fields()
    assert protocol.forecast_inputs_eligible("ridge_7", "a_primary", mapping)
    assert not protocol.forecast_inputs_eligible("ridge_7", "a_sensitivity", mapping)
    assert protocol.forecast_inputs_eligible("ar_1", "a_primary", mapping)
    assert not protocol.forecast_inputs_eligible("ar_1", "a_sensitivity", mapping)
    assert protocol.forecast_inputs_eligible("zero_return", "a_sensitivity", mapping)


def test_null_features_are_preserved_and_do_not_become_ridge_eligible(source):
    result = _plan(source, 0)
    assert result.classification == "compatible"
    assert None in result.value.values
    assert result.value.forecast_fields()["feature_complete"] is False
    assert not protocol.forecast_inputs_eligible(
        "ridge_7", "a_primary", result.value.forecast_fields()
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_feature_is_explicit_failure(adapter, value):
    values = (value, *adapter.records[170].features.values[1:])
    with pytest.raises(ValueError, match="JSON compliant|finite|range"):
        hp.bind_synthetic(_edited(adapter, 170, feature_changes={"values": values}))


def test_out_of_split_origin_is_retained_as_audit_only():
    adapter = _make_adapter(start=fd.TEST_END - 2 * HOUR, count=2)
    source = hp.bind_synthetic(adapter)
    assert source.records[-1].origin == fd.TEST_END
    result = _project(source, -1, checked_at=fd.TEST_END + HOUR)
    assert result.classification == "audit_only"
    assert result.value is None
    audit = hp.audit_compatibility(source, checked_at=fd.TEST_END + HOUR)
    assert audit.report["counts"]["total_origins"] == 2
    assert audit.report["counts"]["audit_only"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"silver_sha256": "e" * 64},
        {"dataset_spec_id": "e" * 64},
        {"manifest_sha256": "e" * 64},
    ],
)
def test_valid_digest_syntax_cannot_forge_source_identity(adapter, change):
    with pytest.raises(ValueError):
        hp.bind_synthetic(
            replace(adapter, identity=replace(adapter.identity, **change))
        )


def test_forged_authenticated_receipt_or_source_binding_is_rejected(source):
    try:
        receipt = replace(source.receipt, authenticated_source_bytes=True)
        forged = replace(source, receipt=receipt)
    except (TypeError, ValueError):
        return
    with pytest.raises(ValueError):
        hp.audit_compatibility(forged, checked_at=AS_OF)


def test_inplace_receipt_boolean_forgery_is_detected_by_bound_digest(source):
    receipt = source.receipt
    object.__setattr__(receipt, "authenticated_source_bytes", True)
    try:
        with pytest.raises(ValueError, match="tampered"):
            hp.source_ref(source, source.records[170].origin)
    finally:
        object.__setattr__(receipt, "authenticated_source_bytes", False)


@pytest.mark.parametrize(
    "name",
    [
        "origin_ledger.parquet",
        "dataset_validation.json",
        "provenance.json",
        "provenance.sha256",
    ],
)
def test_pinned_projection_receipt_rejects_tampered_temp_artifact_bytes(
    tmp_path, monkeypatch, name
):
    from test_historical_adapter import _temporary_artifact_set

    directory, _ = _temporary_artifact_set(tmp_path, monkeypatch)
    tampered = directory / name
    tampered.write_bytes(tampered.read_bytes() + b"!")
    before = {path.name: path.read_bytes() for path in directory.iterdir()}

    def forbidden(*args, **kwargs):
        pytest.fail(
            "failed source verification attempted parsing, writing or execution"
        )

    monkeypatch.setattr(pl, "read_parquet", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    with pytest.raises(ValueError, match="pinned source hash mismatch"):
        hp.verify_pinned_source(tmp_path)
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}


def test_pinned_authentication_uses_actual_reader_and_rejects_missing_bytes(tmp_path):
    with pytest.raises(ValueError):
        hp.verify_pinned_source(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_reference_from_different_bound_source_cannot_be_reused(source):
    other = hp.bind_synthetic(_make_adapter(count=173))
    ref = hp.source_ref(other, other.records[10].origin)
    with pytest.raises(ValueError, match="reference mismatch"):
        hp.plan_forecast_fields(
            source.records[10].features, source=source, reference=ref
        )


def test_canonical_report_has_deterministic_digest_and_no_readiness_claim(source):
    first = hp.audit_compatibility(source, checked_at=AS_OF)
    second = hp.audit_compatibility(source, checked_at=AS_OF)
    assert first.canonical_report == second.canonical_report
    payload = json.loads(first.canonical_report)
    assert payload == _plain(first.report)
    digest = payload.pop("payload_sha256")
    expected_payload = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    assert (
        first.payload_sha256 == digest == hashlib.sha256(expected_payload).hexdigest()
    )
    assert first.canonical_report.endswith(b"\n")
    assert b"2025-01-01T01:00:00.000000Z" in first.canonical_report
    for name in (
        "execution_ready",
        "point_in_time_verified",
        "decision_eligible",
        "scope_projectable",
    ):
        assert first.report[name] is False
    counts = first.report["counts"]
    assert counts["total_origins"] == len(source.records)
    assert (
        sum(
            counts[name]
            for name in ("compatible", "blocked", "failed", "audit_only", "not_closed")
        )
        == counts["total_origins"]
    )


def test_unsupported_rows_remain_full_universe_not_reduced_metrics():
    source = hp.bind_synthetic(
        _make_adapter(anomalies=(_annotation(169, ("unknown",), "shortened_close"),))
    )
    audit = hp.audit_compatibility(source, checked_at=AS_OF)
    assert audit.report["counts"]["total_origins"] == 174
    assert audit.report["counts"]["blocked"] > 0
    assert audit.report["scope_projectable"] is False
    assert "unknown" in audit.report["unsupported_fields"]
    assert not any(
        name in audit.report for name in ("rmse", "mae", "forecasts", "scores")
    )


def test_signed_zero_preserved_in_forecast_plan(adapter):
    record = adapter.records[170]
    values = (-0.0, *record.features.values[1:])
    source = hp.bind_synthetic(
        _edited(
            adapter,
            170,
            feature_changes={"values": values},
            raw={"log_return_1h": -0.0, "null_reason__log_return_1h": None},
        )
    )
    result = _plan(source, 170)
    assert result.classification == "compatible"
    assert math.copysign(1.0, result.value.values[0]) == -1.0


@pytest.mark.parametrize("location", ["features", "raw_source"])
def test_bound_signed_zero_tampering_changes_canonical_identity(adapter, location):
    values = (-0.0, *adapter.records[170].features.values[1:])
    source = hp.bind_synthetic(
        _edited(
            adapter,
            170,
            feature_changes={"values": values},
            raw={"log_return_1h": -0.0},
        )
    )
    record = source.records[170]
    if location == "features":
        original = record.features
        object.__setattr__(
            record, "features", replace(original, values=(0.0, *values[1:]))
        )
        try:
            assert _plan(source, 170).classification == "failed"
        finally:
            object.__setattr__(record, "features", original)
    else:
        original = record.source_values
        object.__setattr__(
            record, "source_values", ha._freeze({**original, "log_return_1h": 0.0})
        )
        try:
            assert _project(source, 170).classification == "failed"
        finally:
            object.__setattr__(record, "source_values", original)


def test_unknown_feature_null_reason_fails_without_repair(adapter):
    original = adapter.records[0].features.null_reasons
    source = hp.bind_synthetic(
        _edited(
            adapter,
            0,
            feature_changes={"null_reasons": ("invented_reason", *original[1:])},
            raw={"null_reason__log_return_1h": "invented_reason"},
        )
    )
    result = _plan(source, 0)
    assert result.classification == "failed"
    assert result.value is None
    assert result.findings == ("unknown feature null reason",)
    assert source.records[0].features.null_reasons[0] == "invented_reason"


@pytest.mark.parametrize(
    "raw",
    [
        {"source_present": False},
        {"missing_hour": True},
        {"current_candle_valid": False},
        {"current_candle_present": False},
        {"current_candle_complete": False},
        {"source_present": None},
        {"current_candle_valid": 1},
        {"current_candle_complete": None},
    ],
)
def test_presence_validity_completeness_mismatches_fail_closed(adapter, raw):
    source = hp.bind_synthetic(_edited(adapter, 170, raw=raw))
    result = _plan(source, 170)
    assert result.classification == "failed"
    assert result.value is None


def test_canonical_payload_exact_zero_null_and_timestamp_encoding():
    payload = hp.canonical_payload({"zero": -0.0, "none": None, "at": START})
    assert payload == b'{"at":"2025-01-01T00:00:00.000000Z","none":null,"zero":-0.0}\n'
    assert hp.canonical_payload({"zero": 0.0, "none": None, "at": START}) != payload


def test_utc_equivalent_clocks_and_unsorted_scope_are_deterministic(source):
    origins = tuple(record.origin for record in source.records[5:9])
    first = hp.audit_compatibility(source, checked_at=AS_OF, origins=origins)
    equivalent = AS_OF.astimezone(timezone(timedelta(0), "SyntheticZero"))
    second = hp.audit_compatibility(
        source, checked_at=equivalent, origins=tuple(reversed(origins))
    )
    assert first.canonical_report == second.canonical_report


def test_source_order_duplicates_and_timestamp_tampering_are_rejected(adapter):
    with pytest.raises(ValueError):
        hp.bind_synthetic(replace(adapter, records=tuple(reversed(adapter.records))))
    with pytest.raises(ValueError):
        hp.bind_synthetic(
            replace(adapter, records=(adapter.records[0], *adapter.records))
        )
    records = list(adapter.records)
    records[1] = replace(records[1], source_row_index=0)
    with pytest.raises(ValueError):
        hp.bind_synthetic(replace(adapter, records=tuple(records)))


def test_opaque_reference_has_no_data_access_capabilities(source):
    ref = hp.source_ref(source, source.records[170].origin)
    assert ref.origin == source.records[170].origin
    assert all(not callable(getattr(ref, field.name)) for field in fields(ref))
    assert not any(
        hasattr(ref, name)
        for name in ("adapter", "record", "source_values", "outcome", "resolve")
    )


def test_synthetic_runner_and_reporting_guards_are_not_bypassed(source):
    with pytest.raises(ValueError, match="typed synthetic fixture"):
        model_evaluation.run_synthetic(
            source,
            source.records[0],
            provenance=None,
            evidence=None,
            evaluated_at_utc=AS_OF,
        )
    with pytest.raises(ValueError, match="cannot claim verified"):
        reporting.Provenance(
            **{
                field.name: True if field.name == "artifact_bytes_verified" else None
                for field in fields(reporting.Provenance)
            }
        )
    assert protocol.FORECAST_STATUSES == {"emitted", "abstained"}
    assert protocol.SCORE_STATUSES == {
        "scored",
        "emitted_but_not_scored",
        "not_scored_no_forecast",
    }


def test_in_memory_projection_does_not_read_files_rebuild_features_or_run_models(
    source, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("projection attempted I/O, feature construction or model execution")

    for module, name in (
        (statistical_baselines, "fit_ar"),
        (statistical_baselines, "predict_mean"),
        (ridge_regression, "fit_ridge"),
        (ridge_regression, "select_alpha"),
        (model_evaluation, "run_synthetic"),
        (fd, "build_origin_ledger"),
        (fd, "publish_ledger"),
        (engine, "calculate_features"),
        (pl, "read_parquet"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    original_read = Path.read_bytes
    original_open = builtins.open

    def allowed_read(path):
        # A code-content hash is provenance, not historical dataset access.
        assert path == Path(hp.__file__)
        return original_read(path)

    def no_dataset_open(path, *args, **kwargs):
        assert not any(
            str(path).endswith(suffix) for suffix in (".parquet", ".duckdb", ".db")
        )
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", no_dataset_open)
    monkeypatch.setattr(Path, "read_bytes", allowed_read)
    for name in ("write_bytes", "write_text"):
        monkeypatch.setattr(Path, name, forbidden)
    assert _plan(source, 170).classification == "compatible"
    assert _project(source, 170).classification == "compatible"
    assert hp.audit_compatibility(source, checked_at=AS_OF).payload_sha256
