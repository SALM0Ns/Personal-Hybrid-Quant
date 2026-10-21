"""Offline, gap-strict BTC/USDT hourly feature calculation."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import stdev

import polars as pl

from quant.features.manifest import Anomaly, AnomalyManifest, require_utc

HOUR = timedelta(hours=1)
FEATURE_VERSION = "qnt-002b-v1"
FEATURES = (
    "log_return_1h",
    "volatility_24h",
    "volatility_168h",
    "momentum_24h",
    "momentum_168h",
    "volume_change_1h",
    "normalized_range_1h",
)
LOOKBACK = {
    "log_return_1h": 1,
    "volatility_24h": 24,
    "volatility_168h": 168,
    "momentum_24h": 24,
    "momentum_168h": 168,
    "volume_change_1h": 1,
    "normalized_range_1h": 0,
}
ANOMALY_SCHEMA = pl.Struct(
    {
        "timestamp": pl.Datetime("us", "UTC"),
        "anomaly_type": pl.String,
        "affected_fields": pl.List(pl.String),
        "severity": pl.String,
        "review_status": pl.String,
        "evidence_references": pl.List(pl.String),
    }
)
GOLD_SCHEMA = {
    "exchange": pl.String,
    "symbol": pl.String,
    "timeframe": pl.String,
    "timestamp": pl.Datetime("us", "UTC"),
    "candle_end_at": pl.Datetime("us", "UTC"),
    "available_at": pl.Datetime("us", "UTC"),
    **dict.fromkeys(FEATURES, pl.Float64),
    **{f"null_reason__{name}": pl.String for name in FEATURES},
    "source_present": pl.Boolean,
    "missing_hour": pl.Boolean,
    "source_discrepancy_at_t": pl.Boolean,
    "shortened_close_at_t": pl.Boolean,
    "source_discrepancy_fields": pl.List(pl.String),
    "recorded_source_close_at": pl.Datetime("us", "UTC"),
    "anomaly_involved_features": pl.List(pl.String),
    "value_sensitive_features": pl.List(pl.String),
    "involved_anomalies": pl.List(ANOMALY_SCHEMA),
    "quality_flags": pl.List(pl.String),
    "decision_eligible": pl.Boolean,
    "max_source_ingested_at": pl.Datetime("us", "UTC"),
    "quality_evidence_available_at": pl.Datetime("us", "UTC"),
    "availability_basis": pl.String,
    "feature_version": pl.String,
    "manifest_version": pl.String,
    "source_snapshot_sha256": pl.String,
    "anomaly_manifest_sha256": pl.String,
    "generated_at": pl.Datetime("us", "UTC"),
}


def _audit_source(frame: pl.DataFrame, analysis_as_of: datetime) -> list[dict]:
    required = {
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
    }
    if any(frame.schema.get(name) != dtype for name, dtype in required.items()):
        raise ValueError("Silver source schema does not match the approved contract")
    if frame.is_empty():
        raise ValueError("Silver source contains no candles")
    rows = list(frame.select(*required).iter_rows(named=True))
    previous: datetime | None = None
    for row in rows:
        timestamp = row["timestamp"]
        if not isinstance(timestamp, datetime):
            raise ValueError("Silver timestamp must be present")
        require_utc(timestamp, "Silver timestamp")
        if timestamp.minute or timestamp.second or timestamp.microsecond:
            raise ValueError("Silver timestamp is not hour-aligned")
        if previous is not None and timestamp <= previous:
            raise ValueError("Silver timestamps must be strictly increasing and unique")
        if (row["exchange"], row["symbol"], row["timeframe"]) != (
            "binance",
            "BTC/USDT",
            "1h",
        ):
            raise ValueError("unexpected Silver market identity")
        prices = tuple(row[name] for name in ("open", "high", "low", "close"))
        volume = row["volume"]
        if any(value is None or not math.isfinite(value) for value in prices):
            raise ValueError("non-finite or null Silver price")
        if volume is None or not math.isfinite(volume) or volume < 0:
            raise ValueError("invalid Silver volume")
        if min(prices) <= 0 or row["high"] < max(prices) or row["low"] > min(prices):
            raise ValueError("invalid Silver OHLC relationship")
        candle_end = timestamp + HOUR
        if candle_end > analysis_as_of:
            raise ValueError("incomplete source candle")
        observed_at = row["ingested_at"]
        if observed_at is not None:
            require_utc(observed_at, "Silver ingested_at")
            if observed_at < candle_end:
                raise ValueError("source candle observed before theoretical closure")
        previous = timestamp
    return rows


def _dependency_indices(index: int, feature: str) -> range:
    return range(max(index - LOOKBACK[feature], 0), index + 1)


def _feature_value(
    feature: str, index: int, candles: list[dict | None]
) -> tuple[float | None, str | None]:
    current = candles[index]
    if current is None:
        return None, "missing_candle"
    start = index - LOOKBACK[feature]
    if any(candles[position] is None for position in range(max(start, 0), index + 1)):
        return None, "gap_in_window"
    if start < 0:
        return None, "insufficient_history"
    prior = candles[start]
    assert prior is not None
    if feature == "log_return_1h":
        value = math.log(current["close"]) - math.log(prior["close"])
    elif feature.startswith("volatility_"):
        returns = [
            math.log(candles[position]["close"])
            - math.log(candles[position - 1]["close"])
            for position in range(start + 1, index + 1)
        ]
        value = stdev(returns)  # sample standard deviation, ddof=1
    elif feature.startswith("momentum_"):
        value = current["close"] / prior["close"] - 1
        if value <= -1:
            raise ValueError("momentum ratio underflowed its mathematical bound")
    elif feature == "volume_change_1h":
        if prior["volume"] == 0:
            return None, "zero_denominator"
        value = current["volume"] / prior["volume"] - 1
    else:
        value = (current["high"] - current["low"]) / current["close"]
    if not math.isfinite(value):
        raise ValueError(f"non-finite calculated {feature}")
    return float(value), None


def _value_sensitive(
    feature: str, anomaly: Anomaly, first: datetime, last: datetime
) -> bool:
    if anomaly.anomaly_type == "missing_hour":
        return False
    at = anomaly.timestamp
    fields = set(anomaly.affected_fields)
    if anomaly.anomaly_type == "source_discrepancy" and "unknown" in fields:
        return True
    if feature.startswith("momentum_") and at not in (first, last):
        return False
    if anomaly.anomaly_type == "shortened_close":
        return True
    numeric_fields = {
        "log_return_1h": {"close"},
        "volatility_24h": {"close"},
        "volatility_168h": {"close"},
        "momentum_24h": {"close"},
        "momentum_168h": {"close"},
        "volume_change_1h": {"volume"},
        "normalized_range_1h": {"high", "low", "close"},
    }[feature]
    return bool(fields & numeric_fields)


def _anomaly_dict(anomaly: Anomaly) -> dict:
    return {
        "timestamp": anomaly.timestamp,
        "anomaly_type": anomaly.anomaly_type,
        "affected_fields": sorted(anomaly.affected_fields),
        "severity": anomaly.severity,
        "review_status": anomaly.review_status,
        "evidence_references": sorted(
            evidence.reference for evidence in anomaly.source_evidence
        ),
    }


def calculate_features(
    silver: pl.DataFrame,
    manifest: AnomalyManifest,
    *,
    analysis_as_of: datetime,
    generated_at: datetime,
    source_snapshot_sha256: str,
    feature_version: str = FEATURE_VERSION,
) -> pl.DataFrame:
    """Build an in-memory, fully typed feature snapshot; never write market data."""
    if not isinstance(analysis_as_of, datetime) or not isinstance(
        generated_at, datetime
    ):
        raise ValueError("analysis_as_of and generated_at must be present")
    require_utc(analysis_as_of, "analysis_as_of")
    require_utc(generated_at, "generated_at")
    if not isinstance(feature_version, str) or not feature_version.strip():
        raise ValueError("feature_version must be nonempty")
    if (
        not isinstance(source_snapshot_sha256, str)
        or len(source_snapshot_sha256) != 64
        or any(
            character not in "0123456789abcdef" for character in source_snapshot_sha256
        )
    ):
        raise ValueError("invalid source_snapshot_sha256")
    source = _audit_source(silver, analysis_as_of)
    if any(
        row["ingested_at"] is not None and row["ingested_at"] > generated_at
        for row in source
    ):
        raise ValueError("generated_at predates a source observation")
    evidence_times = [manifest.version_available_at] + [
        evidence.observed_at
        for item in manifest.records
        for evidence in item.source_evidence
    ]
    if any(value is not None and value > generated_at for value in evidence_times):
        raise ValueError("generated_at predates anomaly evidence")
    first = source[0]["timestamp"]
    last = source[-1]["timestamp"]
    by_timestamp = {row["timestamp"]: row for row in source}
    timeline = [
        first + offset * HOUR for offset in range(int((last - first) / HOUR) + 1)
    ]
    candles = [by_timestamp.get(timestamp) for timestamp in timeline]
    anomalies = manifest.ordered_records()
    for item in anomalies:
        if first <= item.timestamp <= last:
            exists = item.timestamp in by_timestamp
            if (item.anomaly_type == "missing_hour") == exists:
                raise ValueError("anomaly manifest conflicts with Silver presence")
    result = []
    for index, timestamp in enumerate(timeline):
        current = candles[index]
        values: dict[str, float | None] = {}
        reasons: dict[str, str | None] = {}
        involved_features = []
        sensitive_features = []
        involved_records: dict[tuple[datetime, str], Anomaly] = {}
        required_positions: set[int] = set()
        for feature in FEATURES:
            value, reason = _feature_value(feature, index, candles)
            values[feature] = value
            reasons[feature] = reason
            start = timestamp - LOOKBACK[feature] * HOUR
            feature_anomalies = [
                item for item in anomalies if start <= item.timestamp <= timestamp
            ]
            if feature_anomalies:
                involved_features.append(feature)
            for item in feature_anomalies:
                involved_records[(item.timestamp, item.anomaly_type)] = item
            if value is not None:
                required_positions.update(_dependency_indices(index, feature))
                if any(
                    _value_sensitive(feature, item, start, timestamp)
                    for item in feature_anomalies
                ):
                    sensitive_features.append(feature)
        involved = tuple(
            item
            for item in anomalies
            if (item.timestamp, item.anomaly_type) in involved_records
        )
        own = tuple(item for item in involved if item.timestamp == timestamp)
        observations = [
            candles[position]["ingested_at"] for position in required_positions
        ]
        max_observed = (
            max(observations)
            if observations and all(value is not None for value in observations)
            else None
        )
        evidence_times = [manifest.version_available_at] + [
            evidence.observed_at
            for item in involved
            for evidence in item.source_evidence
        ]
        quality_time = (
            max(evidence_times)
            if all(value is not None for value in evidence_times)
            else None
        )
        available = (
            max(timestamp + HOUR, max_observed, quality_time)
            if current is not None
            and required_positions
            and max_observed is not None
            and quality_time is not None
            else None
        )
        flags = set()
        if current is None:
            flags.add("missing_hour")
        if any(reason == "gap_in_window" for reason in reasons.values()):
            flags.add("missing_hour_in_window")
        if any(reason == "insufficient_history" for reason in reasons.values()):
            flags.add("insufficient_history")
        if any(reason == "zero_denominator" for reason in reasons.values()):
            flags.add("zero_denominator")
        if involved:
            flags.add("anomaly_in_window")
        if any(item.anomaly_type == "source_discrepancy" for item in involved):
            flags.add("source_discrepancy")
        if any(item.anomaly_type == "shortened_close" for item in involved):
            flags.add("shortened_close")
        if available is None:
            flags.add("unknown_availability")
        discrepancy_at_t = tuple(
            item for item in own if item.anomaly_type == "source_discrepancy"
        )
        shortened_at_t = tuple(
            item for item in own if item.anomaly_type == "shortened_close"
        )
        result.append(
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "timestamp": timestamp,
                "candle_end_at": timestamp + HOUR,
                "available_at": available,
                **values,
                **{f"null_reason__{name}": reasons[name] for name in FEATURES},
                "source_present": current is not None,
                "missing_hour": current is None,
                "source_discrepancy_at_t": bool(discrepancy_at_t),
                "shortened_close_at_t": bool(shortened_at_t),
                "source_discrepancy_fields": sorted(
                    {
                        field
                        for item in discrepancy_at_t
                        for field in item.affected_fields
                    }
                ),
                "recorded_source_close_at": (
                    shortened_at_t[0].recorded_source_close_at
                    if shortened_at_t
                    else None
                ),
                "anomaly_involved_features": involved_features,
                "value_sensitive_features": sensitive_features,
                "involved_anomalies": [_anomaly_dict(item) for item in involved],
                "quality_flags": sorted(flags),
                "decision_eligible": (
                    current is not None
                    and all(value is not None for value in values.values())
                    and available is not None
                    and not involved
                ),
                "max_source_ingested_at": max_observed,
                "quality_evidence_available_at": quality_time,
                "availability_basis": (
                    "local_observation_plus_quality_evidence"
                    if available is not None
                    else "unverified"
                ),
                "feature_version": feature_version,
                "manifest_version": manifest.manifest_version,
                "source_snapshot_sha256": source_snapshot_sha256,
                "anomaly_manifest_sha256": manifest.sha256,
                "generated_at": generated_at,
            }
        )
    return pl.DataFrame(result, schema=GOLD_SCHEMA)
