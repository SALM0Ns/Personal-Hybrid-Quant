"""Build and independently audit the pinned, local QNT-002B research snapshot.

Run with ``PYTHONPATH=src .venv/bin/python scripts/qnt_002b_stage2b.py``.
The output path is exclusive: this script never overwrites an existing file.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import polars as pl

from quant.features.engine import FEATURE_VERSION, FEATURES
from quant.features.manifest import AnomalyManifest
from quant.features.pipeline import prepare_feature_snapshot

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "data/silver/binance/1h/BTC-USDT.parquet"
MANIFEST = ROOT / "configs/qnt-002b-btc-anomalies.candidate.v1.json"
OUTPUT = ROOT / "data/gold/qnt-002b/btc_usdt_1h/candidate_v1/features.parquet"
SILVER_SHA256 = "edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3"
MANIFEST_SHA256 = "86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4"
ANALYSIS_AS_OF = datetime(2026, 10, 20, 13, tzinfo=UTC)
HOUR = timedelta(hours=1)
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 3
ROW_GROUP_SIZE = 8192
SEED = 20261021
AUDIT_FEATURES = (
    "log_return_1h",
    "volatility_24h",
    "volatility_168h",
    "momentum_24h",
    "momentum_168h",
    "volume_change_1h",
    "normalized_range_1h",
)
LOOKBACK_SPEC = {
    "log_return_1h": 1,
    "volatility_24h": 24,
    "volatility_168h": 168,
    "momentum_24h": 24,
    "momentum_168h": 168,
    "volume_change_1h": 1,
    "normalized_range_1h": 0,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def existing_data_hashes() -> dict[str, str]:
    paths = sorted((ROOT / "data/bronze").rglob("*.parquet"))
    paths += sorted((ROOT / "data/silver").rglob("*.parquet"))
    paths += sorted(
        path for path in (ROOT / "data/gold/qnt-002a").rglob("*") if path.is_file()
    )
    assert len(paths) == 6 + 18, "unexpected existing Bronze/Silver or QNT-002A files"
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def validate_evidence(manifest: AnomalyManifest) -> None:
    assert len(manifest.records) == 19
    assert Counter(item.anomaly_type for item in manifest.records) == {
        "missing_hour": 14,
        "shortened_close": 4,
        "source_discrepancy": 1,
    }
    assert manifest.records == manifest.ordered_records()
    assert manifest.version_available_at is None
    assert all(
        item.severity == "unrated" and item.review_status == "unresolved"
        for item in manifest.records
    )
    for item in manifest.records:
        for evidence in item.source_evidence:
            reference = evidence.reference
            if reference.startswith("https://"):
                parsed = urlparse(reference)
                assert (
                    parsed.scheme == "https" and parsed.netloc == "data.binance.vision"
                )
                assert parsed.path.startswith("/data/spot/monthly/klines/BTCUSDT/1h/")
                filename = Path(parsed.path).name
                assert filename.startswith("BTCUSDT-1h-") and filename.endswith(".zip")
                path = ROOT / "data/verification/qnt-001b/archives" / filename
                checksum = Path(f"{path}.CHECKSUM")
                tokens = checksum.read_text().split()
                assert len(tokens) == 2 and tokens[1] == filename
                assert digest(path) == tokens[0] == evidence.sha256
            else:
                relative = Path(reference)
                assert not relative.is_absolute() and ".." not in relative.parts
                assert relative.parts[:2] == ("data", "verification")
                assert digest(ROOT / relative) == evidence.sha256


def expected_reason(
    feature: str,
    index: int,
    candles: list[dict | None],
    missing_prefix: list[int],
) -> str | None:
    if candles[index] is None:
        return "missing_candle"
    start = index - LOOKBACK_SPEC[feature]
    if missing_prefix[index + 1] - missing_prefix[max(start, 0)] > 0:
        return "gap_in_window"
    if start < 0:
        return "insufficient_history"
    if feature == "volume_change_1h" and candles[start]["volume"] == 0:
        return "zero_denominator"
    return None


def independent_value(feature: str, index: int, candles: list[dict | None]) -> float:
    current = candles[index]
    first = candles[index - LOOKBACK_SPEC[feature]]
    if feature == "log_return_1h":
        return math.log(current["close"] / first["close"])
    if feature.startswith("volatility_"):
        returns = [
            math.log(candles[j]["close"] / candles[j - 1]["close"])
            for j in range(index - LOOKBACK_SPEC[feature] + 1, index + 1)
        ]
        return statistics.stdev(returns)
    if feature.startswith("momentum_"):
        return current["close"] / first["close"] - 1
    if feature == "volume_change_1h":
        return current["volume"] / first["volume"] - 1
    return (current["high"] - current["low"]) / current["close"]


def independently_audit(frame: pl.DataFrame, manifest: AnomalyManifest) -> dict:
    source = pl.read_parquet(SILVER)
    source_rows = {row["timestamp"]: row for row in source.iter_rows(named=True)}
    rows = list(frame.iter_rows(named=True))
    first = min(source_rows)
    last = max(source_rows)
    assert rows and len(rows) == int((last - first) / HOUR) + 1 == 50845
    assert len(source_rows) == 50831
    assert len(
        {(r["exchange"], r["symbol"], r["timeframe"], r["timestamp"]) for r in rows}
    ) == len(rows)
    assert all(frame.schema[feature] == pl.Float64 for feature in FEATURES)
    candles = [source_rows.get(first + i * HOUR) for i in range(len(rows))]
    prefix = [0]
    for candle in candles:
        prefix.append(prefix[-1] + (candle is None))
    assert prefix[-1] == 14

    sample = {0, 1, 23, 24, 167, 168}
    random_indices = random.Random(SEED).sample(range(len(rows)), 64)
    sample.update(random_indices)
    for anomaly in manifest.records:
        at = int((anomaly.timestamp - first) / HOUR)
        sample.update(
            at + offset for offset in (-1, 0, 1, 2, 23, 24, 25, 167, 168, 169)
        )
    sample = {index for index in sample if 0 <= index < len(rows)}
    null_counts = Counter()
    reasons = {feature: Counter() for feature in FEATURES}
    sensitive_counts = Counter()
    involved_counts = Counter()
    all_anomalies = manifest.ordered_records()
    used_anomalies = set()
    for index, row in enumerate(rows):
        timestamp = first + index * HOUR
        assert row["timestamp"] == timestamp
        assert row["candle_end_at"] == timestamp + HOUR
        assert (row["exchange"], row["symbol"], row["timeframe"]) == (
            "binance",
            "BTC/USDT",
            "1h",
        )
        assert row["source_present"] == (candles[index] is not None)
        assert row["missing_hour"] == (candles[index] is None)
        assert row["quality_evidence_available_at"] is None
        assert row["available_at"] is None
        assert row["availability_basis"] == "unverified"
        assert row["decision_eligible"] is False
        assert row["source_snapshot_sha256"] == SILVER_SHA256
        assert row["anomaly_manifest_sha256"] == MANIFEST_SHA256
        assert row["feature_version"] == FEATURE_VERSION
        assert row["manifest_version"] == manifest.manifest_version
        assert row["generated_at"] is not None
        expected_involved = []
        expected_sensitive = []
        active_records = {}
        required = set()
        for feature in FEATURES:
            reason = expected_reason(feature, index, candles, prefix)
            value = row[feature]
            assert row[f"null_reason__{feature}"] == reason, (timestamp, feature)
            assert (value is None) == (reason is not None), (timestamp, feature)
            if reason is not None:
                null_counts[feature] += 1
                reasons[feature][reason] += 1
            else:
                assert math.isfinite(value)
                required.update(range(index - LOOKBACK_SPEC[feature], index + 1))
                if index in sample:
                    expected = independent_value(feature, index, candles)
                    assert math.isclose(
                        value, expected, rel_tol=1e-10, abs_tol=1e-12
                    ), (timestamp, feature, value, expected)
            first_dependency = timestamp - LOOKBACK_SPEC[feature] * HOUR
            relevant = [
                anomaly
                for anomaly in all_anomalies
                if first_dependency <= anomaly.timestamp <= timestamp
            ]
            if relevant:
                expected_involved.append(feature)
                involved_counts[feature] += 1
            for anomaly in relevant:
                active_records[(anomaly.timestamp, anomaly.anomaly_type)] = anomaly
            if value is None:
                continue
            for anomaly in relevant:
                if anomaly.anomaly_type == "missing_hour":
                    continue
                if feature.startswith("momentum_") and anomaly.timestamp not in (
                    first_dependency,
                    timestamp,
                ):
                    continue
                fields = set(anomaly.affected_fields)
                numeric = {
                    "log_return_1h": {"close"},
                    "volatility_24h": {"close"},
                    "volatility_168h": {"close"},
                    "momentum_24h": {"close"},
                    "momentum_168h": {"close"},
                    "volume_change_1h": {"volume"},
                    "normalized_range_1h": {"high", "low", "close"},
                }[feature]
                if (
                    anomaly.anomaly_type == "shortened_close"
                    or "unknown" in fields
                    or bool(fields & numeric)
                ):
                    expected_sensitive.append(feature)
                    sensitive_counts[feature] += 1
                    break
        assert row["anomaly_involved_features"] == expected_involved, timestamp
        assert row["value_sensitive_features"] == expected_sensitive, timestamp
        ordered = [
            anomaly
            for anomaly in all_anomalies
            if (anomaly.timestamp, anomaly.anomaly_type) in active_records
        ]
        actual_keys = [
            (item["timestamp"], item["anomaly_type"])
            for item in row["involved_anomalies"]
        ]
        assert actual_keys == [(item.timestamp, item.anomaly_type) for item in ordered]
        used_anomalies.update(actual_keys)
        own = [item for item in ordered if item.timestamp == timestamp]
        assert row["source_discrepancy_at_t"] == any(
            item.anomaly_type == "source_discrepancy" for item in own
        )
        assert row["shortened_close_at_t"] == any(
            item.anomaly_type == "shortened_close" for item in own
        )
        assert row["source_discrepancy_fields"] == sorted(
            {
                field
                for item in own
                if item.anomaly_type == "source_discrepancy"
                for field in item.affected_fields
            }
        )
        shortened = [item for item in own if item.anomaly_type == "shortened_close"]
        assert row["recorded_source_close_at"] == (
            shortened[0].recorded_source_close_at if shortened else None
        )
        observed = [candles[position]["ingested_at"] for position in required]
        expected_max = max(observed) if observed and all(observed) else None
        assert row["max_source_ingested_at"] == expected_max
        expected_flags = {"unknown_availability"}
        if candles[index] is None:
            expected_flags.add("missing_hour")
        if any(
            reasons_for == "gap_in_window"
            for reasons_for in (row[f"null_reason__{f}"] for f in FEATURES)
        ):
            expected_flags.add("missing_hour_in_window")
        if any(row[f"null_reason__{f}"] == "insufficient_history" for f in FEATURES):
            expected_flags.add("insufficient_history")
        if any(row[f"null_reason__{f}"] == "zero_denominator" for f in FEATURES):
            expected_flags.add("zero_denominator")
        if ordered:
            expected_flags.add("anomaly_in_window")
        if any(item.anomaly_type == "source_discrepancy" for item in ordered):
            expected_flags.add("source_discrepancy")
        if any(item.anomaly_type == "shortened_close" for item in ordered):
            expected_flags.add("shortened_close")
        assert row["quality_flags"] == sorted(expected_flags), timestamp
    assert used_anomalies == {
        (item.timestamp, item.anomaly_type) for item in manifest.records
    }
    return {
        "rows": len(rows),
        "source_rows": len(source_rows),
        "missing_hours": prefix[-1],
        "sampled_rows": len(sample),
        "random_seed": SEED,
        "random_rows": len(random_indices),
        "null_counts": dict(null_counts),
        "null_reasons": {name: dict(reasons[name]) for name in FEATURES},
        "anomaly_involved_row_counts": dict(involved_counts),
        "value_sensitive_row_counts": dict(sensitive_counts),
        "decision_eligible_count": 0,
    }


def parquet_bytes(frame: pl.DataFrame) -> bytes:
    buffer = BytesIO()
    frame.write_parquet(
        buffer,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
        statistics=True,
        row_group_size=ROW_GROUP_SIZE,
    )
    return buffer.getvalue()


def main() -> None:
    assert not OUTPUT.exists(), "output already exists; never overwrite"
    before = existing_data_hashes()
    assert before[str(SILVER.relative_to(ROOT))] == SILVER_SHA256
    assert digest(MANIFEST) == MANIFEST_SHA256
    assert (ROOT / "docs/QNT-002B_MANIFEST_AUDIT.md").is_file()
    manifest = AnomalyManifest.load(MANIFEST)
    validate_evidence(manifest)
    assert FEATURES == AUDIT_FEATURES
    assert FEATURE_VERSION == "qnt-002b-v1"
    source = pl.read_parquet(SILVER)
    assert source["timestamp"].max() == ANALYSIS_AS_OF - HOUR
    generated_at = datetime.now(UTC)
    assert generated_at > ANALYSIS_AS_OF
    frame = prepare_feature_snapshot(
        SILVER, MANIFEST, analysis_as_of=ANALYSIS_AS_OF, generated_at=generated_at
    )
    summary = independently_audit(frame, manifest)
    repeat = prepare_feature_snapshot(
        SILVER, MANIFEST, analysis_as_of=ANALYSIS_AS_OF, generated_at=generated_at
    )
    assert frame.equals(repeat)
    first_bytes = parquet_bytes(frame)
    assert first_bytes == parquet_bytes(repeat)
    shifted = frame.with_columns(
        pl.lit(generated_at + timedelta(microseconds=1)).alias("generated_at")
    )
    assert frame.drop("generated_at").equals(shifted.drop("generated_at"))
    assert first_bytes != parquet_bytes(shifted)
    with tempfile.TemporaryDirectory(prefix="qnt-002b-audit-") as directory:
        temporary = Path(directory) / "features.parquet"
        temporary.write_bytes(first_bytes)
        with duckdb.connect(database=":memory:") as connection:
            count, unique, missing, eligible = connection.execute(
                "SELECT count(*), count(DISTINCT timestamp), "
                "count(*) FILTER (WHERE missing_hour), "
                "count(*) FILTER (WHERE decision_eligible) "
                "FROM read_parquet(?)",
                [str(temporary)],
            ).fetchone()
        assert (count, unique, missing, eligible) == (50845, 50845, 14, 0)
        assert pl.read_parquet(temporary).equals(frame)
    assert existing_data_hashes() == before
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("xb") as destination:
        destination.write(first_bytes)
    assert digest(OUTPUT) == hashlib.sha256(first_bytes).hexdigest()
    assert existing_data_hashes() == before
    summary.update(
        {
            "output": str(OUTPUT.relative_to(ROOT)),
            "output_sha256": digest(OUTPUT),
            "source_sha256": SILVER_SHA256,
            "manifest_sha256": MANIFEST_SHA256,
            "feature_version": FEATURE_VERSION,
            "manifest_version": manifest.manifest_version,
            "analysis_as_of": ANALYSIS_AS_OF.isoformat(),
            "generated_at": generated_at.isoformat(),
            "serializer": {
                "library": "polars",
                "version": pl.__version__,
                "compression": COMPRESSION,
                "compression_level": COMPRESSION_LEVEL,
                "statistics": True,
                "row_group_size": ROW_GROUP_SIZE,
            },
            "duckdb_version": duckdb.__version__,
            "fixed_run_byte_identical": True,
            "changed_generated_at_changes_bytes_only": True,
            "existing_data_hashes_unchanged": True,
        }
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
