"""Isolated, delayed external FX aggregates. Never connects to a broker.

Massive Currencies Basic is documented as end-of-day, not live.  The response
cannot prove broker-executable bid/ask or a particular account's entitlements.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .pipeline import PROJECT_ROOT, json_bytes, within

PROVIDER = "massive"
TICKERS = {"EURUSDm": "C:EURUSD", "XAUUSDm": "C:XAUUSD"}
# Native four-hour aggregate anchor/session semantics are not verified.
TIMEFRAMES = {"M15": (15, timedelta(minutes=15)), "H1": (60, timedelta(hours=1))}
REFRESH_SECONDS = 24 * 60 * 60
FAILURE_BACKOFF_SECONDS = 15 * 60
MANUAL_MINIMUM_SECONDS = 15 * 60
MAX_CALLS_PER_MINUTE = 5
LOOKBACK_DAYS = 40


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class MarketDataProvider(Protocol):
    def get(
        self,
        symbol: str,
        timeframe: str,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict: ...


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _network(
    url: str, headers: dict[str, str], timeout: float
) -> tuple[int, bytes, dict]:
    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            return response.status, response.read(8_000_001), dict(response.headers)
    except HTTPError as exc:
        return exc.code, b"", dict(exc.headers or {})
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError(
            "network_error", "External data request failed or timed out."
        ) from exc


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(
            "malformed_data", "Provider returned nonnumeric OHLC values."
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ProviderError("malformed_data", "Provider returned invalid OHLC values.")
    return number


def parse_aggregates(
    body: bytes,
    ticker: str,
    timeframe: str,
    *,
    cutoff: datetime,
    start: datetime | None = None,
) -> dict:
    """Validate one provider result and retain only bars ending before cutoff.

    Cutoff is deliberately the start of the current UTC date, not live time.
    The provider's end-of-day status is a delay classification, not an SLA.
    """
    if timeframe not in TIMEFRAMES:
        raise ProviderError("unsupported_timeframe", "This timeframe is not available.")
    if len(body) > 8_000_000:
        raise ProviderError(
            "malformed_data", "Provider response exceeds the size limit."
        )
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderError(
            "malformed_data", "Provider response is not valid JSON."
        ) from exc
    if (
        not isinstance(data, dict)
        or data.get("ticker") != ticker
        or data.get("status") not in {"OK", "DELAYED"}
    ):
        raise ProviderError(
            "malformed_data", "Provider response identity or status is invalid."
        )
    # `limit` applies to base aggregates, not returned bars. A saturated
    # query can be truncated without an advertised next page; fail closed.
    query_count = data.get("queryCount")
    if query_count is not None and (
        isinstance(query_count, bool)
        or not isinstance(query_count, int)
        or query_count < 0
    ):
        raise ProviderError(
            "malformed_data", "Provider returned an invalid query count."
        )
    if query_count is not None and query_count >= 50_000:
        raise ProviderError(
            "pagination_required",
            "Provider aggregate query reached its cap; no partial dataset was accepted.",
        )
    # A next page is not followed: its host and entitlement must not leak credentials.
    if data.get("next_url"):
        raise ProviderError(
            "pagination_required",
            "Provider returned a partial page; no data was accepted.",
        )
    records = data.get("results")
    if not isinstance(records, list) or not records:
        raise ProviderError(
            "empty_response", "Provider returned no candles for this request."
        )
    step_ms = int(TIMEFRAMES[timeframe][1].total_seconds() * 1000)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    output = []
    seen = set()
    excluded = 0
    for item in records:
        if not isinstance(item, dict):
            raise ProviderError(
                "malformed_data", "Provider returned an invalid candle."
            )
        stamp = item.get("t")
        if (
            isinstance(stamp, bool)
            or not isinstance(stamp, int)
            or stamp < 0
            or stamp % step_ms
        ):
            raise ProviderError(
                "malformed_timestamp",
                "Provider candle time is not UTC interval-aligned.",
            )
        if start is not None and stamp < int(start.timestamp() * 1000):
            raise ProviderError(
                "unexpected_coverage",
                "Provider returned a candle before the requested range.",
            )
        if stamp in seen:
            raise ProviderError(
                "duplicate_timestamp", "Provider returned duplicate candle timestamps."
            )
        seen.add(stamp)
        o, h, low, close = (_number(item.get(k)) for k in ("o", "h", "l", "c"))
        if h < max(o, low, close) or low > min(o, h, close):
            raise ProviderError(
                "invalid_ohlc", "Provider returned inconsistent OHLC values."
            )
        volume = item.get("v")
        if volume is not None and (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not math.isfinite(volume)
            or volume < 0
        ):
            raise ProviderError("malformed_data", "Provider returned invalid volume.")
        try:
            ts = datetime.fromtimestamp(stamp / 1000, UTC)
        except (ValueError, OverflowError, OSError) as exc:
            raise ProviderError(
                "malformed_timestamp", "Provider returned an out-of-range timestamp."
            ) from exc
        if stamp + step_ms > cutoff_ms:
            excluded += 1
            continue
        output.append(
            {
                "timestamp_utc": _iso(ts),
                "source_timestamp_ms": stamp,
                "open": o,
                "high": h,
                "low": low,
                "close": close,
                "provider_volume": volume,
                "completion": "THEORETICAL_CLOSED_UNVERIFIED",
                "complete_basis": "ended_before_current_utc_day",
            }
        )
    output.sort(key=lambda x: x["source_timestamp_ms"])
    if not output:
        raise ProviderError(
            "empty_response", "No conservatively completed candles are available."
        )
    # No provider finality flag was established. Exclude the newest nominally
    # closed observation from all chart analysis; preserve it separately.
    latest_observed = output[-1]
    eligible = output[:-1]
    gaps = []
    for first, second in pairwise(output):
        delta = second["source_timestamp_ms"] - first["source_timestamp_ms"]
        if delta > step_ms:
            gaps.append(
                {
                    "after_utc": first["timestamp_utc"],
                    "before_utc": second["timestamp_utc"],
                    "missing_intervals": delta // step_ms - 1,
                    "classification": "unknown",
                }
            )
    return {
        "candles": eligible,
        "latest_observed_candle": latest_observed,
        "gaps": gaps,
        "excluded_unconfirmed_count": excluded + 1,
    }


class ExternalMarketService:
    """Process-local quota guard and isolated content-addressed last-good cache."""

    def __init__(
        self,
        *,
        cache_root: Path | None = None,
        transport: Callable = _network,
        sleeper: Callable = time.sleep,
        monotonic: Callable = time.monotonic,
        key_provider: Callable[[], str | None] | None = None,
    ):
        self.cache_root = within(
            cache_root or PROJECT_ROOT / "data/external", PROJECT_ROOT
        )
        self.transport = transport
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.key_provider = key_provider or (lambda: os.environ.get("MASSIVE_API_KEY"))
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()
        self._cooldown_until = 0.0
        self._attempts: dict[tuple[str, str], float] = {}
        self._last_errors: dict[tuple[str, str], ProviderError] = {}

    def _write_once(self, path: Path, body: bytes) -> None:
        path = within(path, self.cache_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(body)
        except FileExistsError:
            if path.read_bytes() != body:
                raise ProviderError(
                    "cache_corrupt", "External cache identity conflict."
                ) from None

    def _save(self, symbol: str, timeframe: str, raw: bytes, snapshot: dict) -> dict:
        raw_hash = _sha(raw)
        snapshot["source_payload_sha256"] = raw_hash
        self._write_once(self.cache_root / "raw" / f"{raw_hash}.json", raw)
        normalized = json_bytes(snapshot)
        identity = _sha(normalized)
        self._write_once(
            self.cache_root / "normalized" / f"{identity}.json", normalized
        )
        pointer = self.cache_root / "pointers" / f"{symbol}-{timeframe}.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        temp = pointer.with_suffix(".tmp")
        temp.write_bytes(json_bytes({"snapshot_sha256": identity}))
        temp.replace(pointer)
        return {**snapshot, "snapshot_sha256": identity}

    def _load(self, symbol: str, timeframe: str) -> dict | None:
        pointer = self.cache_root / "pointers" / f"{symbol}-{timeframe}.json"
        if not pointer.exists():
            return None
        try:
            identity = json.loads(pointer.read_bytes())["snapshot_sha256"]
            if (
                not isinstance(identity, str)
                or len(identity) != 64
                or any(c not in "0123456789abcdef" for c in identity)
            ):
                raise ValueError("invalid hash")
            body = (self.cache_root / "normalized" / f"{identity}.json").read_bytes()
            if _sha(body) != identity:
                raise ValueError("snapshot hash mismatch")
            value = json.loads(body)
            if (
                value["provider"] != PROVIDER
                or value["symbol"] != symbol
                or value["timeframe"] != timeframe
            ):
                raise ValueError("snapshot identity mismatch")
            raw_hash = value["source_payload_sha256"]
            if (
                not isinstance(raw_hash, str)
                or len(raw_hash) != 64
                or any(c not in "0123456789abcdef" for c in raw_hash)
            ):
                raise ValueError("invalid payload hash")
            if (
                _sha((self.cache_root / "raw" / f"{raw_hash}.json").read_bytes())
                != raw_hash
            ):
                raise ValueError("payload hash mismatch")
            return {**value, "snapshot_sha256": identity}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                "cache_corrupt", "External cache failed integrity validation."
            ) from exc

    def _with_freshness(self, cached: dict, now: datetime, error: dict | None) -> dict:
        latest = datetime.fromisoformat(
            cached["latest_observed_candle"]["timestamp_utc"]
        )
        step = TIMEFRAMES[cached["timeframe"]][1]
        age = max(0, int((now - latest - step).total_seconds()))
        return {
            **cached,
            "freshness": "STALE" if age > 48 * 60 * 60 else "DELAYED_EOD",
            "data_age_seconds": age,
            "error": error,
        }

    def _failure(self, cached: dict | None, error: ProviderError) -> dict:
        if cached is None:
            raise error
        return {
            **cached,
            "freshness": "STALE_AFTER_ERROR",
            "error": {"code": error.code, "message": error.message},
        }

    def read_cached(
        self, symbol: str, timeframe: str, *, now: datetime | None = None
    ) -> dict | None:
        """Read only: never use a provider key or initiate a refresh."""
        if symbol not in TICKERS:
            raise ProviderError(
                "unsupported_symbol", "External provider does not support this symbol."
            )
        if timeframe not in TIMEFRAMES:
            raise ProviderError(
                "unsupported_timeframe",
                "External H4 is disabled until its session anchor is verified.",
            )
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone aware")
        with self._lock:
            cached = self._load(symbol, timeframe)
            if cached is None:
                return None
            error = self._last_errors.get((symbol, timeframe))
            if error:
                return self._failure(cached, error)
            return self._with_freshness(cached, now, None)

    def get(
        self,
        symbol: str,
        timeframe: str,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict:
        if symbol not in TICKERS:
            raise ProviderError(
                "unsupported_symbol", "External provider does not support this symbol."
            )
        if timeframe not in TIMEFRAMES:
            raise ProviderError(
                "unsupported_timeframe",
                "External H4 is disabled until its session anchor is verified.",
            )
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone aware")
        now = now.astimezone(UTC)
        with self._lock:
            cached = self._load(symbol, timeframe)
            key = self.key_provider()
            if not key:
                return self._failure(
                    cached,
                    ProviderError(
                        "missing_api_key",
                        "Set MASSIVE_API_KEY locally to use external data.",
                    ),
                )
            tick = self.monotonic()
            pair = (symbol, timeframe)
            last = self._attempts.get(pair)
            prior_error = self._last_errors.get(pair)
            elapsed_limit = (
                (FAILURE_BACKOFF_SECONDS if force else REFRESH_SECONDS)
                if prior_error
                else MANUAL_MINIMUM_SECONDS
            )
            if last is not None and tick - last < elapsed_limit:
                if prior_error is not None:
                    return self._failure(cached, prior_error)
                if cached is not None:
                    return self._with_freshness(
                        cached,
                        now,
                        {
                            "code": "refresh_throttled",
                            "message": "Refresh is limited to once per 15 minutes per market.",
                        }
                        if force
                        else None,
                    )
            if cached is not None and not force and prior_error is None:
                try:
                    fetched = datetime.fromisoformat(
                        cached["last_successful_fetch_utc"]
                    )
                    age = (now - fetched).total_seconds()
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProviderError(
                        "cache_corrupt",
                        "External cache has an invalid fetch timestamp.",
                    ) from exc
                if 0 <= age < REFRESH_SECONDS:
                    return self._with_freshness(cached, now, None)
            if tick < self._cooldown_until:
                return self._failure(
                    cached,
                    ProviderError(
                        "rate_limited", "Provider rate limit reached; retry later."
                    ),
                )
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_ms = int((cutoff - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
            end_ms = int(cutoff.timestamp() * 1000) - 1
            ticker = TICKERS[symbol]
            minutes, _ = TIMEFRAMES[timeframe]
            params = urlencode({"adjusted": "true", "sort": "asc", "limit": 50000})
            url = f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/{minutes}/minute/{start_ms}/{end_ms}?{params}"
            self._attempts[(symbol, timeframe)] = tick
            try:
                for attempt in range(3):
                    tick = self.monotonic()
                    while self._calls and tick - self._calls[0] >= 60:
                        self._calls.popleft()
                    if len(self._calls) >= MAX_CALLS_PER_MINUTE:
                        raise ProviderError(
                            "rate_limited",
                            "Local five-per-minute limit reached; retry later.",
                        )
                    self._calls.append(tick)
                    try:
                        status, body, _headers = self.transport(
                            url, {"Authorization": f"Bearer {key}"}, 10.0
                        )
                    except ProviderError:
                        if attempt < 2:
                            self.sleeper(0.25 * (2**attempt))
                            continue
                        raise
                    if status == 429:
                        retry_after = next(
                            (
                                v
                                for k, v in _headers.items()
                                if str(k).lower() == "retry-after"
                            ),
                            None,
                        )
                        seconds = int(retry_after) if str(retry_after).isdigit() else 60
                        self._cooldown_until = tick + max(60, seconds)
                        raise ProviderError(
                            "rate_limited", "Provider rate limit reached; retry later."
                        )
                    if status in {401, 403}:
                        raise ProviderError(
                            "authentication_or_entitlement",
                            "Provider rejected the key or instrument entitlement.",
                        )
                    if status in {500, 502, 503, 504} and attempt < 2:
                        self.sleeper(0.25 * (2**attempt))
                        continue
                    if status != 200:
                        raise ProviderError(
                            "provider_error",
                            f"Provider request failed with HTTP {status}.",
                        )
                    parsed = parse_aggregates(
                        body,
                        ticker,
                        timeframe,
                        cutoff=cutoff,
                        start=cutoff - timedelta(days=LOOKBACK_DAYS),
                    )
                    data = {
                        "provider": PROVIDER,
                        "symbol": symbol,
                        "provider_ticker": ticker,
                        "timeframe": timeframe,
                        "source_timezone": "UTC",
                        "last_successful_fetch_utc": _iso(now),
                        "freshness": "DELAYED_EOD",
                        "provider_delay": "End-of-day plan; exact publication delay unknown.",
                        "requested_start_utc": _iso(
                            cutoff - timedelta(days=LOOKBACK_DAYS)
                        ),
                        "requested_end_exclusive_utc": _iso(cutoff),
                        "latest_completed_candle_utc": None,
                        "latest_nominally_closed_candle_utc": (
                            parsed["candles"][-1]["timestamp_utc"]
                            if parsed["candles"]
                            else None
                        ),
                        "execution_eligibility": "BLOCKED_UNVERIFIED",
                        **parsed,
                    }
                    self._last_errors.pop((symbol, timeframe), None)
                    return self._with_freshness(
                        self._save(symbol, timeframe, body, data), now, None
                    )
                raise ProviderError(
                    "provider_error", "Provider request failed after bounded retries."
                )
            except ProviderError as exc:
                self._last_errors[(symbol, timeframe)] = exc
                return self._failure(cached, exc)
