"""Conservative hourly coverage accounting with explicit availability evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from quant.ingestion.ohlcv import HOUR_MS
from quant.validation.ohlcv import utc_from_ms


def verified_availability(
    config_path: Path, symbol: str
) -> tuple[datetime | None, str | None]:
    """Read an externally verified start; a first API candle is not evidence."""
    if not config_path.exists():
        return None, None
    values = json.loads(config_path.read_text(encoding="utf-8"))
    entry = values.get(symbol, {})
    start_text = entry.get("verified_start_utc")
    evidence = entry.get("evidence")
    if start_text is None:
        return None, None
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError(f"{symbol}: verified availability requires evidence")
    start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
    if start.tzinfo is None or start.utcoffset() != UTC.utcoffset(start):
        raise ValueError(f"{symbol}: verified availability start must be UTC")
    start_ms = int(start.timestamp() * 1000)
    if start_ms % HOUR_MS:
        raise ValueError(f"{symbol}: verified availability start must align to an hour")
    return start.astimezone(UTC), evidence.strip()


def _periods(timestamps_ms: list[int]) -> list[dict[str, str]]:
    """Compress hourly timestamps into disjoint half-open UTC intervals."""
    if not timestamps_ms:
        return []
    periods = []
    first = previous = timestamps_ms[0]
    for timestamp in timestamps_ms[1:]:
        if timestamp != previous + HOUR_MS:
            periods.append(
                {
                    "start": utc_from_ms(first).isoformat(),
                    "end_exclusive": utc_from_ms(previous + HOUR_MS).isoformat(),
                }
            )
            first = timestamp
        previous = timestamp
    periods.append(
        {
            "start": utc_from_ms(first).isoformat(),
            "end_exclusive": utc_from_ms(previous + HOUR_MS).isoformat(),
        }
    )
    return periods


def coverage_report(
    start_ms: int,
    end_exclusive_ms: int,
    observed_ms: set[int],
    verified_start_ms: int | None,
) -> dict:
    """Classify every requested hour without guessing the listing date."""
    pre_availability = []
    unknown = []
    verified_missing = []
    availability_conflicts = []
    for timestamp in range(start_ms, end_exclusive_ms, HOUR_MS):
        if timestamp in observed_ms:
            if verified_start_ms is not None and timestamp < verified_start_ms:
                availability_conflicts.append(timestamp)
        elif verified_start_ms is None:
            unknown.append(timestamp)
        elif timestamp < verified_start_ms:
            pre_availability.append(timestamp)
        else:
            verified_missing.append(timestamp)
    if availability_conflicts:
        status = "availability_conflict"
    elif verified_missing:
        status = "incomplete"
    elif unknown:
        status = "unknown"
    elif pre_availability:
        status = "complete_after_availability"
    else:
        status = "complete"
    return {
        "coverage_status": status,
        "unobserved_timestamps": [
            utc_from_ms(ts).isoformat()
            for ts in sorted(pre_availability + unknown + verified_missing)
        ],
        "missing_within_verified_coverage_count": len(verified_missing),
        "missing_timestamps": [utc_from_ms(ts).isoformat() for ts in verified_missing],
        "pre_availability_candle_count": len(pre_availability),
        "pre_availability_periods": _periods(pre_availability),
        "unknown_coverage_candle_count": len(unknown),
        "unknown_coverage_periods": _periods(unknown),
        "availability_conflict_timestamps": [
            utc_from_ms(ts).isoformat() for ts in availability_conflicts
        ],
    }
