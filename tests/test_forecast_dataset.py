"""Synthetic-only contract checks for the research-origin dataset builder."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from quant.features.engine import FEATURES, calculate_features
from quant.features.manifest import Anomaly, AnomalyManifest, Evidence
from quant.research.forecast_dataset import (
    ANALYSIS_AS_OF,
    DATASET_CONTRACT_VERSION,
    GOLD_SHA256,
    LEDGER_SCHEMA,
    MANIFEST_SHA256,
    PROTOCOL_VERSION,
    SILVER_SHA256,
    TARGET_REASON_PRIORITY,
    artifact_build_id,
    build_origin_ledger,
    canonical_json,
    dataset_spec_id,
    forecast_side_view,
    publish_ledger,
    run_pinned_dataset,
    split_id,
    target_audit,
    validation_report,
    verify_published,
)

HOUR = timedelta(hours=1)
START = datetime(2023, 1, 1, tzinfo=UTC)
AS_OF = START + 7 * HOUR
SOURCE_SHA = "a" * 64
GOLD_SHA = "b" * 64


def _manifest() -> AnomalyManifest:
    evidence = (Evidence("data/verification/synthetic.json", "c" * 64, AS_OF),)
    return AnomalyManifest(
        "synthetic-v1",
        None,
        (
            Anomaly(
                START + 2 * HOUR,
                "source_discrepancy",
                ("close", "volume"),
                evidence,
                "unrated",
                "unresolved",
                "synthetic-v1",
            ),
            Anomaly(
                START + 3 * HOUR,
                "shortened_close",
                ("unknown",),
                evidence,
                "unrated",
                "unresolved",
                "synthetic-v1",
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
                "synthetic-v1",
                coverage_basis="synthetic_checked_range",
            ),
        ),
    )


def _silver() -> pl.DataFrame:
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
    return pl.DataFrame(
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


@pytest.fixture
def inputs() -> tuple[pl.DataFrame, pl.DataFrame, AnomalyManifest]:
    silver = _silver()
    manifest = _manifest()
    gold = calculate_features(
        silver,
        manifest,
        analysis_as_of=AS_OF,
        generated_at=AS_OF + 2 * HOUR,
        source_snapshot_sha256=SOURCE_SHA,
    )
    return silver, gold, manifest


@pytest.fixture
def ledger(inputs) -> pl.DataFrame:
    silver, gold, manifest = inputs
    return build_origin_ledger(
        silver,
        gold,
        manifest,
        analysis_as_of=AS_OF,
        silver_sha256=SOURCE_SHA,
        gold_sha256=GOLD_SHA,
    )


def _rows(ledger: pl.DataFrame) -> list[dict]:
    return list(ledger.iter_rows(named=True))


def test_exact_target_formula_and_origin_alignment(ledger):
    first = _rows(ledger)[0]
    assert first["target_next_1h_log_return"] == pytest.approx(math.log(101 / 100))
    assert first["feature_open_t"] == START
    assert first["forecast_origin_utc"] == START + HOUR
    assert first["target_open_at"] == START + HOUR
    assert first["target_theoretical_close_at"] == START + 2 * HOUR
    assert first["feature_theoretical_close_at"] == START + HOUR


@pytest.mark.parametrize(
    "hour,reason", [(3, "next_missing"), (4, "current_missing"), (6, "next_missing")]
)
def test_missing_candle_target_reasons(ledger, hour, reason):
    row = _rows(ledger)[hour]
    assert not row["target_valid"]
    assert row["target_next_1h_log_return"] is None
    assert reason in row["target_null_reasons"]


def test_nonconsecutive_observed_candle_does_not_bridge_gap(ledger):
    before_gap = _rows(ledger)[3]
    assert before_gap["current_candle_present"]
    assert not before_gap["next_candle_present"]
    assert not before_gap["consecutive_opens"]
    assert "nonconsecutive_opens" in before_gap["target_null_reasons"]


def test_incomplete_final_target_and_priority(ledger):
    final = _rows(ledger)[-1]
    assert final["target_null_reasons"] == ["next_incomplete", "next_missing"]
    assert final["target_primary_null_reason"] == "next_missing"
    assert final["next_candle_complete"] is False


def test_invalid_closes_and_source_failure_reason_overlap():
    current = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 0.0, "volume": 1.0}
    following = {
        "open": 101.0,
        "high": 102.0,
        "low": 100.0,
        "close": 101.0,
        "volume": 1.0,
    }
    value, reasons = target_audit(
        current,
        following,
        current_open=START,
        next_observed_open=START + HOUR,
        analysis_as_of=AS_OF,
    )
    assert value is None
    assert reasons == ["current_invalid_close", "current_invalid_source"]
    assert min(reasons, key=TARGET_REASON_PRIORITY.index) == "current_invalid_source"


def test_nonfinite_close_reasons():
    following = {
        "open": 101.0,
        "high": 102.0,
        "low": 100.0,
        "close": float("nan"),
        "volume": 1.0,
    }
    value, reasons = target_audit(
        _silver().row(0, named=True),
        following,
        current_open=START,
        next_observed_open=START + HOUR,
        analysis_as_of=AS_OF,
    )
    assert value is None
    assert "next_invalid_source" in reasons
    assert "next_invalid_close" in reasons


def test_exact_utc_key_join_not_physical_row_shift(ledger):
    rows = _rows(ledger)
    assert rows[4]["missing_hour"]
    assert rows[5]["target_valid"]
    assert rows[5]["target_next_1h_log_return"] == pytest.approx(math.log(106 / 105))
    assert rows[3]["target_next_1h_log_return"] is None


def test_gold_features_nulls_and_provenance_preserved(inputs, ledger):
    _, gold, _ = inputs
    for gold_row, row in zip(
        gold.iter_rows(named=True), ledger.iter_rows(named=True), strict=True
    ):
        for feature in FEATURES:
            assert row[feature] == gold_row[feature]
            assert row[f"null_reason__{feature}"] == gold_row[f"null_reason__{feature}"]
        for field in (
            "quality_flags",
            "involved_anomalies",
            "anomaly_involved_features",
            "value_sensitive_features",
            "source_discrepancy_fields",
            "recorded_source_close_at",
            "source_present",
            "missing_hour",
        ):
            assert row[field] == gold_row[field]
        assert row["gold_available_at"] == gold_row["available_at"]
        assert row["gold_decision_eligible"] == gold_row["decision_eligible"]
        assert row["gold_generated_at"] == gold_row["generated_at"]


def test_feature_target_and_ar_masks_are_distinct(ledger):
    rows = _rows(ledger)
    assert rows[0]["target_valid"] and not rows[0]["feature_complete"]
    assert rows[3]["feature_manifest_anomaly"] and not rows[3]["target_valid"]
    assert rows[5]["target_valid"] and not rows[5]["ar_lag_valid"]
    assert rows[6]["ar_lag_valid"]


def test_ar_lag_requires_exact_previous_hour_and_closed_current(ledger):
    rows = _rows(ledger)
    assert not rows[0]["ar_lag_valid"]  # no candle at t-1h
    assert rows[1]["ar_lag_valid"]  # exact t-1h and t, closed at origin
    assert rows[1]["forecast_origin_utc"] == rows[1]["feature_open_t"] + HOUR
    assert rows[1]["feature_theoretical_close_at"] == rows[1]["forecast_origin_utc"]
    assert not rows[4]["ar_lag_valid"]  # current candle absent
    assert not rows[5]["ar_lag_valid"]  # previous hour absent; no row shifting
    assert rows[6]["ar_lag_valid"]  # two new consecutive closed candles
    assert rows[6]["current_candle_complete"]


def test_ar_lag_ignores_future_target_candle_and_anomaly(ledger):
    row = _rows(ledger)[1]
    assert row["ar_lag_valid"]
    assert not row["ar_lag_manifest_anomaly"]
    assert row["target_manifest_anomaly"]  # only next candle is anomalous
    assert row["target_endpoint_anomalies"][0]["timestamp"] == START + 2 * HOUR


def test_invalid_previous_ar_lag_candle_fails_source_audit(inputs):
    silver, gold, manifest = inputs
    # At t=1h the t-1h candle would be invalid. The whole source must fail,
    # rather than publishing a ledger that treats it as an AR lag input.
    malformed = silver.with_columns(
        pl.when(pl.col("timestamp") == START)
        .then(pl.lit(0.0))
        .otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(ValueError, match="Silver"):
        build_origin_ledger(
            malformed,
            gold,
            manifest,
            analysis_as_of=AS_OF,
            silver_sha256=SOURCE_SHA,
            gold_sha256=GOLD_SHA,
        )


def test_incomplete_ar_lag_current_candle_fails_source_audit(inputs):
    silver, gold, manifest = inputs
    with pytest.raises(ValueError, match="incomplete source candle"):
        build_origin_ledger(
            silver,
            gold,
            manifest,
            analysis_as_of=AS_OF - HOUR,
            silver_sha256=SOURCE_SHA,
            gold_sha256=GOLD_SHA,
        )


def test_primary_and_sensitivity_target_eligibility(ledger):
    rows = _rows(ledger)
    assert rows[1]["target_valid"]
    assert rows[1]["target_manifest_anomaly"]
    assert rows[1]["lane_a_primary"] == {
        "sample_id": "a_primary",
        "target_eligible": True,
    }
    assert rows[1]["lane_a_sensitivity"]["target_eligible"] is False
    assert rows[0]["lane_a_sensitivity"]["target_eligible"] is True


def test_target_endpoint_anomalies_and_field_sensitivity(ledger):
    rows = _rows(ledger)
    assert rows[1]["target_endpoint_anomalies"][0]["timestamp"] == START + 2 * HOUR
    assert rows[1]["target_value_sensitive"]
    assert rows[2]["target_value_sensitive"]
    assert not rows[3]["target_value_sensitive"]  # no valid value across the gap
    assert rows[2]["ar_lag_manifest_anomaly"]


def test_target_value_sensitivity_requires_calculable_target(ledger):
    rows = _rows(ledger)
    assert rows[2]["target_valid"] and rows[2]["target_value_sensitive"]
    assert rows[3]["target_manifest_anomaly"]  # shortened close and missing next
    assert not rows[3]["target_valid"]
    assert not rows[3]["target_value_sensitive"]
    assert rows[4]["target_manifest_anomaly"]  # missing current endpoint
    assert not rows[4]["target_value_sensitive"]
    assert rows[3]["lane_a_primary"]["target_eligible"] is False
    assert rows[3]["lane_a_sensitivity"]["target_eligible"] is False


def test_forecast_side_view_excludes_future_outcome_metadata(ledger):
    view = forecast_side_view(ledger)
    assert list(view.columns) == list(dict.fromkeys(view.columns))
    assert "target_next_1h_log_return" not in view.columns
    assert "target_endpoint_anomalies" not in view.columns
    assert "target_manifest_anomaly" not in view.columns
    assert "next_candle_present" not in view.columns
    assert "lane_a_sensitivity" not in view.columns
    assert set(FEATURES) <= set(view.columns)


@pytest.mark.parametrize(
    "origin,expected",
    [
        (datetime(2021, 1, 1, 0, tzinfo=UTC), "outside_approved_evaluation_window"),
        (datetime(2021, 1, 1, 1, tzinfo=UTC), "training_history"),
        (datetime(2023, 12, 31, 23, tzinfo=UTC), "training_history"),
        (datetime(2024, 1, 1, tzinfo=UTC), "validation"),
        (datetime(2024, 12, 31, 23, tzinfo=UTC), "validation"),
        (datetime(2025, 1, 1, tzinfo=UTC), "test"),
        (datetime(2026, 10, 20, 12, tzinfo=UTC), "test"),
        (ANALYSIS_AS_OF, "outside_approved_evaluation_window"),
    ],
)
def test_exact_split_boundaries(origin, expected):
    assert split_id(origin) == expected


def test_unique_sorted_hourly_origin_keys_and_schema(ledger):
    assert ledger.schema == LEDGER_SCHEMA
    origins = ledger["forecast_origin_utc"].to_list()
    assert origins == sorted(set(origins))
    assert all(right - left == HOUR for left, right in zip(origins, origins[1:]))
    assert all(row["research_only"] for row in ledger.iter_rows(named=True))
    assert all(
        row["gold_decision_eligible"] is False for row in ledger.iter_rows(named=True)
    )


def test_dataset_spec_identity_excludes_build_information(inputs, ledger):
    _, gold, manifest = inputs
    params = dict(
        silver_sha256=SOURCE_SHA,
        gold_sha256=GOLD_SHA,
        manifest_sha256=manifest.sha256,
        analysis_as_of=AS_OF,
        feature_version=gold["feature_version"][0],
        manifest_version=manifest.manifest_version,
    )
    identity = dataset_spec_id(**params)
    assert identity == ledger["dataset_spec_id"][0]
    assert dataset_spec_id(**params) == identity
    assert dataset_spec_id(**(params | {"gold_sha256": "d" * 64})) != identity


def test_artifact_build_identity_changes_with_code_and_versions(ledger):
    spec = ledger["dataset_spec_id"][0]
    first = artifact_build_id(
        spec,
        code_revision="1" * 64,
        dependency_versions={"python": "3.12", "polars": "2.0"},
    )
    assert first == artifact_build_id(
        spec,
        code_revision="1" * 64,
        dependency_versions={"polars": "2.0", "python": "3.12"},
    )
    assert first != artifact_build_id(
        spec,
        code_revision="2" * 64,
        dependency_versions={"python": "3.12", "polars": "2.0"},
    )


def test_canonical_json_sorted_compact_stable():
    expected = b'{"a":"2026-10-20T13:00:00.000000Z","b":2}\n'
    assert canonical_json({"b": 2, "a": "2026-10-20T13:00:00.000000Z"}) == expected
    assert canonical_json({"a": "2026-10-20T13:00:00.000000Z", "b": 2}) == expected


def _publish(ledger: pl.DataFrame, root: Path) -> Path:
    return publish_ledger(
        ledger,
        root=root,
        silver_rows=6,
        silver_sha256=SOURCE_SHA,
        gold_sha256=GOLD_SHA,
        manifest_sha256=_manifest().sha256,
        code_revision="1" * 64,
        dependency_versions={"python": "3.12", "polars": "2.0"},
    )


def test_artifact_hashes_and_idempotent_rerun(ledger, tmp_path):
    target = _publish(ledger, tmp_path)
    first = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()
    }
    assert _publish(ledger, tmp_path) == target
    assert first == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()
    }
    provenance = json.loads((target / "provenance.json").read_bytes())
    for name, digest in provenance["artifact_sha256"].items():
        assert first[name] == digest
    assert (target / "provenance.sha256").read_text().strip() == first[
        "provenance.json"
    ]
    verify_published(target, {p.name: p.read_bytes() for p in target.iterdir()})
    assert pl.read_parquet(target / "origin_ledger.parquet").equals(
        ledger, null_equal=True
    )


def test_conflicting_immutable_build_rejected_without_overwrite(ledger, tmp_path):
    target = _publish(ledger, tmp_path)
    path = target / "dataset_validation.json"
    original = path.read_bytes()
    path.write_bytes(b"conflict\n")
    with pytest.raises(ValueError, match="conflicting bytes"):
        _publish(ledger, tmp_path)
    assert path.read_bytes() == b"conflict\n"
    assert original != path.read_bytes()


@pytest.mark.parametrize(
    "filename",
    ("origin_ledger.parquet", "provenance.json", "provenance.sha256"),
)
def test_tampered_immutable_artifact_fails_closed(ledger, tmp_path, filename):
    target = _publish(ledger, tmp_path)
    artifact = target / filename
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"tampered")
    with pytest.raises(ValueError, match="conflicting bytes"):
        _publish(ledger, tmp_path)
    assert artifact.read_bytes() == original + b"tampered"
    assert {path.name for path in target.iterdir()} == {
        "origin_ledger.parquet",
        "dataset_validation.json",
        "provenance.json",
        "provenance.sha256",
    }


def test_missing_immutable_artifact_fails_closed(ledger, tmp_path):
    target = _publish(ledger, tmp_path)
    missing = target / "provenance.json"
    missing.unlink()  # synthetic tmp_path only; never the pinned local build
    with pytest.raises(ValueError, match="missing or unexpected files"):
        _publish(ledger, tmp_path)
    assert not missing.exists()


def test_unexpected_immutable_artifact_fails_closed(ledger, tmp_path):
    target = _publish(ledger, tmp_path)
    unexpected = target / "unexpected.txt"
    unexpected.write_bytes(b"not part of the immutable build\n")
    with pytest.raises(ValueError, match="missing or unexpected files"):
        _publish(ledger, tmp_path)
    assert unexpected.read_bytes() == b"not part of the immutable build\n"


def test_source_validation_rejects_invalid_and_duplicate_rows(inputs):
    silver, gold, manifest = inputs
    malformed = silver.with_columns(
        pl.when(pl.col("timestamp") == START)
        .then(pl.lit(-1.0))
        .otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(ValueError, match="Silver"):
        build_origin_ledger(
            malformed,
            gold,
            manifest,
            analysis_as_of=AS_OF,
            silver_sha256=SOURCE_SHA,
            gold_sha256=GOLD_SHA,
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        build_origin_ledger(
            pl.concat([silver, silver.head(1)]),
            gold,
            manifest,
            analysis_as_of=AS_OF,
            silver_sha256=SOURCE_SHA,
            gold_sha256=GOLD_SHA,
        )


def test_gold_identity_or_presence_mismatch_rejected(inputs):
    silver, gold, manifest = inputs
    altered = gold.with_columns(pl.lit("d" * 64).alias("source_snapshot_sha256"))
    with pytest.raises(ValueError, match="digest"):
        build_origin_ledger(
            silver,
            altered,
            manifest,
            analysis_as_of=AS_OF,
            silver_sha256=SOURCE_SHA,
            gold_sha256=GOLD_SHA,
        )


def test_pinned_input_sha_mismatch_fails_before_parquet_read(tmp_path):
    root = tmp_path
    silver = root / "data/silver/binance/1h/BTC-USDT.parquet"
    silver.parent.mkdir(parents=True)
    silver.write_bytes(b"not the pinned bytes")
    with pytest.raises(ValueError, match="Silver pinned SHA-256 mismatch"):
        run_pinned_dataset(root)


def test_validation_report_is_nonpredictive(ledger):
    report = validation_report(
        ledger,
        silver_rows=6,
        silver_sha256=SOURCE_SHA,
        gold_sha256=GOLD_SHA,
        manifest_sha256=_manifest().sha256,
    )
    assert report["origin_rows"] == 7
    assert report["gold_missing_hours"] == 1
    assert report["valid_targets"] + report["null_targets"] == 7
    assert report["a_sensitivity_target_eligible"] < report["a_primary_target_eligible"]
    assert not any(name in report for name in ("rmse", "forecast", "score", "refit"))


def test_no_model_or_forecast_artifacts(ledger, tmp_path):
    target = _publish(ledger, tmp_path)
    assert {path.name for path in target.iterdir()} == {
        "origin_ledger.parquet",
        "dataset_validation.json",
        "provenance.json",
        "provenance.sha256",
    }
    assert DATASET_CONTRACT_VERSION == "pqta-003b-origin-ledger-v1"
    assert PROTOCOL_VERSION == "qnt-003d-design-v1"


def test_protected_inputs_are_not_written(inputs, tmp_path):
    silver, gold, manifest = inputs
    before = (silver.to_dicts(), gold.to_dicts(), manifest.to_bytes())
    ledger = build_origin_ledger(
        silver,
        gold,
        manifest,
        analysis_as_of=AS_OF,
        silver_sha256=SOURCE_SHA,
        gold_sha256=GOLD_SHA,
    )
    _publish(ledger, tmp_path)
    assert (silver.to_dicts(), gold.to_dicts(), manifest.to_bytes()) == before
    assert SILVER_SHA256 != GOLD_SHA256 != MANIFEST_SHA256
