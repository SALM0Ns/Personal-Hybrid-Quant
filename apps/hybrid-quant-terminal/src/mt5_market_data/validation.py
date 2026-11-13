"""Strict validation of broker-clock exports; never infer a timezone."""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timedelta
from itertools import pairwise

COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread_points",
    "real_volume",
)
MARKETS = {"EURUSDm", "XAUUSDm"}
PERIODS = {"M15": 900, "H1": 3600, "H4": 14400}
META_FIELDS = {
    "format_version",
    "broker_server",
    "symbol",
    "timeframe",
    "requested_start",
    "requested_end_exclusive",
    "actual_first",
    "actual_last",
    "exported_at_server",
    "exported_at_local",
    "row_count",
    "copyrates_returned",
    "timestamp_semantics",
}


class InputError(ValueError):
    """Source input is inconsistent or malformed."""


def parse_time(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y.%m.%d %H:%M:%S")
    except (ValueError, TypeError) as exc:
        raise InputError(f"Invalid broker-clock timestamp: {value!r}") from exc


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("Input must be UTF-8 CSV") from exc


def parse_metadata(raw: bytes) -> dict[str, str]:
    reader = csv.reader(io.StringIO(_text(raw), newline=""), strict=True)
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise InputError("Malformed metadata CSV") from exc
    if not rows or rows[0] != ["field", "value"]:
        raise InputError("Metadata must have field,value header")
    result = {}
    for row in rows[1:]:
        if len(row) != 2 or row[0] in result:
            raise InputError("Malformed or duplicate metadata field")
        result[row[0]] = row[1]
    if set(result) != META_FIELDS:
        raise InputError("Missing or unexpected metadata fields")
    if result["format_version"] != "mt5-export-v1":
        raise InputError("Unsupported metadata format")
    if not result["broker_server"].strip():
        raise InputError("Broker server is required")
    if result["symbol"] not in MARKETS or result["timeframe"] not in PERIODS:
        raise InputError("Unsupported symbol or timeframe")
    if result["timestamp_semantics"] != "broker_server_clock_unverified":
        raise InputError("Unexpected timestamp semantics")
    start = parse_time(result["requested_start"])
    end = parse_time(result["requested_end_exclusive"])
    parse_time(result["exported_at_server"])
    parse_time(result["exported_at_local"])
    if end <= start:
        raise InputError("Invalid requested interval")
    for name in ("row_count", "copyrates_returned"):
        if not result[name].isdigit():
            raise InputError(f"Invalid {name}")
    if int(result["copyrates_returned"]) < int(result["row_count"]):
        raise InputError("CopyRates count is smaller than exported row count")
    return result


def parse_candles(raw: bytes, metadata: dict[str, str]) -> tuple[list[dict], dict]:
    reader = csv.DictReader(io.StringIO(_text(raw), newline=""), strict=True)
    if reader.fieldnames != list(COLUMNS):
        raise InputError("CSV header does not match the export contract")
    rows = []
    seen = set()
    duplicate_count = invalid_ohlc_count = non_monotonic_count = 0
    misaligned_timestamp_count = 0
    previous = None
    try:
        for line, raw_row in enumerate(reader, start=2):
            if None in raw_row or any(value is None for value in raw_row.values()):
                raise InputError(f"Malformed CSV row {line}")
            timestamp = parse_time(raw_row["timestamp"])
            minute_step = 15 if metadata["timeframe"] == "M15" else 60
            if timestamp.second or timestamp.minute % minute_step:
                misaligned_timestamp_count += 1
            if timestamp in seen:
                duplicate_count += 1
            if previous is not None and timestamp <= previous:
                non_monotonic_count += 1
            seen.add(timestamp)
            previous = timestamp
            try:
                values = {
                    name: float(raw_row[name])
                    for name in ("open", "high", "low", "close")
                }
                volumes = {}
                for name in ("tick_volume", "spread_points", "real_volume"):
                    value = raw_row[name]
                    if not value.isdigit():
                        raise ValueError(name)
                    volumes[name] = int(value)
                    if volumes[name] > 2**63 - 1:
                        raise ValueError(name)
            except (ValueError, OverflowError) as exc:
                raise InputError(f"Invalid numeric value at CSV row {line}") from exc
            o, h, low, c = (values[name] for name in ("open", "high", "low", "close"))
            if (
                not all(math.isfinite(x) and x > 0 for x in (o, h, low, c))
                or h < max(o, low, c)
                or low > min(o, h, c)
            ):
                invalid_ohlc_count += 1
            rows.append({"timestamp": timestamp, **values, **volumes})
    except csv.Error as exc:
        raise InputError("Malformed candles CSV") from exc
    counts = {
        "duplicate_count": duplicate_count,
        "non_monotonic_count": non_monotonic_count,
        "invalid_ohlc_count": invalid_ohlc_count,
        "misaligned_timestamp_count": misaligned_timestamp_count,
    }
    return rows, counts


def coverage(rows: list[dict], metadata: dict[str, str]) -> dict:
    start = parse_time(metadata["requested_start"])
    end = parse_time(metadata["requested_end_exclusive"])
    step = timedelta(seconds=PERIODS[metadata["timeframe"]])
    times = sorted({row["timestamp"] for row in rows})
    gaps = []
    for left, right in pairwise(times):
        delta = right - left
        if delta > step:
            gaps.append(
                {
                    "after": left.isoformat(),
                    "before": right.isoformat(),
                    "elapsed_seconds": int(delta.total_seconds()),
                    "nominal_missing_bars": max(0, int(delta // step) - 1),
                    "classification": "unverified_calendar_or_missing",
                }
            )
    unknown = [
        {"start": (left + step).isoformat(), "end_exclusive": right.isoformat()}
        for left, right in pairwise(times)
        if right - left > step
    ]
    if not times:
        unknown.append({"start": start.isoformat(), "end_exclusive": end.isoformat()})
    else:
        if times[0] > start:
            unknown.append(
                {"start": start.isoformat(), "end_exclusive": times[0].isoformat()}
            )
        if times[-1] + step < end:
            unknown.append(
                {
                    "start": (times[-1] + step).isoformat(),
                    "end_exclusive": end.isoformat(),
                }
            )
    return {
        "actual_first": times[0].isoformat() if times else None,
        "actual_last": times[-1].isoformat() if times else None,
        "observed_timestamp_gaps": gaps,
        "unknown_coverage_periods": unknown,
    }
