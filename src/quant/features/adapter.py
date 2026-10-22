"""Validate in-memory BTC/USDT candles before using the offline feature engine."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import polars as pl

from quant.features.engine import FEATURE_VERSION, calculate_features
from quant.features.manifest import AnomalyManifest, require_utc
from quant.ingestion.storage import SILVER_SCHEMA

HOUR = timedelta(hours=1)
SNAPSHOT_SCHEMA_VERSION = "pqta-canonical-ohlcv-v1"
# The suffix distinguishes an in-memory canonical digest from the historical
# Silver Parquet-file digest while retaining the same seven feature formulas.
ADAPTER_FEATURE_VERSION = f"{FEATURE_VERSION}+{SNAPSHOT_SCHEMA_VERSION}"
SOURCE_FIELDS = (
    "timestamp",
    "ingested_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
PRICE_FIELDS = ("open", "high", "low", "close")
MARKET = ("binance", "BTC/USDT", "1h")


def _utc_hour(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    require_utc(value, name)
    normalized = value.astimezone(UTC)
    if normalized.minute or normalized.second or normalized.microsecond:
        raise ValueError(f"{name} must be aligned to a UTC hour")
    return normalized


def _utc_time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    require_utc(value, name)
    return value.astimezone(UTC)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite Float64-compatible number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite Float64-compatible number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    # Signed zero is not a distinct OHLCV observation.
    return 0.0 if result == 0 else result


def _validate_observations(
    observations: Sequence[Mapping[str, object]], analysis_as_of: datetime
) -> list[dict]:
    if not isinstance(observations, (list, tuple)) or not observations:
        raise ValueError("observations must be a nonempty bounded sequence")
    rows: list[dict] = []
    previous: datetime | None = None
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping) or set(observation) != set(
            SOURCE_FIELDS
        ):
            raise ValueError(f"observation {index} must have exactly the source fields")
        timestamp = _utc_hour(observation["timestamp"], "timestamp")
        ingested_at = _utc_time(observation["ingested_at"], "ingested_at")
        if previous is not None and timestamp <= previous:
            problem = "duplicate" if timestamp == previous else "out-of-order"
            raise ValueError(f"{problem} candle timestamp")
        if timestamp + HOUR > analysis_as_of:
            raise ValueError("incomplete candle at analysis_as_of")
        if ingested_at < timestamp + HOUR:
            raise ValueError("observation predates candle closure")
        if ingested_at > analysis_as_of:
            raise ValueError("observation occurs after analysis_as_of")
        numeric = {
            name: _number(observation[name], name) for name in (*PRICE_FIELDS, "volume")
        }
        prices = [numeric[name] for name in PRICE_FIELDS]
        if (
            min(prices) <= 0
            or numeric["volume"] < 0
            or numeric["high"] < max(prices)
            or numeric["low"] > min(prices)
        ):
            raise ValueError("invalid OHLCV relationship")
        rows.append(
            {
                "exchange": MARKET[0],
                "symbol": MARKET[1],
                "timeframe": MARKET[2],
                "timestamp": timestamp,
                **numeric,
                "ingested_at": ingested_at,
            }
        )
        previous = timestamp
    return rows


def _snapshot_bytes(rows: list[dict]) -> bytes:
    """Canonical UTF-8 JSON; floats are exact big-endian IEEE-754 hex bytes."""

    def instant(value: datetime) -> str:
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    payload = {
        "schema": SNAPSHOT_SCHEMA_VERSION,
        "market": list(MARKET),
        "fields": list(SOURCE_FIELDS),
        "rows": [
            [
                instant(row["timestamp"]),
                instant(row["ingested_at"]),
                *[
                    struct.pack(">d", row[name]).hex()
                    for name in (*PRICE_FIELDS, "volume")
                ],
            ]
            for row in rows
        ],
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def prepare_shared_features(
    observations: Sequence[Mapping[str, object]],
    manifest: AnomalyManifest,
    *,
    analysis_as_of: datetime,
    expected_latest_candle: datetime,
    generated_at: datetime,
) -> pl.DataFrame:
    """Return the existing Gold schema from validated, non-network observations.

    This is an offline feature calculation boundary, not an inference or
    trading-decision API. A manifest with no findings cannot by itself prove
    complete quality; an empty manifest must retain unknown version timing.
    """
    analysis_as_of = _utc_time(analysis_as_of, "analysis_as_of")
    generated_at = _utc_time(generated_at, "generated_at")
    expected_latest_candle = _utc_hour(expected_latest_candle, "expected_latest_candle")
    if generated_at < analysis_as_of:
        raise ValueError("generated_at predates analysis_as_of")
    latest_closed = (analysis_as_of - HOUR).replace(minute=0, second=0, microsecond=0)
    if expected_latest_candle != latest_closed:
        raise ValueError("expected_latest_candle is not the latest closed hour")
    if not isinstance(manifest, AnomalyManifest):
        raise ValueError("a versioned AnomalyManifest is required")
    if not manifest.records and manifest.version_available_at is not None:
        raise ValueError("empty manifest does not establish complete quality evidence")
    evidence_times = [manifest.version_available_at] + [
        evidence.observed_at
        for record in manifest.records
        for evidence in record.source_evidence
    ]
    if any(time is not None and time > analysis_as_of for time in evidence_times):
        raise ValueError("quality evidence occurs after analysis_as_of")
    rows = _validate_observations(observations, analysis_as_of)
    if rows[-1]["timestamp"] != expected_latest_candle:
        raise ValueError("last candle does not match expected_latest_candle")
    source_hash = hashlib.sha256(_snapshot_bytes(rows)).hexdigest()
    frame = pl.DataFrame(rows, schema=SILVER_SCHEMA)
    return calculate_features(
        frame,
        manifest,
        analysis_as_of=analysis_as_of,
        generated_at=generated_at,
        source_snapshot_sha256=source_hash,
        feature_version=ADAPTER_FEATURE_VERSION,
    )
