"""Normalize raw hourly candles and measure quality without filling gaps."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime

from quant.ingestion.ohlcv import HOUR_MS


def utc_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def normalize(observation: dict, latest_closed_ms: int) -> dict | None:
    """Return a canonical candidate, or reject a malformed/incomplete row."""
    try:
        values = json.loads(observation["raw_ohlcv"])
        if not isinstance(values, list) or len(values) < 6:
            return None
        timestamp = values[0]
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            return None
        if timestamp % HOUR_MS or timestamp > latest_closed_ms:
            return None
        if observation["observed_at"] < utc_from_ms(timestamp + HOUR_MS):
            return None
        prices = [float(value) for value in values[1:6]]
        if not all(math.isfinite(value) for value in prices):
            return None
        opening, high, low, close, volume = prices
        if min(opening, high, low, close) <= 0 or volume < 0:
            return None
        if high < max(opening, close, low) or low > min(opening, close, high):
            return None
        return {
            "exchange": observation["exchange"],
            "symbol": observation["symbol"],
            "timeframe": observation["timeframe"],
            "timestamp": utc_from_ms(timestamp),
            "open": opening,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "ingested_at": observation["observed_at"],
            "_observation_id": observation["observation_id"],
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def canonicalize(
    observations: list[dict], latest_closed_ms: int
) -> tuple[list[dict], dict[str, int]]:
    """Choose the latest observed valid value per key, breaking ties by hash."""
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    rejected = 0
    for observation in observations:
        candidate = normalize(observation, latest_closed_ms)
        if candidate is None:
            rejected += 1
        else:
            key = (
                candidate["exchange"],
                candidate["symbol"],
                candidate["timeframe"],
                candidate["timestamp"],
            )
            by_key[key].append(candidate)
    canonical = []
    duplicates = 0
    conflicts = 0
    for candidates in by_key.values():
        duplicates += len(candidates) - 1
        values = {
            tuple(item[field] for field in ("open", "high", "low", "close", "volume"))
            for item in candidates
        }
        conflicts += len(values) - 1
        winner = max(
            candidates, key=lambda row: (row["ingested_at"], row["_observation_id"])
        )
        canonical.append(
            {key: value for key, value in winner.items() if not key.startswith("_")}
        )
    canonical.sort(key=lambda row: row["timestamp"])
    return canonical, {
        "duplicate_count": duplicates,
        "conflict_revision_count": conflicts,
        "rejected_record_count": rejected,
    }
