"""Build a bounded chart preview from the existing BTC/USDT Silver snapshot."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

HOUR = timedelta(hours=1)
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
EXCHANGE = "binance"
SIGNAL = "NO SIGNAL"
PREVIEW_LABEL = "HISTORICAL PREVIEW — NOT LIVE"


class PreviewDataError(ValueError):
    """The local Silver snapshot cannot safely be displayed."""


class PreviewNotFoundError(FileNotFoundError):
    """The local BTC/USDT Silver snapshot is missing."""


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PreviewDataError(f"{field} must be timezone-aware UTC")
    return value.astimezone(UTC)


def load_preview(
    data_root: Path,
    *,
    limit: int = 500,
    as_of: datetime | None = None,
) -> dict:
    """Read the latest *limit* observations without changing the Parquet file.

    The preview is descriptive only. Candle closure is checked, but historical
    publication availability is neither known nor inferred.
    """
    if not 1 <= limit <= 2000:
        raise ValueError("limit must be between 1 and 2000")
    cutoff = _utc(as_of or datetime.now(UTC), "as_of")
    # The established Silver location; importing the storage writer would also
    # import Polars, which this read-only DuckDB preview does not need.
    path = Path(data_root) / "silver" / "binance" / "1h" / "BTC-USDT.parquet"
    if not path.is_file():
        raise PreviewNotFoundError(f"Silver dataset not found: {path}")

    try:
        with duckdb.connect(database=":memory:") as connection:
            rows = connection.execute(
                """SELECT timestamp, open, high, low, close, volume
                   FROM read_parquet(?)
                   WHERE exchange = ? AND symbol = ? AND timeframe = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                [str(path), EXCHANGE, SYMBOL, TIMEFRAME, limit],
            ).fetchall()
    except duckdb.Error as exc:
        raise PreviewDataError(
            "Silver dataset is unreadable or has an invalid schema"
        ) from exc

    if not rows:
        raise PreviewDataError("No BTC/USDT 1h candles are present in Silver")

    candles: list[dict] = []
    missing_hours = 0
    previous: datetime | None = None
    for raw_timestamp, *raw_values in reversed(rows):
        if not isinstance(raw_timestamp, datetime):
            raise PreviewDataError("Candle timestamp is not a datetime")
        timestamp = _utc(raw_timestamp, "timestamp")
        if timestamp.minute or timestamp.second or timestamp.microsecond:
            raise PreviewDataError("Candle timestamp is not aligned to a UTC hour")
        if timestamp + HOUR > cutoff:
            raise PreviewDataError("Silver contains an incomplete candle")
        if previous is not None:
            delta = timestamp - previous
            if delta <= timedelta(0):
                raise PreviewDataError(
                    "Silver contains duplicate or unordered timestamps"
                )
            if delta != HOUR:
                missing_hours += int(delta / HOUR) - 1
        if any(value is None or isinstance(value, bool) for value in raw_values):
            raise PreviewDataError(f"Null or invalid OHLCV at {timestamp.isoformat()}")
        try:
            opening, high, low, close, volume = map(float, raw_values)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PreviewDataError(f"Invalid OHLCV at {timestamp.isoformat()}") from exc
        if (
            not all(
                math.isfinite(value) for value in (opening, high, low, close, volume)
            )
            or min(opening, high, low, close) <= 0
            or volume < 0
            or high < max(opening, close, low)
            or low > min(opening, close, high)
        ):
            raise PreviewDataError(f"Invalid OHLCV at {timestamp.isoformat()}")
        candles.append(
            {
                "time": int(timestamp.timestamp()),
                "open": opening,
                "high": high,
                "low": low,
                "close": close,
            }
        )
        previous = timestamp

    return {
        "source": PREVIEW_LABEL,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "signal": SIGNAL,
        "quality_status": "GAPS DETECTED" if missing_hours else "CONTIGUOUS WINDOW",
        "missing_hours": missing_hours,
        "candle_count": len(candles),
        "latest_candle_timestamp": previous.isoformat().replace("+00:00", "Z"),
        "candles": candles,
    }
