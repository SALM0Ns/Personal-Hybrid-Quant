"""Synthetic, offline QNT-002B feature and anomaly-manifest contracts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from statistics import stdev

import duckdb
import polars as pl
import pytest

from quant.features.engine import FEATURE_VERSION, FEATURES, calculate_features
from quant.features.manifest import Anomaly, AnomalyManifest, Evidence
from quant.features.pipeline import prepare_feature_snapshot
from quant.ingestion.storage import SILVER_SCHEMA

START = datetime(2021, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
GENERATED = datetime(2026, 1, 1, tzinfo=UTC)
SOURCE_DIGEST = "a" * 64
EVIDENCE_DIGEST = hashlib.sha256(b"synthetic archive").hexdigest()


def silver(
    count: int = 200,
    *,
    missing: frozenset[int] = frozenset(),
    prices: list[float] | None = None,
    volumes: dict[int, float] | None = None,
    unknown_observed: frozenset[int] = frozenset(),
) -> pl.DataFrame:
    rows = []
    for index in range(count):
        if index in missing:
            continue
        close = prices[index] if prices else 100.0 + index * 0.1
        rows.append(
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "timestamp": START + index * HOUR,
                "open": close,
                "high": close + 2,
                "low": close - 1,
                "close": close,
                "volume": (volumes or {}).get(index, 10.0),
                "ingested_at": (
                    None if index in unknown_observed else START + (index + 2) * HOUR
                ),
            }
        )
    return pl.DataFrame(rows, schema=SILVER_SCHEMA)


def evidence(observed_at: datetime | None = GENERATED) -> Evidence:
    return Evidence("synthetic://archive", EVIDENCE_DIGEST, observed_at)


def anomaly(
    index: int,
    kind: str,
    fields: tuple[str, ...],
    *,
    observed_at: datetime | None = GENERATED,
) -> Anomaly:
    return Anomaly(
        timestamp=START + index * HOUR,
        anomaly_type=kind,
        affected_fields=fields,
        source_evidence=(evidence(observed_at),),
        severity="review",
        review_status="unresolved",
        manifest_version="v1",
        recorded_source_close_at=(
            START + index * HOUR + timedelta(minutes=40)
            if kind == "shortened_close"
            else None
        ),
        source_close_precision="milliseconds" if kind == "shortened_close" else None,
        coverage_basis="verified archive and Silver gap"
        if kind == "missing_hour"
        else None,
    )


def manifest(
    *records: Anomaly, version_available_at: datetime | None = GENERATED
) -> AnomalyManifest:
    return AnomalyManifest("v1", version_available_at, records)


def calculate(
    frame: pl.DataFrame, registry: AnomalyManifest | None = None
) -> pl.DataFrame:
    return calculate_features(
        frame,
        registry or manifest(),
        analysis_as_of=START + 1_000 * HOUR,
        generated_at=GENERATED,
        source_snapshot_sha256=SOURCE_DIGEST,
    )


def row(frame: pl.DataFrame, index: int) -> dict:
    return frame.row(index, named=True)


def test_exact_feature_formulas_and_float64_outputs() -> None:
    prices = [100 * 1.01**index for index in range(170)]
    result = calculate(silver(170, prices=prices))
    actual = row(result, 168)
    assert actual["log_return_1h"] == pytest.approx(math.log(1.01))
    assert actual["momentum_24h"] == pytest.approx(prices[168] / prices[144] - 1)
    assert actual["momentum_168h"] == pytest.approx(prices[168] / prices[0] - 1)
    assert actual["normalized_range_1h"] == pytest.approx(3 / prices[168])
    assert actual["volume_change_1h"] == 0
    assert actual["volatility_24h"] == pytest.approx(0, abs=1e-14)
    assert actual["volatility_168h"] == pytest.approx(0, abs=1e-14)
    assert all(result.schema[name] == pl.Float64 for name in FEATURES)


def test_sample_standard_deviation_and_simple_momentum() -> None:
    prices = [100.0]
    for index in range(1, 170):
        prices.append(prices[-1] * math.exp(0.01 if index % 2 else -0.02))
    actual = row(calculate(silver(170, prices=prices)), 168)
    returns = [math.log(prices[index] / prices[index - 1]) for index in range(1, 169)]
    assert actual["volatility_24h"] == pytest.approx(stdev(returns[-24:]))
    assert actual["volatility_168h"] == pytest.approx(stdev(returns))
    assert actual["momentum_24h"] == pytest.approx(math.expm1(sum(returns[-24:])))
    assert actual["momentum_168h"] == pytest.approx(math.expm1(sum(returns)))
    assert actual["momentum_24h"] != pytest.approx(sum(returns[-24:]))


def test_close_denominator_not_open_denominator() -> None:
    frame = silver(2).with_columns(
        pl.when(pl.col("timestamp") == START + HOUR)
        .then(pl.lit(101.0))
        .otherwise(pl.col("open"))
        .alias("open")
    )
    actual = row(calculate(frame), 1)
    assert actual["normalized_range_1h"] == pytest.approx(3 / 100.1)
    assert actual["normalized_range_1h"] != pytest.approx(3 / 101)


def test_utc_availability_and_processing_time_are_distinct() -> None:
    result = calculate(silver(170))
    actual = row(result, 168)
    assert actual["timestamp"] == START + 168 * HOUR
    assert actual["candle_end_at"] == START + 169 * HOUR
    assert actual["max_source_ingested_at"] == START + 170 * HOUR
    assert actual["quality_evidence_available_at"] == GENERATED
    assert actual["available_at"] == GENERATED
    assert actual["generated_at"] == GENERATED
    assert actual["availability_basis"] == "local_observation_plus_quality_evidence"
    assert actual["decision_eligible"]


def test_unknown_availability_fails_closed_without_erasing_values() -> None:
    unknown_manifest = row(
        calculate(silver(170), manifest(version_available_at=None)), 168
    )
    assert unknown_manifest["log_return_1h"] is not None
    assert unknown_manifest["available_at"] is None
    assert not unknown_manifest["decision_eligible"]
    assert "unknown_availability" in unknown_manifest["quality_flags"]
    unknown_source = row(calculate(silver(170, unknown_observed=frozenset({0}))), 168)
    assert unknown_source["max_source_ingested_at"] is None
    assert unknown_source["available_at"] is None
    assert not unknown_source["decision_eligible"]
    unknown_evidence = row(
        calculate(
            silver(170),
            manifest(anomaly(168, "source_discrepancy", ("close",), observed_at=None)),
        ),
        168,
    )
    assert unknown_evidence["quality_evidence_available_at"] is None
    assert unknown_evidence["available_at"] is None
    assert unknown_evidence["log_return_1h"] is not None
    assert not unknown_evidence["decision_eligible"]


def test_later_anomaly_evidence_delays_availability() -> None:
    later = GENERATED + HOUR
    registry = manifest(
        anomaly(168, "source_discrepancy", ("close",), observed_at=later)
    )
    result = calculate_features(
        silver(170),
        registry,
        analysis_as_of=START + 1_000 * HOUR,
        generated_at=later,
        source_snapshot_sha256=SOURCE_DIGEST,
    )
    actual = row(result, 168)
    assert actual["quality_evidence_available_at"] == later
    assert actual["available_at"] == later
    assert actual["generated_at"] == later
    assert not actual["decision_eligible"]
    assert actual["quality_flags"] == sorted(actual["quality_flags"])
    assert actual["involved_anomalies"][0]["evidence_references"] == [
        "synthetic://archive"
    ]


def test_processing_time_cannot_predate_known_inputs() -> None:
    with pytest.raises(ValueError, match="source observation"):
        calculate_features(
            silver(2),
            manifest(),
            analysis_as_of=START + 1_000 * HOUR,
            generated_at=START + HOUR,
            source_snapshot_sha256=SOURCE_DIGEST,
        )
    with pytest.raises(ValueError, match="anomaly evidence"):
        calculate_features(
            silver(2),
            manifest(),
            analysis_as_of=START + 1_000 * HOUR,
            generated_at=GENERATED - HOUR,
            source_snapshot_sha256=SOURCE_DIGEST,
        )


def test_missing_hour_and_warmup_restart_without_filling() -> None:
    result = calculate(silver(350, missing=frozenset({170})))
    missing = row(result, 170)
    assert missing["missing_hour"] and not missing["source_present"]
    assert all(missing[name] is None for name in FEATURES)
    assert missing["null_reason__normalized_range_1h"] == "missing_candle"
    first_after = row(result, 171)
    assert first_after["normalized_range_1h"] is not None
    assert first_after["log_return_1h"] is None
    assert first_after["null_reason__log_return_1h"] == "gap_in_window"
    assert row(result, 194)["volatility_24h"] is None
    assert row(result, 195)["volatility_24h"] is not None
    assert row(result, 338)["volatility_168h"] is None
    assert row(result, 339)["volatility_168h"] is not None
    assert row(result, 339)["decision_eligible"]


def test_null_reason_priority_and_zero_volume() -> None:
    result = calculate(silver(4, volumes={0: 0, 1: 0, 2: 4, 3: 0}))
    assert row(result, 0)["null_reason__volume_change_1h"] == "insufficient_history"
    assert row(result, 1)["null_reason__volume_change_1h"] == "zero_denominator"
    assert row(result, 2)["null_reason__volume_change_1h"] == "zero_denominator"
    assert row(result, 3)["volume_change_1h"] == -1
    assert not row(result, 3)["decision_eligible"]
    gap = calculate(silver(4, missing=frozenset({1}), volumes={0: 0}))
    assert row(gap, 2)["null_reason__volume_change_1h"] == "gap_in_window"


def test_discrepancy_exact_dependency_and_field_sensitivity() -> None:
    result = calculate(
        silver(345), manifest(anomaly(175, "source_discrepancy", ("close", "volume")))
    )
    at = row(result, 175)
    next_row = row(result, 176)
    assert at["source_discrepancy_at_t"]
    assert at["source_discrepancy_fields"] == ["close", "volume"]
    assert at["anomaly_involved_features"] == list(FEATURES)
    assert at["value_sensitive_features"] == list(FEATURES)
    assert next_row["log_return_1h"] is not None
    assert "log_return_1h" in next_row["value_sensitive_features"]
    assert "volume_change_1h" in next_row["value_sensitive_features"]
    assert "normalized_range_1h" not in next_row["anomaly_involved_features"]
    assert "momentum_24h" in next_row["anomaly_involved_features"]
    assert "momentum_24h" not in next_row["value_sensitive_features"]
    assert "momentum_24h" in row(result, 199)["value_sensitive_features"]
    assert "momentum_168h" in row(result, 343)["value_sensitive_features"]
    assert "volatility_24h" not in row(result, 200)["anomaly_involved_features"]
    assert at["available_at"] is not None and not at["decision_eligible"]


def test_volume_only_discrepancy_is_not_price_sensitive() -> None:
    at = row(
        calculate(
            silver(170), manifest(anomaly(168, "source_discrepancy", ("volume",)))
        ),
        168,
    )
    assert at["value_sensitive_features"] == ["volume_change_1h"]
    assert at["anomaly_involved_features"] == list(FEATURES)


def test_unknown_disputed_field_is_conservatively_sensitive() -> None:
    result = calculate(
        silver(180), manifest(anomaly(175, "source_discrepancy", ("unknown",)))
    )
    assert "momentum_24h" in row(result, 176)["value_sensitive_features"]
    assert "momentum_168h" in row(result, 176)["value_sensitive_features"]


def test_shortened_close_and_missing_manifest_record_propagate() -> None:
    shortened = anomaly(169, "shortened_close", ("unknown",))
    absent = anomaly(170, "missing_hour", ("candle",))
    result = calculate(
        silver(175, missing=frozenset({170})), manifest(shortened, absent)
    )
    at = row(result, 169)
    assert at["shortened_close_at_t"]
    assert at["recorded_source_close_at"] == START + 169 * HOUR + timedelta(minutes=40)
    assert "normalized_range_1h" in at["value_sensitive_features"]
    gap = row(result, 170)
    assert gap["null_reason__log_return_1h"] == "missing_candle"
    assert "log_return_1h" in gap["anomaly_involved_features"]
    assert gap["value_sensitive_features"] == []
    assert len(gap["involved_anomalies"]) == 2
    assert not gap["decision_eligible"]


def test_manifest_canonical_digest_and_round_trip() -> None:
    first = anomaly(2, "source_discrepancy", ("volume", "close"))
    second = anomaly(1, "missing_hour", ("candle",))
    left = manifest(first, second)
    right = manifest(second, first)
    assert left.sha256 == right.sha256
    assert left.to_bytes() == right.to_bytes()
    assert AnomalyManifest.from_bytes(left.to_bytes()).sha256 == left.sha256
    assert [item.timestamp for item in left.ordered_records()] == [
        START + HOUR,
        START + 2 * HOUR,
    ]


def test_manifest_schema_rejects_bad_evidence_and_duplicate_records() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        Evidence("synthetic://bad", "abc", GENERATED)
    with pytest.raises(ValueError, match="predates candle closure"):
        anomaly(1, "source_discrepancy", ("close",), observed_at=START)
    duplicate = anomaly(1, "source_discrepancy", ("close",))
    with pytest.raises(ValueError, match="duplicate"):
        manifest(duplicate, duplicate)
    payload = manifest().to_dict()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="root schema"):
        AnomalyManifest.from_dict(payload)
    with pytest.raises(ValueError, match="canonical serialization"):
        AnomalyManifest.from_bytes(json.dumps(manifest().to_dict()).encode())
    with pytest.raises(ValueError, match="manifest version"):
        AnomalyManifest("v2", GENERATED, (duplicate,))


def test_manifest_presence_must_match_silver() -> None:
    with pytest.raises(ValueError, match="conflicts with Silver"):
        calculate(silver(3), manifest(anomaly(1, "missing_hour", ("candle",))))
    with pytest.raises(ValueError, match="conflicts with Silver"):
        calculate(
            silver(3, missing=frozenset({1})),
            manifest(anomaly(1, "source_discrepancy", ("close",))),
        )


@pytest.mark.parametrize(
    "change",
    (
        "identity",
        "ohlc",
        "volume",
        "timestamp",
        "misaligned",
        "null_timestamp",
        "nonfinite",
        "observed",
    ),
)
def test_invalid_source_is_rejected(change: str) -> None:
    frame = silver(2)
    expression = {
        "identity": pl.lit("ETH/USDT").alias("symbol"),
        "ohlc": pl.lit(50.0).alias("high"),
        "volume": pl.lit(-1.0).alias("volume"),
        "timestamp": pl.lit(START).alias("timestamp"),
        "misaligned": pl.lit(START + timedelta(minutes=30)).alias("timestamp"),
        "null_timestamp": pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias(
            "timestamp"
        ),
        "nonfinite": pl.lit(float("nan")).alias("close"),
        "observed": pl.lit(START).alias("ingested_at"),
    }[change]
    with pytest.raises(ValueError):
        calculate(frame.with_columns(expression))


def test_incomplete_and_non_utc_candles_are_rejected() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        calculate_features(
            silver(2),
            manifest(),
            analysis_as_of=START + HOUR,
            generated_at=GENERATED,
            source_snapshot_sha256=SOURCE_DIGEST,
        )
    bad = silver(2).with_columns(pl.col("timestamp").dt.replace_time_zone(None))
    with pytest.raises(ValueError, match="schema"):
        calculate(bad)


def test_prefix_invariance_and_snapshot_identity() -> None:
    short = calculate(silver(180))
    extended = calculate(silver(200))
    assert short.select(*FEATURES).equals(extended.head(180).select(*FEATURES))
    assert short["source_snapshot_sha256"][0] == SOURCE_DIGEST
    assert short["feature_version"][0] == FEATURE_VERSION
    changed = calculate_features(
        silver(180),
        manifest(),
        analysis_as_of=START + 1_000 * HOUR,
        generated_at=GENERATED,
        source_snapshot_sha256="b" * 64,
        feature_version="qnt-002b-v2",
    )
    assert changed["source_snapshot_sha256"][0] != short["source_snapshot_sha256"][0]
    assert changed["feature_version"][0] != short["feature_version"][0]
    assert changed.select(*FEATURES).equals(short.select(*FEATURES))
    new_manifest = calculate_features(
        silver(180),
        AnomalyManifest("v2", GENERATED, ()),
        analysis_as_of=START + 1_000 * HOUR,
        generated_at=GENERATED,
        source_snapshot_sha256=SOURCE_DIGEST,
    )
    assert new_manifest["manifest_version"][0] == "v2"
    assert (
        new_manifest["anomaly_manifest_sha256"][0]
        != (short["anomaly_manifest_sha256"][0])
    )
    assert new_manifest.select(*FEATURES).equals(short.select(*FEATURES))


def test_determinism_ordering_and_read_only_orchestration(tmp_path) -> None:
    frame = silver(170)
    registry = manifest()
    left = calculate(frame, registry)
    right = calculate(frame, registry)
    assert left.equals(right)
    assert left["timestamp"].is_sorted()
    source_path = tmp_path / "silver.parquet"
    manifest_path = tmp_path / "manifest.json"
    frame.write_parquet(source_path)
    manifest_path.write_bytes(registry.to_bytes())
    prepared = prepare_feature_snapshot(
        source_path,
        manifest_path,
        analysis_as_of=START + 1_000 * HOUR,
        generated_at=GENERATED,
    )
    assert (
        prepared["source_snapshot_sha256"][0]
        == hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    assert prepared["anomaly_manifest_sha256"][0] == registry.sha256
    assert not list(tmp_path.glob("*gold*"))
    synthetic_output = tmp_path / "synthetic_features.parquet"
    prepared.write_parquet(synthetic_output)
    with duckdb.connect(":memory:") as connection:
        count, unique = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT timestamp) FROM read_parquet(?)",
            [str(synthetic_output)],
        ).fetchone()
    assert (count, unique) == (prepared.height, prepared.height)
