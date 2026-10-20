"""Bounded, retryable CCXT OHLCV retrieval for Binance spot."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence

import ccxt

HOUR_MS = 3_600_000


class PaginationError(RuntimeError):
    """The provider did not advance through a requested page."""


def binance_spot() -> ccxt.binance:
    """Create a public, rate-limited spot client; no credentials are used."""
    return ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})


def fetch_pages(
    exchange: object,
    symbol: str,
    start_ms: int,
    end_ms: int,
    *,
    page_size: int = 1000,
    max_retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[Sequence[object]]:
    """Fetch every bounded hour window, including windows returning no rows.

    End is an inclusive candle-open timestamp. A short or empty response never
    ends the scan; final coverage is checked against the expected hourly grid.
    """
    if not 1 <= page_size <= 1000 or max_retries < 0:
        raise ValueError("page_size must be 1..1000 and max_retries nonnegative")
    previous_signature: tuple[tuple[object, ...], ...] | None = None
    for cursor in range(start_ms, end_ms + 1, page_size * HOUR_MS):
        count = min(page_size, (end_ms - cursor) // HOUR_MS + 1)
        for attempt in range(max_retries + 1):
            try:
                page = exchange.fetch_ohlcv(symbol, "1h", since=cursor, limit=count)
                break
            except (ccxt.NetworkError, ccxt.RateLimitExceeded):
                if attempt == max_retries:
                    raise
                sleep(min(2**attempt, 30))
        if not isinstance(page, list):
            raise PaginationError("OHLCV response is not a list")
        if page:
            timestamps = [
                row[0] for row in page if isinstance(row, (list, tuple)) and row
            ]
            if not timestamps or not all(isinstance(ts, int) for ts in timestamps):
                raise PaginationError(f"Pagination stalled at {cursor}")
            page_end = cursor + count * HOUR_MS
            if all(ts >= page_end for ts in timestamps):
                # Binance can return the first listed candle for a symbol even
                # when the requested page predates listing. That page belongs
                # to a later window; keep scanning and report the missing hours.
                yield []
                continue
            signature = tuple(tuple(row) for row in page)
            if signature == previous_signature or not any(
                cursor <= ts < page_end for ts in timestamps
            ):
                raise PaginationError(f"Pagination stalled or repeated at {cursor}")
            previous_signature = signature
        yield page
