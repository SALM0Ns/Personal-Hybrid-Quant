"""Synthetic checks for the shared, non-network feature adapter."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO

import polars as pl
import pytest

from quant.features.adapter import ADAPTER_FEATURE_VERSION, prepare_shared_features
from quant.features.engine import FEATURES, calculate_features
from quant.features.manifest import Anomaly, AnomalyManifest, Evidence
from quant.ingestion.storage import SILVER_SCHEMA

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
GENERATED = datetime(2025, 1, 1, tzinfo=UTC)


def candles(count: int = 170, *, missing: frozenset[int] = frozenset()) -> list[dict]:
    return [
        {
            "timestamp": START + index * HOUR,
            "ingested_at": START + (index + 1) * HOUR,
            "open": 100.0 + index / 10,
            "high": 102.0 + index / 10,
            "low": 99.0 + index / 10,
            "close": 101.0 + index / 10,
            "volume": 10.0 + index,
        }
        for index in range(count)
        if index not in missing
    ]


def manifest(
    *records: Anomaly, available_at: datetime | None = None
) -> AnomalyManifest:
    return AnomalyManifest("synthetic-v1", available_at, records)


def adapt(
    observations: list[dict],
    registry: AnomalyManifest | None = None,
    *,
    analysis_as_of: datetime | None = None,
    expected_latest_candle: datetime | None = None,
) -> pl.DataFrame:
    cutoff = analysis_as_of or observations[-1]["timestamp"] + HOUR
    return prepare_shared_features(
        observations,
        registry or manifest(),
        analysis_as_of=cutoff,
        expected_latest_candle=expected_latest_candle or observations[-1]["timestamp"],
        generated_at=GENERATED,
    )


def test_historical_and_adapter_features_match_on_equivalent_inputs() -> None:
    source = candles(170)
    registry = manifest()
    shared = adapt(source, registry)
    silver = pl.DataFrame(
        [
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                **row,
            }
            for row in source
        ],
        schema=SILVER_SCHEMA,
    )
    historical = calculate_features(
        silver,
        registry,
        analysis_as_of=source[-1]["timestamp"] + HOUR,
        generated_at=GENERATED,
        source_snapshot_sha256=shared["source_snapshot_sha256"][0],
        feature_version=ADAPTER_FEATURE_VERSION,
    )
    assert shared.equals(historical)
    assert all(shared.schema[name] == pl.Float64 for name in FEATURES)
    assert shared["feature_version"][0] == ADAPTER_FEATURE_VERSION


def test_canonical_hash_is_stable_and_distinct_from_file_hash() -> None:
    source = candles(2)
    first = adapt(source)
    second = adapt([{**row} for row in source])
    digest = first["source_snapshot_sha256"][0]
    assert digest == second["source_snapshot_sha256"][0]
    assert len(digest) == 64
    changed = [{**row} for row in source]
    changed[0]["volume"] = 11.0
    assert adapt(changed)["source_snapshot_sha256"][0] != digest
    observed_later = [{**row} for row in source]
    observed_later[0]["ingested_at"] += timedelta(minutes=1)
    assert adapt(observed_later)["source_snapshot_sha256"][0] != digest
    silver = pl.DataFrame(
        [
            {"exchange": "binance", "symbol": "BTC/USDT", "timeframe": "1h", **row}
            for row in source
        ],
        schema=SILVER_SCHEMA,
    )
    parquet_bytes = BytesIO()
    silver.write_parquet(parquet_bytes)
    assert digest != hashlib.sha256(parquet_bytes.getvalue()).hexdigest()


def test_equivalent_utc_and_float64_inputs_hash_identically() -> None:
    source = candles(2)
    alternate = [{**row} for row in source]
    alternate[0]["timestamp"] = alternate[0]["timestamp"].astimezone(
        timezone(timedelta(0))
    )
    alternate[0]["volume"] = 10
    assert (
        adapt(source)["source_snapshot_sha256"][0]
        == adapt(alternate)["source_snapshot_sha256"][0]
    )


def test_prefix_invariance_and_no_future_candle() -> None:
    short = adapt(candles(169))
    long = adapt(candles(171))
    assert short.select(*FEATURES).equals(long.head(169).select(*FEATURES))
    assert short["timestamp"][-1] == START + 168 * HOUR
    assert short["candle_end_at"][-1] == START + 169 * HOUR
    assert short["available_at"].null_count() == short.height


def test_exact_24_and_168_hour_warmup() -> None:
    result = adapt(candles(170))
    assert result["volatility_24h"][23] is None
    assert result["momentum_24h"][23] is None
    assert result["volatility_24h"][24] is not None
    assert result["momentum_24h"][24] is not None
    assert result["volatility_168h"][167] is None
    assert result["momentum_168h"][167] is None
    assert result["volatility_168h"][168] is not None
    assert result["momentum_168h"][168] is not None


def test_internal_gap_is_explicit_and_restarts_rolling_windows() -> None:
    result = adapt(candles(350, missing=frozenset({170})))
    assert result["missing_hour"][170]
    assert result["log_return_1h"][171] is None
    assert result["null_reason__log_return_1h"][171] == "gap_in_window"
    assert result["normalized_range_1h"][171] is not None
    assert result["volatility_24h"][194] is None
    assert result["volatility_24h"][195] is not None
    assert result["volatility_168h"][338] is None
    assert result["volatility_168h"][339] is not None


def test_duplicate_out_of_order_and_empty_inputs_are_rejected() -> None:
    source = candles(3)
    with pytest.raises(ValueError, match="duplicate"):
        adapt([source[0], source[1], source[1]])
    with pytest.raises(ValueError, match="out-of-order"):
        adapt([source[1], source[0], source[2]])
    with pytest.raises(ValueError, match="exactly the source fields"):
        adapt([{**source[0], "symbol": "ETH/USDT"}])
    with pytest.raises(ValueError, match="nonempty"):
        prepare_shared_features(
            [],
            manifest(),
            analysis_as_of=START + HOUR,
            expected_latest_candle=START,
            generated_at=GENERATED,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", 0),
        ("high", 90),
        ("low", 110),
        ("close", float("nan")),
        ("volume", -1),
        ("volume", float("inf")),
        ("volume", True),
    ],
)
def test_invalid_ohlcv_is_rejected(field: str, value: object) -> None:
    source = candles(1)
    source[0][field] = value
    with pytest.raises(ValueError):
        adapt(source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("timestamp", datetime(2024, 1, 1)),
        ("timestamp", START.astimezone(timezone(timedelta(hours=7)))),
        ("timestamp", START + timedelta(minutes=1)),
        ("ingested_at", datetime(2024, 1, 1, 1)),
    ],
)
def test_non_utc_or_misaligned_time_is_rejected(field: str, value: datetime) -> None:
    source = candles(1)
    source[0][field] = value
    with pytest.raises(ValueError, match="UTC"):
        adapt(source)


def test_incomplete_future_observation_and_stale_latest_are_rejected() -> None:
    source = candles(2)
    with pytest.raises(ValueError, match="incomplete"):
        prepare_shared_features(
            source,
            manifest(),
            analysis_as_of=START + HOUR,
            expected_latest_candle=START,
            generated_at=GENERATED,
        )
    source[1]["ingested_at"] = START + HOUR
    with pytest.raises(ValueError, match="predates candle closure"):
        adapt(source)
    source[1]["ingested_at"] = START + 3 * HOUR
    with pytest.raises(ValueError, match="after analysis_as_of"):
        adapt(source, analysis_as_of=START + 2 * HOUR)
    with pytest.raises(ValueError, match="expected_latest_candle"):
        adapt(
            candles(2),
            analysis_as_of=START + 3 * HOUR,
            expected_latest_candle=START + 2 * HOUR,
        )
    with pytest.raises(ValueError, match="latest closed hour"):
        adapt(candles(2), analysis_as_of=START + 3 * HOUR)


def test_unknown_quality_timing_fails_closed_without_losing_features() -> None:
    result = adapt(candles(170))
    assert result["log_return_1h"][168] is not None
    assert result["available_at"][168] is None
    assert not result["decision_eligible"][168]
    assert "unknown_availability" in result["quality_flags"][168]
    with pytest.raises(ValueError, match="empty manifest"):
        adapt(candles(170), manifest(available_at=GENERATED))


def test_manifest_anomaly_provenance_and_versions_are_preserved() -> None:
    source = candles(170)
    issue = Anomaly(
        timestamp=START + 168 * HOUR,
        anomaly_type="source_discrepancy",
        affected_fields=("close",),
        source_evidence=(Evidence("synthetic://source", "a" * 64, START + 169 * HOUR),),
        severity="unrated",
        review_status="unresolved",
        manifest_version="synthetic-v1",
    )
    registry = manifest(issue)
    result = adapt(source, registry)
    assert result["manifest_version"][168] == "synthetic-v1"
    assert result["anomaly_manifest_sha256"][168] == registry.sha256
    assert result["source_discrepancy_at_t"][168]
    assert "log_return_1h" in result["value_sensitive_features"][168]
    assert not result["decision_eligible"][168]


def test_later_quality_evidence_cannot_enter_earlier_analysis() -> None:
    issue = Anomaly(
        timestamp=START,
        anomaly_type="source_discrepancy",
        affected_fields=("close",),
        source_evidence=(Evidence("synthetic://late", "a" * 64, GENERATED),),
        severity="unrated",
        review_status="unresolved",
        manifest_version="synthetic-v1",
    )
    with pytest.raises(ValueError, match="quality evidence occurs after"):
        adapt(candles(2), manifest(issue))


def test_analysis_and_generation_times_must_be_consistent() -> None:
    with pytest.raises(ValueError, match="generated_at predates"):
        prepare_shared_features(
            candles(1),
            manifest(),
            analysis_as_of=GENERATED + HOUR,
            expected_latest_candle=START,
            generated_at=GENERATED,
        )
    with pytest.raises(ValueError, match="latest closed hour"):
        adapt(candles(1), expected_latest_candle=START + 500 * HOUR)
