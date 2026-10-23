"""Synthetic-only checks for lossless, non-executable historical auditing."""

from __future__ import annotations

import builtins
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from quant.features import engine
from quant.features.manifest import Anomaly, AnomalyManifest, Evidence
from quant.research import forecast_dataset as fd
from quant.research import historical_adapter as ha
from quant.research import model_evaluation, ridge_regression, statistical_baselines

HOUR = timedelta(hours=1)
START = datetime(2023, 1, 1, tzinfo=UTC)
AS_OF = START + 7 * HOUR


@pytest.fixture
def source_frames():
    """Invent seven candles, one gap, and three fully synthetic annotations."""
    evidence = (Evidence("data/verification/invented.json", "c" * 64, AS_OF),)
    manifest = AnomalyManifest(
        "synthetic-audit-v1",
        None,
        (
            Anomaly(
                START + 2 * HOUR,
                "source_discrepancy",
                ("close", "volume"),
                evidence,
                "unrated",
                "unresolved",
                "synthetic-audit-v1",
            ),
            Anomaly(
                START + 3 * HOUR,
                "shortened_close",
                ("unknown",),
                evidence,
                "unrated",
                "unresolved",
                "synthetic-audit-v1",
                recorded_source_close_at=START + 3 * HOUR + timedelta(minutes=40),
                source_close_precision="milliseconds",
            ),
            Anomaly(
                START + 4 * HOUR,
                "missing_hour",
                ("candle",),
                evidence,
                "unrated",
                "unresolved",
                "synthetic-audit-v1",
                coverage_basis="invented_checked_range",
            ),
        ),
    )
    rows = []
    for hour in (0, 1, 2, 3, 5, 6):
        close = float(100 + hour)
        rows.append(
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "timestamp": START + hour * HOUR,
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": float(10 + hour),
                "ingested_at": AS_OF + HOUR,
            }
        )
    silver = pl.DataFrame(
        rows,
        schema={
            "exchange": pl.String,
            "symbol": pl.String,
            "timeframe": pl.String,
            "timestamp": pl.Datetime("us", "UTC"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
            "ingested_at": pl.Datetime("us", "UTC"),
        },
    )
    gold = engine.calculate_features(
        silver,
        manifest,
        analysis_as_of=AS_OF,
        generated_at=AS_OF + 2 * HOUR,
        source_snapshot_sha256="a" * 64,
    )
    ledger = fd.build_origin_ledger(
        silver,
        gold,
        manifest,
        analysis_as_of=AS_OF,
        silver_sha256="a" * 64,
        gold_sha256="b" * 64,
    )
    identity = ha.SourceIdentity(
        silver_sha256="a" * 64,
        gold_sha256="b" * 64,
        manifest_sha256=manifest.sha256,
        dataset_spec_id=ledger["dataset_spec_id"][0],
        artifact_build_id="d" * 64,
        analysis_as_of=AS_OF,
        feature_version=engine.FEATURE_VERSION,
        manifest_version=manifest.manifest_version,
    )
    return silver, gold, ledger, manifest, identity


def _audit(source_frames, **replacements):
    silver, gold, ledger, manifest, identity = source_frames
    return ha.audit_frames(
        replacements.get("silver", silver),
        replacements.get("gold", gold),
        replacements.get("ledger", ledger),
        replacements.get("manifest", manifest),
        identity=replacements.get("identity", identity),
    )


def _change(frame, index, **changes):
    rows = list(frame.iter_rows(named=True))
    rows[index].update(changes)
    return pl.DataFrame(rows, schema=frame.schema, strict=True)


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _failed(audit):
    assert audit.adapter is None
    assert audit.report["status"] == "failed"
    assert audit.report["execution_ready"] is False


def test_valid_in_memory_mapping_is_not_authenticated_execution(source_frames):
    audit = _audit(source_frames)
    assert audit.adapter is not None
    assert audit.report["status"] == "blocked"
    assert audit.report["execution_ready"] is False
    assert len(audit.adapter.records) == 7
    assert len(audit.adapter.universes) == 3
    assert {item.period_id for item in audit.adapter.universes} == {
        "training_history",
        "validation",
        "test",
    }


def test_source_rows_values_and_nulls_preserved_losslessly(source_frames):
    ledger = source_frames[2]
    records = _audit(source_frames).adapter.records
    for index, (record, source) in enumerate(
        zip(records, ledger.iter_rows(named=True), strict=True)
    ):
        assert record.source_row_index == index
        assert _plain(record.source_values) == source
        assert record.origin == source["forecast_origin_utc"]
        assert record.period == source["split_id"]
        assert record.features.values == tuple(source[name] for name in engine.FEATURES)
        assert record.features.null_reasons == tuple(
            source[f"null_reason__{name}"] for name in engine.FEATURES
        )
        assert record.outcome.target == source["target_next_1h_log_return"]
        assert record.outcome.target_valid is source["target_valid"]
        assert record.outcome.invalid_reasons == tuple(source["target_null_reasons"])
        assert record.features.available_at is None
        assert record.features.decision_eligible is False


@pytest.mark.parametrize("field", ["candle", "unknown"])
def test_original_non_ohlcv_anomaly_fields_are_never_translated(source_frames, field):
    records = _audit(source_frames).adapter.records
    found = []
    for record in records:
        for annotation in (
            *record.outcome.target_endpoint_anomalies,
            *record.outcome.feature_window_anomalies,
        ):
            if field in annotation.raw["affected_fields"]:
                found.append(annotation)
                assert annotation.raw["affected_fields"] == (field,)
    assert found


def test_target_and_feature_associations_remain_separate(source_frames):
    record = _audit(source_frames).adapter.records[2]
    source = source_frames[2].row(2, named=True)
    assert [_plain(a.raw) for a in record.outcome.target_endpoint_anomalies] == source[
        "target_endpoint_anomalies"
    ]
    assert [_plain(a.raw) for a in record.outcome.feature_window_anomalies] == source[
        "involved_anomalies"
    ]
    assert all(
        a.association == "target_endpoint"
        for a in record.outcome.target_endpoint_anomalies
    )
    assert all(
        a.association == "feature_window"
        for a in record.outcome.feature_window_anomalies
    )
    # The source-discrepancy observation belongs to both distinct dependencies.
    assert any(
        target.raw == feature.raw
        for target in record.outcome.target_endpoint_anomalies
        for feature in record.outcome.feature_window_anomalies
    )


def test_unknown_source_association_is_unresolved_without_loss(source_frames):
    raw = source_frames[2].row(2, named=True)["target_endpoint_anomalies"][0]
    raw["original_extra"] = {"observed": None, "values": ["unknown", "candle"]}
    annotation = ha.associate_anomaly(
        raw, source_column="unspecified_source_annotations", source_row_index=2
    )
    assert annotation.association == "unresolved"
    assert _plain(annotation.raw) == raw
    assert annotation.raw["original_extra"]["observed"] is None


def test_nested_annotations_and_original_rows_are_immutable(source_frames):
    record = _audit(source_frames).adapter.records[2]
    with pytest.raises(TypeError):
        record.source_values["target_valid"] = False
    with pytest.raises(TypeError):
        record.source_values["target_endpoint_anomalies"][0]["severity"] = "high"
    annotation = record.outcome.target_endpoint_anomalies[0]
    with pytest.raises(TypeError):
        annotation.raw["affected_fields"][0] = "open"


def test_shortened_close_timestamp_and_invalid_reason_order_preserved(source_frames):
    records = _audit(source_frames).adapter.records
    assert records[3].source_values["recorded_source_close_at"] == (
        START + 3 * HOUR + timedelta(minutes=40)
    )
    assert records[-1].outcome.invalid_reasons == ("next_incomplete", "next_missing")
    assert records[-1].source_values["target_primary_null_reason"] == "next_missing"


def test_historical_forecast_view_contains_no_future_outcome_fields(source_frames):
    record = _audit(source_frames).adapter.records[2]
    fields = record.features.forecast_fields()
    assert fields["forecast_origin_utc"] == record.origin
    assert fields["feature_open_t"] == record.origin - HOUR
    assert not any(name.startswith("target") for name in fields)
    assert "next_candle_valid" not in fields
    assert "lane_a_sensitivity" not in fields
    assert "target_endpoint_anomalies" not in fields
    assert all(name in fields for name in engine.FEATURES)


@pytest.mark.parametrize(
    "field,value",
    [
        ("silver_sha256", "e" * 64),
        ("gold_sha256", "e" * 64),
        ("manifest_sha256", "e" * 64),
        ("dataset_spec_id", "e" * 64),
        ("feature_version", "unapproved"),
        ("manifest_version", "unapproved"),
        ("analysis_as_of", AS_OF + HOUR),
    ],
)
def test_inconsistent_source_identities_fail_closed(source_frames, field, value):
    identity = replace(source_frames[4], **{field: value})
    _failed(_audit(source_frames, identity=identity))


@pytest.mark.parametrize("source", ["silver", "gold", "ledger"])
def test_missing_schema_column_fails_closed(source_frames, source):
    frame = source_frames[("silver", "gold", "ledger").index(source)]
    _failed(_audit(source_frames, **{source: frame.drop(frame.columns[-1])}))


def test_unknown_ledger_schema_column_fails_closed(source_frames):
    ledger = source_frames[2].with_columns(pl.lit("not approved").alias("extra"))
    _failed(_audit(source_frames, ledger=ledger))


def test_reordered_feature_columns_fail_closed(source_frames):
    gold = source_frames[1]
    columns = list(gold.columns)
    a, b = (columns.index(name) for name in engine.FEATURES[:2])
    columns[a], columns[b] = columns[b], columns[a]
    _failed(_audit(source_frames, gold=gold.select(columns)))


@pytest.mark.parametrize("defect", ["duplicate", "missing", "misaligned", "reverse"])
def test_invalid_origin_timeline_fails_closed(source_frames, defect):
    ledger = source_frames[2]
    if defect == "duplicate":
        ledger = _change(
            ledger, 2, forecast_origin_utc=ledger["forecast_origin_utc"][1]
        )
    elif defect == "missing":
        ledger = ledger.filter(pl.col("forecast_origin_utc") != START + 3 * HOUR)
    elif defect == "misaligned":
        ledger = _change(
            ledger,
            2,
            forecast_origin_utc=START + 3 * HOUR + timedelta(minutes=1),
        )
    else:
        ledger = ledger.reverse()
    _failed(_audit(source_frames, ledger=ledger))


@pytest.mark.parametrize(
    "changes",
    [
        {"feature_open_t": START + HOUR},
        {"target_theoretical_close_at": START + 3 * HOUR},
        {"split_id": "test"},
        {"gold_available_at": AS_OF},
        {"gold_decision_eligible": True},
        {"research_only": False},
    ],
)
def test_temporal_period_and_pit_contract_mismatches_fail_closed(
    source_frames, changes
):
    _failed(_audit(source_frames, ledger=_change(source_frames[2], 0, **changes)))


@pytest.mark.parametrize(
    "changes",
    [
        {"target_valid": False},
        {"target_next_1h_log_return": None},
        {"target_next_1h_log_return": float("nan")},
        {"target_next_1h_log_return": 42.0},
        {"target_null_reasons": ["next_missing"]},
        {"target_primary_null_reason": "next_missing"},
        {"target_manifest_anomaly": True},
        {"feature_manifest_anomaly": True},
        {"ar_lag_valid": True},
        {"ar_lag_manifest_anomaly": True},
        {"feature_complete": True},
        {"lane_a_primary": {"sample_id": "a_primary", "target_eligible": False}},
        {
            "lane_a_sensitivity": {
                "sample_id": "a_sensitivity",
                "target_eligible": False,
            }
        },
    ],
)
def test_quality_target_and_sample_mask_mismatches_fail_closed(source_frames, changes):
    _failed(_audit(source_frames, ledger=_change(source_frames[2], 0, **changes)))


def test_valid_target_value_and_endpoint_evidence_must_match_silver_manifest(
    source_frames,
):
    ledger = source_frames[2]
    # Remove a real endpoint annotation rather than relying on its mask alone.
    _failed(
        _audit(source_frames, ledger=_change(ledger, 2, target_endpoint_anomalies=[]))
    )


def test_feature_annotations_must_match_gold_and_manifest(source_frames):
    ledger = _change(source_frames[2], 2, involved_anomalies=[])
    _failed(_audit(source_frames, ledger=ledger))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_features_fail_even_when_ledger_and_gold_agree(source_frames, value):
    gold = _change(source_frames[1], 2, normalized_range_1h=value)
    ledger = _change(source_frames[2], 2, normalized_range_1h=value)
    _failed(_audit(source_frames, gold=gold, ledger=ledger))


def test_ar_gap_remains_unavailable_without_adjacency_compression(source_frames):
    records = _audit(source_frames).adapter.records
    assert not records[4].source_values["ar_lag_valid"]
    assert not records[5].source_values["ar_lag_valid"]
    assert records[6].source_values["ar_lag_valid"]
    assert records[4].source_values["missing_hour"]
    assert records[3].outcome.target is None
    assert records[4].outcome.target is None


def test_canonical_report_deterministic_and_requires_no_files_or_execution(
    source_frames, monkeypatch
):
    before = tuple(frame.clone() for frame in source_frames[:3])

    def forbidden(*args, **kwargs):
        pytest.fail(
            "in-memory historical audit attempted I/O, feature rebuild, or execution"
        )

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
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    first = _audit(source_frames)
    second = _audit(source_frames)
    assert first.adapter is not None
    assert first.canonical_report == second.canonical_report
    assert json.loads(first.canonical_report) == first.report
    assert first.canonical_report.endswith(b"\n")
    assert first.report["execution_ready"] is False
    for expected, actual in zip(before, source_frames[:3], strict=True):
        assert expected.equals(actual)


def test_historical_adapter_cannot_bypass_synthetic_runner_guard(source_frames):
    adapter = _audit(source_frames).adapter
    with pytest.raises(ValueError, match="typed immutable fixture"):
        model_evaluation.SyntheticFixture(
            synthetic=True, features=(adapter.records[0].features,), outcomes=()
        )
    with pytest.raises(ValueError, match="typed synthetic fixture"):
        model_evaluation.run_synthetic(
            adapter,
            adapter.universes[0],
            provenance=None,
            evidence=None,
            evaluated_at_utc=AS_OF,
        )


def test_valid_hash_syntax_does_not_establish_verified_source_bytes(source_frames):
    audit = _audit(source_frames)
    proof = audit.report["provenance"]
    assert proof["hash_syntax_validated"] is True
    assert proof["file_bytes_verified"] is False
    assert proof["source_identity_matched"] is False
    assert proof["chain_complete"] is False
    assert proof["sources"] == {}
    assert audit.report["anomalies"]["evidence_completeness"] == "unverified"
    assert audit.report["anomalies"]["evidence_references_checked"] is False


def _temporary_artifact_set(root, monkeypatch):
    """Deliberately non-Parquet synthetic bytes for early integrity gates."""
    relative = "invented_build"
    directory = root / relative
    directory.mkdir()
    hashes = {}
    for name in ha.ARTIFACT_HASHES:
        data = ("invented:" + name).encode()
        (directory / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(ha, "ORIGIN_DIRECTORY", relative)
    monkeypatch.setattr(ha, "ARTIFACT_HASHES", hashes)
    return directory, hashes


def _forbid_reader_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail(
            "failed integrity gate attempted Parquet parsing or model execution"
        )

    for module, name in (
        (pl, "read_parquet"),
        (statistical_baselines, "fit_ar"),
        (statistical_baselines, "predict_mean"),
        (ridge_regression, "fit_ridge"),
        (model_evaluation, "run_synthetic"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.mark.parametrize("defect", ["missing", "extra", "wrong"])
def test_pinned_reader_rejects_incorrect_immutable_artifact_set(
    tmp_path, monkeypatch, defect
):
    directory, _ = _temporary_artifact_set(tmp_path, monkeypatch)
    if defect == "missing":
        (directory / "provenance.sha256").unlink()
    elif defect == "extra":
        (directory / "unexpected.json").write_bytes(b"invented")
    else:
        (directory / "provenance.sha256").rename(directory / "wrong-name.sha256")
    before = {str(p): p.read_bytes() for p in directory.iterdir()}
    _forbid_reader_execution(monkeypatch)
    audit = ha.audit_pinned_history(tmp_path)
    _failed(audit)
    assert "missing or unexpected" in audit.report["blocking_findings"][0]
    assert before == {str(p): p.read_bytes() for p in directory.iterdir()}


@pytest.mark.parametrize(
    "name",
    [
        "origin_ledger.parquet",
        "dataset_validation.json",
        "provenance.json",
        "provenance.sha256",
    ],
)
def test_pinned_reader_rejects_tampered_approved_bytes_before_parquet(
    tmp_path, monkeypatch, name
):
    directory, _ = _temporary_artifact_set(tmp_path, monkeypatch)
    (directory / name).write_bytes(b"tampered invented bytes")
    before = {str(p): p.read_bytes() for p in directory.iterdir()}
    _forbid_reader_execution(monkeypatch)
    audit = ha.audit_pinned_history(tmp_path)
    _failed(audit)
    assert "pinned source hash mismatch" in audit.report["blocking_findings"][0]
    assert name in audit.report["blocking_findings"][0]
    assert before == {str(p): p.read_bytes() for p in directory.iterdir()}


def test_pinned_reader_missing_source_fails_without_output_or_execution(
    tmp_path, monkeypatch
):
    directory, _ = _temporary_artifact_set(tmp_path, monkeypatch)
    before = {str(p): p.read_bytes() for p in directory.iterdir()}
    _forbid_reader_execution(monkeypatch)
    audit = ha.audit_pinned_history(tmp_path)
    _failed(audit)
    assert audit.report["blocking_findings"] == ["FileNotFoundError"]
    assert before == {str(p): p.read_bytes() for p in directory.iterdir()}
    assert {p.name for p in tmp_path.iterdir()} == {directory.name}


def test_pinned_reader_authenticates_only_synthetic_temp_bytes_read_only(
    source_frames, tmp_path, monkeypatch
):
    """Temporary invented artifacts exercise the complete reader, not history."""
    silver, _, _, manifest, _ = source_frames
    silver_bytes = fd._parquet_bytes(silver)
    silver_sha = hashlib.sha256(silver_bytes).hexdigest()
    gold = engine.calculate_features(
        silver,
        manifest,
        analysis_as_of=AS_OF,
        generated_at=AS_OF + 2 * HOUR,
        source_snapshot_sha256=silver_sha,
    )
    gold_bytes = fd._parquet_bytes(gold)
    gold_sha = hashlib.sha256(gold_bytes).hexdigest()
    ledger = fd.build_origin_ledger(
        silver,
        gold,
        manifest,
        analysis_as_of=AS_OF,
        silver_sha256=silver_sha,
        gold_sha256=gold_sha,
    )
    directory = fd.publish_ledger(
        ledger,
        root=tmp_path / "invented_publication",
        silver_rows=silver.height,
        silver_sha256=silver_sha,
        gold_sha256=gold_sha,
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
    monkeypatch.setattr(fd, "SILVER_SHA256", silver_sha)
    monkeypatch.setattr(fd, "GOLD_SHA256", gold_sha)
    monkeypatch.setattr(fd, "MANIFEST_SHA256", manifest.sha256)
    monkeypatch.setattr(fd, "ANALYSIS_AS_OF", AS_OF)
    monkeypatch.setattr(ha, "SPEC_ID", directory.parent.name)
    monkeypatch.setattr(ha, "BUILD_ID", directory.name)
    monkeypatch.setattr(ha, "ORIGIN_DIRECTORY", str(directory.relative_to(tmp_path)))
    monkeypatch.setattr(
        ha,
        "ARTIFACT_HASHES",
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.iterdir()
        },
    )
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }

    def forbidden(*args, **kwargs):
        pytest.fail(
            "read-only historical audit attempted a write, rebuild, or model call"
        )

    for module, name in (
        (statistical_baselines, "fit_ar"),
        (ridge_regression, "fit_ridge"),
        (model_evaluation, "run_synthetic"),
        (fd, "publish_ledger"),
        (fd, "build_origin_ledger"),
        (engine, "calculate_features"),
        (Path, "write_bytes"),
        (Path, "write_text"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    audit = ha.audit_pinned_history(tmp_path)
    assert audit.adapter is not None, audit.report
    assert audit.report["status"] == "ready_for_architect_review"
    assert audit.report["execution_ready"] is False
    assert audit.report["provenance"]["file_bytes_verified"] is True
    assert audit.report["provenance"]["source_identity_matched"] is True
    assert audit.report["provenance"]["chain_complete"] is True
    assert len(audit.report["provenance"]["sources"]) == 7
    assert audit.report["point_in_time_verified"] is False
    assert audit.report["anomalies"]["evidence_completeness"] == "unverified"
    assert "4a_quality_projection_policy_deferred" in audit.report["execution_blockers"]
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
