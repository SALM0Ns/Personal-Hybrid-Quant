"""Build a research-only, forecast-origin audit ledger from pinned local data.

No forecast, fit, score, signal, or exchange operation is performed here.
The target and next-candle metadata are deliberately absent from
``forecast_side_view``. They are retrospective outcome/audit information.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import tempfile
from bisect import bisect_right
from collections import Counter
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from io import BytesIO
from pathlib import Path

import polars as pl

from quant.features.engine import FEATURES, GOLD_SCHEMA, LOOKBACK, _audit_source
from quant.features.manifest import Anomaly, AnomalyManifest, require_utc

HOUR = timedelta(hours=1)
ANALYSIS_AS_OF = datetime(2026, 10, 20, 13, tzinfo=UTC)
DATASET_CONTRACT_VERSION = "pqta-003b-origin-ledger-v1"
PROTOCOL_VERSION = "qnt-003d-design-v1"
SERIALIZER_VERSION = "pqta-003c-parquet-json-v1"
PARQUET_WRITER = {
    "compression": "zstd",
    "compression_level": 3,
    "statistics": True,
    "row_group_size": 8192,
}
SILVER_SHA256 = "edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3"
GOLD_SHA256 = "18f70e22ce189787e74fad2d8f7d14202625e09f355bf81792f2aac7bcd1a66d"
MANIFEST_SHA256 = "86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4"
TRAIN_START = datetime(2021, 1, 1, 1, tzinfo=UTC)
VALIDATION_START = datetime(2024, 1, 1, tzinfo=UTC)
TEST_START = datetime(2025, 1, 1, tzinfo=UTC)
TEST_END = ANALYSIS_AS_OF
TARGET_REASON_PRIORITY = (
    "current_missing",
    "next_missing",
    "current_incomplete",
    "next_incomplete",
    "nonconsecutive_opens",
    "current_invalid_source",
    "next_invalid_source",
    "current_invalid_close",
    "next_invalid_close",
    "target_nonfinite",
)
GOLD_NULL_REASONS = frozenset(
    {"missing_candle", "gap_in_window", "insufficient_history", "zero_denominator"}
)
TARGET_ANOMALY_SCHEMA = pl.Struct(
    {
        "timestamp": pl.Datetime("us", "UTC"),
        "anomaly_type": pl.String,
        "affected_fields": pl.List(pl.String),
        "severity": pl.String,
        "review_status": pl.String,
        "evidence_references": pl.List(pl.String),
    }
)
SAMPLE_SCHEMA = pl.Struct({"sample_id": pl.String, "target_eligible": pl.Boolean})
LEDGER_SCHEMA = {
    **{
        (
            "feature_open_t"
            if name == "timestamp"
            else "feature_theoretical_close_at"
            if name == "candle_end_at"
            else "gold_available_at"
            if name == "available_at"
            else "gold_decision_eligible"
            if name == "decision_eligible"
            else "gold_generated_at"
            if name == "generated_at"
            else name
        ): dtype
        for name, dtype in GOLD_SCHEMA.items()
    },
    "forecast_origin_utc": pl.Datetime("us", "UTC"),
    "split_id": pl.String,
    "target_open_at": pl.Datetime("us", "UTC"),
    "target_theoretical_close_at": pl.Datetime("us", "UTC"),
    "current_candle_present": pl.Boolean,
    "next_candle_present": pl.Boolean,
    "current_candle_valid": pl.Boolean,
    "next_candle_valid": pl.Boolean,
    "current_candle_complete": pl.Boolean,
    "next_candle_complete": pl.Boolean,
    "consecutive_opens": pl.Boolean,
    "target_next_1h_log_return": pl.Float64,
    "target_valid": pl.Boolean,
    "target_null_reasons": pl.List(pl.String),
    "target_primary_null_reason": pl.String,
    "target_endpoint_anomalies": pl.List(TARGET_ANOMALY_SCHEMA),
    "target_value_sensitive": pl.Boolean,
    "feature_complete": pl.Boolean,
    "target_manifest_anomaly": pl.Boolean,
    "feature_manifest_anomaly": pl.Boolean,
    "ar_lag_valid": pl.Boolean,
    "ar_lag_manifest_anomaly": pl.Boolean,
    "lane_a_primary": SAMPLE_SCHEMA,
    "lane_a_sensitivity": SAMPLE_SCHEMA,
    "research_only": pl.Boolean,
    "dataset_spec_id": pl.String,
    "dataset_contract_version": pl.String,
    "protocol_version": pl.String,
    "analysis_as_of": pl.Datetime("us", "UTC"),
}
GOLD_COPY_RENAMES = {
    "timestamp": "feature_open_t",
    "candle_end_at": "feature_theoretical_close_at",
    "available_at": "gold_available_at",
    "decision_eligible": "gold_decision_eligible",
    "generated_at": "gold_generated_at",
}
FORECAST_SIDE_COLUMNS = (
    "exchange",
    "symbol",
    "timeframe",
    "feature_open_t",
    "forecast_origin_utc",
    "split_id",
    *FEATURES,
    *(f"null_reason__{name}" for name in FEATURES),
    "source_present",
    "missing_hour",
    "source_discrepancy_at_t",
    "shortened_close_at_t",
    "source_discrepancy_fields",
    "recorded_source_close_at",
    "anomaly_involved_features",
    "value_sensitive_features",
    "involved_anomalies",
    "quality_flags",
    "feature_complete",
    "feature_manifest_anomaly",
    "ar_lag_valid",
    "ar_lag_manifest_anomaly",
    "gold_available_at",
    "gold_decision_eligible",
    "research_only",
    "dataset_spec_id",
)


def _utc_text(value: datetime) -> str:
    require_utc(value, "canonical timestamp")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_json(value: dict) -> bytes:
    """Versioned canonical JSON: sorted compact UTF-8 object and final LF."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_digest(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def dataset_spec_id(
    *,
    silver_sha256: str,
    gold_sha256: str,
    manifest_sha256: str,
    analysis_as_of: datetime,
    feature_version: str,
    manifest_version: str,
) -> str:
    """Identify the logical dataset, independently of code and build time."""
    for item in (silver_sha256, gold_sha256, manifest_sha256):
        if not _valid_digest(item):
            raise ValueError("invalid source digest")
    if not feature_version or not manifest_version:
        raise ValueError("source contract versions must be nonempty")
    return _sha256(
        canonical_json(
            {
                "dataset_contract_version": DATASET_CONTRACT_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "silver_sha256": silver_sha256,
                "gold_sha256": gold_sha256,
                "manifest_sha256": manifest_sha256,
                "analysis_as_of": _utc_text(analysis_as_of),
                "source_feature_version": feature_version,
                "manifest_version": manifest_version,
            }
        )
    )


def split_id(origin: datetime) -> str:
    require_utc(origin, "forecast origin")
    if TRAIN_START <= origin < VALIDATION_START:
        return "training_history"
    if VALIDATION_START <= origin < TEST_START:
        return "validation"
    if TEST_START <= origin < TEST_END:
        return "test"
    return "outside_approved_evaluation_window"


def _valid_candle(row: dict | None) -> bool:
    if row is None:
        return False
    values = [row.get(name) for name in ("open", "high", "low", "close", "volume")]
    if any(
        value is None or not isinstance(value, (int, float)) or not math.isfinite(value)
        for value in values
    ):
        return False
    opening, high, low, close, volume = values
    return (
        min(opening, high, low, close) > 0
        and volume >= 0
        and high >= max(opening, close, low)
        and low <= min(opening, close, high)
    )


def target_audit(
    current: dict | None,
    following: dict | None,
    *,
    current_open: datetime,
    next_observed_open: datetime | None,
    analysis_as_of: datetime,
) -> tuple[float | None, list[str]]:
    """Classify every applicable target failure; never bridge an absent hour."""
    require_utc(current_open, "current open")
    require_utc(analysis_as_of, "analysis_as_of")
    expected_next = current_open + HOUR
    reasons = set()
    if current is None:
        reasons.add("current_missing")
    if following is None:
        reasons.add("next_missing")
    if current is not None and current.get("timestamp", current_open) != current_open:
        reasons.add("nonconsecutive_opens")
    if (
        following is not None
        and following.get("timestamp", expected_next) != expected_next
    ):
        reasons.add("nonconsecutive_opens")
    if current_open + HOUR > analysis_as_of:
        reasons.add("current_incomplete")
    if expected_next + HOUR > analysis_as_of:
        reasons.add("next_incomplete")
    if current is not None and following is None and next_observed_open is not None:
        if next_observed_open != expected_next:
            reasons.add("nonconsecutive_opens")
    if current is not None and not _valid_candle(current):
        reasons.add("current_invalid_source")
    if following is not None and not _valid_candle(following):
        reasons.add("next_invalid_source")
    for label, row in (("current", current), ("next", following)):
        if row is not None:
            close = row.get("close")
            if (
                close is None
                or not isinstance(close, (int, float))
                or not math.isfinite(close)
                or close <= 0
            ):
                reasons.add(f"{label}_invalid_close")
    value = None
    if not reasons:
        value = math.log(following["close"]) - math.log(current["close"])
        if not math.isfinite(value):
            value = None
            reasons.add("target_nonfinite")
    return value, sorted(reasons)


def _anomaly_record(item: Anomaly) -> dict:
    return {
        "timestamp": item.timestamp,
        "anomaly_type": item.anomaly_type,
        "affected_fields": sorted(item.affected_fields),
        "severity": item.severity,
        "review_status": item.review_status,
        "evidence_references": sorted(e.reference for e in item.source_evidence),
    }


def _audit_gold(
    gold: pl.DataFrame,
    source: list[dict],
    manifest: AnomalyManifest,
    analysis_as_of: datetime,
    silver_sha256: str,
) -> list[dict]:
    if gold.schema != GOLD_SCHEMA or gold.is_empty():
        raise ValueError("Gold schema does not match the approved contract")
    rows = list(gold.iter_rows(named=True))
    first, last = source[0]["timestamp"], source[-1]["timestamp"]
    if len(rows) != int((last - first) / HOUR) + 1:
        raise ValueError("Gold does not cover the complete Silver UTC timeline")
    source_opens = {row["timestamp"] for row in source}
    missing_manifest = {
        item.timestamp
        for item in manifest.records
        if item.anomaly_type == "missing_hour"
    }
    actual_missing = set()
    for index, row in enumerate(rows):
        timestamp = first + index * HOUR
        if row["timestamp"] != timestamp or row["candle_end_at"] != timestamp + HOUR:
            raise ValueError("Gold timestamps are not unique contiguous UTC hours")
        if row["candle_end_at"] > analysis_as_of:
            raise ValueError("Gold contains an incomplete candle")
        if (row["exchange"], row["symbol"], row["timeframe"]) != (
            "binance",
            "BTC/USDT",
            "1h",
        ):
            raise ValueError("unexpected Gold market identity")
        present = timestamp in source_opens
        if row["source_present"] is not present or row["missing_hour"] is present:
            raise ValueError("Gold presence conflicts with Silver")
        if not present:
            actual_missing.add(timestamp)
        if row["source_snapshot_sha256"] != silver_sha256:
            raise ValueError("Gold source digest differs from Silver")
        if (
            row["anomaly_manifest_sha256"] != manifest.sha256
            or row["manifest_version"] != manifest.manifest_version
        ):
            raise ValueError("Gold manifest identity differs")
        if row["feature_version"] is None or not row["feature_version"].strip():
            raise ValueError("missing Gold feature version")
        if row["feature_version"] != rows[0]["feature_version"]:
            raise ValueError("mixed Gold feature versions")
        if row["available_at"] is None and row["decision_eligible"] is not False:
            raise ValueError("unknown Gold availability cannot be decision eligible")
        if not isinstance(row["decision_eligible"], bool):
            raise ValueError("missing Gold decision eligibility")
        for feature in FEATURES:
            value, reason = row[feature], row[f"null_reason__{feature}"]
            if (value is None) != (reason is not None):
                raise ValueError("Gold feature and null reason disagree")
            if value is not None and not math.isfinite(value):
                raise ValueError("non-finite Gold feature")
            if reason is not None and reason not in GOLD_NULL_REASONS:
                raise ValueError("unknown Gold null reason")
            if not present and (value is not None or reason != "missing_candle"):
                raise ValueError("missing Gold hour has feature value")
        if row["anomaly_involved_features"] != [
            feature
            for feature in FEATURES
            if any(
                timestamp - LOOKBACK[feature] * HOUR <= item.timestamp <= timestamp
                for item in manifest.records
            )
        ]:
            raise ValueError("Gold feature anomaly dependencies differ from manifest")
    if actual_missing != missing_manifest:
        raise ValueError("missing-hour manifest differs from Silver/Gold timeline")
    return rows


def build_origin_ledger(
    silver: pl.DataFrame,
    gold: pl.DataFrame,
    manifest: AnomalyManifest,
    *,
    analysis_as_of: datetime,
    silver_sha256: str,
    gold_sha256: str,
) -> pl.DataFrame:
    """Build and validate a full audit timeline; never write an input."""
    require_utc(analysis_as_of, "analysis_as_of")
    if analysis_as_of.minute or analysis_as_of.second or analysis_as_of.microsecond:
        raise ValueError("analysis_as_of must be hour-aligned")
    if not _valid_digest(gold_sha256):
        raise ValueError("invalid Gold digest")
    source = _audit_source(silver, analysis_as_of)
    if any(row["ingested_at"] is None for row in source):
        raise ValueError("Silver source is missing local observation timestamps")
    gold_rows = _audit_gold(gold, source, manifest, analysis_as_of, silver_sha256)
    spec = dataset_spec_id(
        silver_sha256=silver_sha256,
        gold_sha256=gold_sha256,
        manifest_sha256=manifest.sha256,
        analysis_as_of=analysis_as_of,
        feature_version=gold_rows[0]["feature_version"],
        manifest_version=manifest.manifest_version,
    )
    by_open = {row["timestamp"]: row for row in source}
    source_opens = sorted(by_open)
    anomalies_by_open: dict[datetime, list[Anomaly]] = {}
    for item in manifest.ordered_records():
        anomalies_by_open.setdefault(item.timestamp, []).append(item)
    result = []
    for gold_row in gold_rows:
        t = gold_row["timestamp"]
        origin = t + HOUR
        current = by_open.get(t)
        following = by_open.get(origin)
        next_position = bisect_right(source_opens, t)
        next_observed = (
            source_opens[next_position] if next_position < len(source_opens) else None
        )
        target, reasons = target_audit(
            current,
            following,
            current_open=t,
            next_observed_open=next_observed,
            analysis_as_of=analysis_as_of,
        )
        endpoints = [*anomalies_by_open.get(t, ()), *anomalies_by_open.get(origin, ())]
        target_anomaly = bool(endpoints)
        target_sensitive = target is not None and any(
            item.anomaly_type == "shortened_close"
            or (
                item.anomaly_type == "source_discrepancy"
                and bool(set(item.affected_fields) & {"close", "unknown"})
            )
            for item in endpoints
        )
        previous = by_open.get(t - HOUR)
        ar_lag_valid = (
            previous is not None
            and current is not None
            and _valid_candle(previous)
            and _valid_candle(current)
            and t + HOUR <= analysis_as_of
        )
        primary = reasons == []
        row = {
            **{
                GOLD_COPY_RENAMES.get(name, name): value
                for name, value in gold_row.items()
            },
            "forecast_origin_utc": origin,
            "split_id": split_id(origin),
            "target_open_at": origin,
            "target_theoretical_close_at": origin + HOUR,
            "current_candle_present": current is not None,
            "next_candle_present": following is not None,
            "current_candle_valid": _valid_candle(current),
            "next_candle_valid": _valid_candle(following),
            "current_candle_complete": current is not None
            and t + HOUR <= analysis_as_of,
            "next_candle_complete": following is not None
            and origin + HOUR <= analysis_as_of,
            "consecutive_opens": current is not None and following is not None,
            "target_next_1h_log_return": target,
            "target_valid": primary,
            "target_null_reasons": reasons,
            "target_primary_null_reason": next(
                (name for name in TARGET_REASON_PRIORITY if name in reasons), None
            ),
            "target_endpoint_anomalies": [_anomaly_record(item) for item in endpoints],
            "target_value_sensitive": target_sensitive,
            "feature_complete": all(gold_row[name] is not None for name in FEATURES),
            "target_manifest_anomaly": target_anomaly,
            "feature_manifest_anomaly": bool(gold_row["anomaly_involved_features"]),
            "ar_lag_valid": ar_lag_valid,
            "ar_lag_manifest_anomaly": bool(
                anomalies_by_open.get(t - HOUR) or anomalies_by_open.get(t)
            ),
            "lane_a_primary": {"sample_id": "a_primary", "target_eligible": primary},
            "lane_a_sensitivity": {
                "sample_id": "a_sensitivity",
                "target_eligible": primary and not target_anomaly,
            },
            "research_only": True,
            "dataset_spec_id": spec,
            "dataset_contract_version": DATASET_CONTRACT_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "analysis_as_of": analysis_as_of,
        }
        result.append(row)
    ledger = pl.DataFrame(result, schema=LEDGER_SCHEMA, strict=True)
    if ledger.height != len(gold_rows) or ledger.schema != LEDGER_SCHEMA:
        raise ValueError("origin ledger schema or row count invalid")
    return ledger


def forecast_side_view(ledger: pl.DataFrame) -> pl.DataFrame:
    """Allowlisted current/past columns; never expose outcome/audit fields."""
    if ledger.schema != LEDGER_SCHEMA:
        raise ValueError("unexpected origin ledger schema")
    return ledger.select(*FORECAST_SIDE_COLUMNS)


def validate_ledger(ledger: pl.DataFrame) -> list[dict]:
    """Fail closed on complete schema, key, target, and mask invariants."""
    if ledger.schema != LEDGER_SCHEMA or ledger.is_empty():
        raise ValueError("unexpected or empty origin ledger schema")
    rows = list(ledger.iter_rows(named=True))
    first = rows[0]["forecast_origin_utc"]
    identity = rows[0]["dataset_spec_id"]
    for index, row in enumerate(rows):
        origin = first + index * HOUR
        if (
            row["forecast_origin_utc"] != origin
            or row["feature_open_t"] != origin - HOUR
        ):
            raise ValueError("origin keys must be unique, sorted, contiguous UTC hours")
        if (row["exchange"], row["symbol"], row["timeframe"]) != (
            "binance",
            "BTC/USDT",
            "1h",
        ):
            raise ValueError("unexpected ledger market identity")
        if (
            row["feature_theoretical_close_at"] != origin
            or row["target_open_at"] != origin
        ):
            raise ValueError("forecast-origin alignment failure")
        if row["target_theoretical_close_at"] != origin + HOUR:
            raise ValueError("target close alignment failure")
        if row["split_id"] != split_id(origin) or row["dataset_spec_id"] != identity:
            raise ValueError("split or dataset identity mismatch")
        if row["source_present"] != row["current_candle_present"]:
            raise ValueError("source presence mismatch")
        if row["missing_hour"] == row["source_present"]:
            raise ValueError("missing-hour mask mismatch")
        if row["consecutive_opens"] != (
            row["current_candle_present"] and row["next_candle_present"]
        ):
            raise ValueError("consecutive-open mask mismatch")
        if row["feature_complete"] != all(row[name] is not None for name in FEATURES):
            raise ValueError("feature completeness mismatch")
        if row["feature_manifest_anomaly"] != bool(row["anomaly_involved_features"]):
            raise ValueError("feature anomaly mask mismatch")
        if row["target_manifest_anomaly"] != bool(row["target_endpoint_anomalies"]):
            raise ValueError("target anomaly mask mismatch")
        reasons = row["target_null_reasons"]
        if reasons != sorted(set(reasons)) or not set(reasons) <= set(
            TARGET_REASON_PRIORITY
        ):
            raise ValueError("target reasons are not canonical")
        if row["target_primary_null_reason"] != next(
            (name for name in TARGET_REASON_PRIORITY if name in reasons), None
        ):
            raise ValueError("target primary reason priority mismatch")
        if row["target_valid"] != (not reasons):
            raise ValueError("target validity/reasons mismatch")
        target = row["target_next_1h_log_return"]
        if (target is None) == row["target_valid"] or (
            target is not None and not math.isfinite(target)
        ):
            raise ValueError("invalid or non-finite target value")
        if row["lane_a_primary"] != {
            "sample_id": "a_primary",
            "target_eligible": row["target_valid"],
        }:
            raise ValueError("A-primary eligibility mismatch")
        if row["lane_a_sensitivity"] != {
            "sample_id": "a_sensitivity",
            "target_eligible": row["target_valid"]
            and not row["target_manifest_anomaly"],
        }:
            raise ValueError("A-sensitivity eligibility mismatch")
        if row["gold_available_at"] is None and row["gold_decision_eligible"]:
            raise ValueError("unknown availability marked decision eligible")
        if row["research_only"] is not True:
            raise ValueError("origin ledger must be research-only")
    return rows


def validation_report(
    ledger: pl.DataFrame,
    *,
    silver_rows: int,
    gold_sha256: str,
    silver_sha256: str,
    manifest_sha256: str,
) -> dict:
    """Dataset-quality counts only; no forecast or performance metrics."""
    rows = validate_ledger(ledger)
    splits = Counter(row["split_id"] for row in rows)
    reasons = Counter(reason for row in rows for reason in row["target_null_reasons"])
    return {
        "report_version": "pqta-003c-validation-v1",
        "dataset_spec_id": rows[0]["dataset_spec_id"],
        "protocol_version": PROTOCOL_VERSION,
        "analysis_as_of": _utc_text(rows[0]["analysis_as_of"]),
        "source_sha256": {
            "silver": silver_sha256,
            "gold": gold_sha256,
            "manifest_canonical": manifest_sha256,
        },
        "source_rows": {"silver": silver_rows, "gold": len(rows)},
        "source_bounds": {
            "first_gold_open": _utc_text(rows[0]["feature_open_t"]),
            "last_gold_open": _utc_text(rows[-1]["feature_open_t"]),
            "first_silver_open": _utc_text(
                next(row["feature_open_t"] for row in rows if row["source_present"])
            ),
            "last_silver_open": _utc_text(
                next(
                    row["feature_open_t"]
                    for row in reversed(rows)
                    if row["source_present"]
                )
            ),
        },
        "origin_rows": len(rows),
        "first_origin": _utc_text(rows[0]["forecast_origin_utc"]),
        "last_origin": _utc_text(rows[-1]["forecast_origin_utc"]),
        "split_counts": dict(sorted(splits.items())),
        "in_split_origins": sum(
            count
            for key, count in splits.items()
            if key != "outside_approved_evaluation_window"
        ),
        "gold_missing_hours": sum(row["missing_hour"] for row in rows),
        "valid_targets": sum(row["target_valid"] for row in rows),
        "null_targets": sum(not row["target_valid"] for row in rows),
        "target_null_reason_frequencies": dict(sorted(reasons.items())),
        "feature_complete": sum(row["feature_complete"] for row in rows),
        "target_manifest_anomaly": sum(row["target_manifest_anomaly"] for row in rows),
        "target_value_sensitive": sum(row["target_value_sensitive"] for row in rows),
        "feature_manifest_anomaly": sum(
            row["feature_manifest_anomaly"] for row in rows
        ),
        "ar_lag_valid": sum(row["ar_lag_valid"] for row in rows),
        "ar_lag_manifest_anomaly": sum(row["ar_lag_manifest_anomaly"] for row in rows),
        "a_primary_target_eligible": sum(
            row["lane_a_primary"]["target_eligible"] for row in rows
        ),
        "a_sensitivity_target_eligible": sum(
            row["lane_a_sensitivity"]["target_eligible"] for row in rows
        ),
        "gold_available_at_null": sum(row["gold_available_at"] is None for row in rows),
        "gold_decision_eligible_false": sum(
            not row["gold_decision_eligible"] for row in rows
        ),
        "research_only": all(row["research_only"] for row in rows),
    }


def _parquet_bytes(ledger: pl.DataFrame) -> bytes:
    sink = BytesIO()
    ledger.write_parquet(sink, **PARQUET_WRITER)
    return sink.getvalue()


def _dependency_versions() -> dict[str, str]:
    names = ("ccxt", "duckdb", "pandera", "polars", "pytz")
    return {name: version(name) for name in names} | {
        "python": platform.python_version()
    }


def _code_revision() -> str:
    """Content identity of this builder and its reused validation contracts."""
    source_root = Path(__file__).resolve().parents[1]
    paths = (
        "research/forecast_dataset.py",
        "features/engine.py",
        "features/manifest.py",
    )
    return _sha256(
        canonical_json({name: file_sha256(source_root / name) for name in paths})
    )


def artifact_build_id(
    spec_id: str, *, code_revision: str, dependency_versions: dict[str, str]
) -> str:
    if not _valid_digest(spec_id) or not _valid_digest(code_revision):
        raise ValueError("invalid build identity digest")
    if not dependency_versions or any(
        not key or not val for key, val in dependency_versions.items()
    ):
        raise ValueError("missing dependency version")
    return _sha256(
        canonical_json(
            {
                "dataset_spec_id": spec_id,
                "code_revision_sha256": code_revision,
                "dependency_versions": dict(sorted(dependency_versions.items())),
                "serializer_version": SERIALIZER_VERSION,
                "schema": [(name, str(dtype)) for name, dtype in LEDGER_SCHEMA.items()],
                "row_order": ["exchange", "symbol", "timeframe", "forecast_origin_utc"],
                "float_encoding": "IEEE-754 Float64; no NaN or infinity",
                "parquet_writer": PARQUET_WRITER,
                "embedded_processing_timestamp": None,
            }
        )
    )


def verify_published(directory: Path, expected: dict[str, bytes]) -> None:
    if not directory.is_dir() or {path.name for path in directory.iterdir()} != set(
        expected
    ):
        raise ValueError("existing immutable build has missing or unexpected files")
    for name, value in expected.items():
        if file_sha256(directory / name) != _sha256(value):
            raise ValueError(
                f"conflicting bytes under immutable build identity: {name}"
            )
    provenance = (directory / "provenance.json").read_bytes()
    if (directory / "provenance.sha256").read_bytes() != (
        _sha256(provenance) + "\n"
    ).encode():
        raise ValueError("published provenance sidecar mismatch")


def publish_ledger(
    ledger: pl.DataFrame,
    *,
    root: Path,
    silver_rows: int,
    silver_sha256: str,
    gold_sha256: str,
    manifest_sha256: str,
    code_revision: str,
    dependency_versions: dict[str, str],
) -> Path:
    """Validate, stage on the destination filesystem, then publish atomically."""
    report = validation_report(
        ledger,
        silver_rows=silver_rows,
        silver_sha256=silver_sha256,
        gold_sha256=gold_sha256,
        manifest_sha256=manifest_sha256,
    )
    spec = report["dataset_spec_id"]
    build = artifact_build_id(
        spec, code_revision=code_revision, dependency_versions=dependency_versions
    )
    ledger_bytes = _parquet_bytes(ledger)
    check = pl.read_parquet(BytesIO(ledger_bytes))
    if not check.equals(ledger, null_equal=True):
        raise ValueError("Parquet roundtrip differs from validated ledger")
    report_bytes = canonical_json(report)
    provenance = {
        "dataset_spec_id": spec,
        "artifact_build_id": build,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "code_revision_sha256": code_revision,
        "dependency_versions": dict(sorted(dependency_versions.items())),
        "serializer_version": SERIALIZER_VERSION,
        "parquet_writer": PARQUET_WRITER,
        "schema": [(name, str(dtype)) for name, dtype in LEDGER_SCHEMA.items()],
        "row_order": ["exchange", "symbol", "timeframe", "forecast_origin_utc"],
        "float_encoding": "IEEE-754 Float64; no NaN or infinity",
        "input_sha256": {
            "silver": silver_sha256,
            "gold": gold_sha256,
            "manifest_canonical": manifest_sha256,
        },
        "artifact_sha256": {
            "origin_ledger.parquet": _sha256(ledger_bytes),
            "dataset_validation.json": _sha256(report_bytes),
        },
        "processing_time_embedded": None,
        "research_only": True,
    }
    provenance_bytes = canonical_json(provenance)
    expected = {
        "origin_ledger.parquet": ledger_bytes,
        "dataset_validation.json": report_bytes,
        "provenance.json": provenance_bytes,
        "provenance.sha256": (_sha256(provenance_bytes) + "\n").encode(),
    }
    parent = root / spec
    final = parent / build
    if final.exists():
        verify_published(final, expected)
        return final
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=parent) as stage_name:
        stage = Path(stage_name)
        for name, value in expected.items():
            (stage / name).write_bytes(value)
            if file_sha256(stage / name) != _sha256(value):
                raise ValueError(f"staged artifact hash mismatch: {name}")
        if final.exists():
            verify_published(final, expected)
            return final
        stage.rename(final)
    verify_published(final, expected)
    return final


def run_pinned_dataset(root: Path) -> tuple[Path, dict]:
    """Fail closed on the three approved inputs before building local output."""
    silver_path = root / "data/silver/binance/1h/BTC-USDT.parquet"
    gold_path = root / "data/gold/qnt-002b/btc_usdt_1h/candidate_v1/features.parquet"
    manifest_path = root / "configs/qnt-002b-btc-anomalies.candidate.v1.json"
    if file_sha256(silver_path) != SILVER_SHA256:
        raise ValueError("Silver pinned SHA-256 mismatch")
    if file_sha256(gold_path) != GOLD_SHA256:
        raise ValueError("Gold pinned SHA-256 mismatch")
    manifest = AnomalyManifest.load(manifest_path)
    if manifest.sha256 != MANIFEST_SHA256:
        raise ValueError("candidate manifest canonical SHA-256 mismatch")
    silver = pl.read_parquet(silver_path)
    gold = pl.read_parquet(gold_path)
    ledger = build_origin_ledger(
        silver,
        gold,
        manifest,
        analysis_as_of=ANALYSIS_AS_OF,
        silver_sha256=SILVER_SHA256,
        gold_sha256=GOLD_SHA256,
    )
    report = validation_report(
        ledger,
        silver_rows=silver.height,
        silver_sha256=SILVER_SHA256,
        gold_sha256=GOLD_SHA256,
        manifest_sha256=MANIFEST_SHA256,
    )
    if not (
        report["source_rows"] == {"silver": 50831, "gold": 50845}
        and report["origin_rows"] == 50845
        and report["in_split_origins"] == 50844
        and report["gold_missing_hours"] == 14
        and report["first_origin"] == "2021-01-01T01:00:00.000000Z"
        and report["last_origin"] == "2026-10-20T13:00:00.000000Z"
        and report["split_counts"].get("outside_approved_evaluation_window") == 1
        and report["gold_available_at_null"] == 50845
        and report["gold_decision_eligible_false"] == 50845
    ):
        raise ValueError("pinned historical acceptance counts differ")
    output = publish_ledger(
        ledger,
        root=root / "data/research/pqta-003",
        silver_rows=silver.height,
        silver_sha256=SILVER_SHA256,
        gold_sha256=GOLD_SHA256,
        manifest_sha256=MANIFEST_SHA256,
        code_revision=_code_revision(),
        dependency_versions=_dependency_versions(),
    )
    return output, report


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    output, report = run_pinned_dataset(root)
    print(
        canonical_json(
            {"output": str(output.relative_to(root)), "validation": report}
        ).decode(),
        end="",
    )


if __name__ == "__main__":
    main()
