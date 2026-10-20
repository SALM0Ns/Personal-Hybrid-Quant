"""Historical Bronze to Silver orchestration and coverage reporting."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant.ingestion.ohlcv import HOUR_MS, binance_spot, fetch_pages
from quant.ingestion.storage import (
    BRONZE_SCHEMA,
    SILVER_SCHEMA,
    atomic_parquet,
    dataset_path,
    read_rows,
)
from quant.validation.coverage import coverage_report, verified_availability
from quant.validation.ohlcv import canonicalize, utc_from_ms

DEFAULT_START = datetime(2021, 1, 1, tzinfo=UTC)
SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
HOUR = timedelta(hours=1)


def latest_closed(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(UTC).replace(minute=0, second=0, microsecond=0) - HOUR


def hour_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    timestamp = int(value.timestamp() * 1000)
    if timestamp % HOUR_MS:
        raise ValueError("timestamps must align to UTC hourly candle opens")
    return timestamp


@dataclass(frozen=True)
class Request:
    symbol: str
    start: datetime = DEFAULT_START
    end: datetime | None = None
    end_exclusive: datetime | None = None
    mode: str = "backfill"
    overlap_hours: int = 24
    data_root: Path = Path("data")
    dry_run: bool = False
    page_size: int = 1000
    availability_config: Path = Path("configs/availability.json")


def plan(request: Request, *, now: datetime | None = None) -> dict:
    if request.symbol not in SYMBOLS:
        raise ValueError(f"Unsupported Binance Spot symbol: {request.symbol}")
    if request.mode not in {"backfill", "incremental"}:
        raise ValueError("mode must be backfill or incremental")
    if request.overlap_hours < 0 or not 1 <= request.page_size <= 1000:
        raise ValueError("overlap_hours must be nonnegative and page_size 1..1000")
    now = now or datetime.now(UTC)
    closed = latest_closed(now)
    start_ms = hour_ms(request.start)
    if request.end is not None and request.end_exclusive is not None:
        raise ValueError("Specify either end or end_exclusive, not both")
    if request.end_exclusive is not None:
        end_exclusive_ms = hour_ms(request.end_exclusive)
        end_ms = end_exclusive_ms - HOUR_MS
    else:
        end_ms = hour_ms(request.end) if request.end else hour_ms(closed)
        end_exclusive_ms = end_ms + HOUR_MS
    if end_ms > hour_ms(closed):
        raise ValueError("end must be a fully closed candle open")
    if start_ms > end_ms:
        raise ValueError("start must not exceed end")
    verified_start, evidence = verified_availability(
        request.availability_config, request.symbol
    )
    fetch_start_ms = start_ms
    if request.mode == "incremental":
        silver = read_rows(dataset_path(request.data_root, "silver", request.symbol))
        if silver:
            last_ms = max(hour_ms(row["timestamp"]) for row in silver)
            fetch_start_ms = max(start_ms, last_ms - request.overlap_hours * HOUR_MS)
    return {
        "exchange": "binance",
        "symbol": request.symbol,
        "timeframe": "1h",
        "mode": request.mode,
        "requested_start": utc_from_ms(start_ms).isoformat(),
        "requested_end": utc_from_ms(end_ms).isoformat(),
        "requested_end_exclusive": utc_from_ms(end_exclusive_ms).isoformat(),
        "interval_convention": "[start,end)",
        "verified_instrument_availability_start": (
            verified_start.isoformat() if verified_start else None
        ),
        "availability_evidence": evidence,
        "fetch_start": utc_from_ms(fetch_start_ms).isoformat(),
        "latest_complete_candle": closed.isoformat(),
        "expected_candle_count": (end_ms - start_ms) // HOUR_MS + 1,
        "estimated_pages": (end_ms - fetch_start_ms) // (request.page_size * HOUR_MS)
        + 1
        if fetch_start_ms <= end_ms
        else 0,
    }


def _report_path(root: Path, symbol: str) -> Path:
    return root / "reports" / "binance" / "1h" / f"{symbol.replace('/', '-')}.json"


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _observation_key(raw: object, content_hash: str) -> object:
    """Use the candle open for revisions; malformed rows identify themselves."""
    if (
        isinstance(raw, list)
        and raw
        and isinstance(raw[0], int)
        and not isinstance(raw[0], bool)
    ):
        return raw[0]
    return content_hash


def ingest(
    request: Request, *, exchange: object | None = None, now: datetime | None = None
) -> dict:
    """Fetch, preserve revision events, rebuild Silver, and verify coverage.

    Bronze is committed first. If a later write fails, the next run rebuilds
    Silver from durable Bronze observations. No completion report is published
    until both datasets and the coverage check have finished.
    """
    summary = plan(request, now=now)
    if request.dry_run:
        return {**summary, "ingestion_status": "dry_run"}
    start_ms = hour_ms(datetime.fromisoformat(summary["requested_start"]))
    end_ms = hour_ms(datetime.fromisoformat(summary["requested_end"]))
    end_exclusive_ms = hour_ms(
        datetime.fromisoformat(summary["requested_end_exclusive"])
    )
    fetch_ms = hour_ms(datetime.fromisoformat(summary["fetch_start"]))
    closed_ms = hour_ms(datetime.fromisoformat(summary["latest_complete_candle"]))
    bronze_path = dataset_path(request.data_root, "bronze", request.symbol)
    silver_path = dataset_path(request.data_root, "silver", request.symbol)
    observations = read_rows(bronze_path)
    latest_content: dict[object, tuple[str, datetime]] = {}
    for row in sorted(observations, key=lambda item: item["observed_at"]):
        raw = json.loads(row["raw_ohlcv"])
        latest_content[_observation_key(raw, row["content_hash"])] = (
            row["content_hash"],
            row["observed_at"],
        )
    batch_seen: set[str] = set()
    repeated_observations = 0
    fetched_page_count = 0
    fetched_observation_count = 0
    new_bronze_event_count = 0
    observed_at = max(
        (now or datetime.now(UTC)).astimezone(UTC),
        max((row["observed_at"] for row in observations), default=DEFAULT_START)
        + timedelta(microseconds=1),
    )
    try:
        if fetch_ms <= end_ms:
            client = exchange if exchange is not None else binance_spot()
            for page in fetch_pages(
                client, request.symbol, fetch_ms, end_ms, page_size=request.page_size
            ):
                fetched_page_count += 1
                fetched_observation_count += len(page)
                for raw in page:
                    raw_json = json.dumps(raw, separators=(",", ":"), allow_nan=True)
                    content_hash = hashlib.sha256(
                        f"binance|{request.symbol}|1h|{raw_json}".encode()
                    ).hexdigest()
                    if content_hash in batch_seen:
                        repeated_observations += 1
                    batch_seen.add(content_hash)
                    key = _observation_key(raw, content_hash)
                    prior = latest_content.get(key)
                    needs_post_close_observation = (
                        isinstance(key, int)
                        and prior is not None
                        and prior[1] < utc_from_ms(key + HOUR_MS) <= observed_at
                    )
                    if (
                        prior is None
                        or prior[0] != content_hash
                        or needs_post_close_observation
                    ):
                        observation_id = hashlib.sha256(
                            f"{content_hash}|{observed_at.isoformat()}".encode()
                        ).hexdigest()
                        observations.append(
                            {
                                "exchange": "binance",
                                "symbol": request.symbol,
                                "timeframe": "1h",
                                "source": "ccxt:binance:spot",
                                "observation_id": observation_id,
                                "content_hash": content_hash,
                                "observed_at": observed_at,
                                "raw_ohlcv": raw_json,
                            }
                        )
                        new_bronze_event_count += 1
                        latest_content[key] = (content_hash, observed_at)
                        observed_at += timedelta(microseconds=1)
        canonical, metrics = canonicalize(observations, closed_ms)
        window = [
            row for row in canonical if start_ms <= hour_ms(row["timestamp"]) <= end_ms
        ]
        expected = summary["expected_candle_count"]
        observed = len(window)
        actual = [row["timestamp"] for row in window]
        verified_start_text = summary["verified_instrument_availability_start"]
        verified_start_ms = (
            hour_ms(datetime.fromisoformat(verified_start_text))
            if verified_start_text
            else None
        )
        coverage = coverage_report(
            start_ms,
            end_exclusive_ms,
            {hour_ms(timestamp) for timestamp in actual},
            verified_start_ms,
        )
        report = {
            **summary,
            **metrics,
            **coverage,
            "quality_metrics_scope": "all_stored_bronze_observations_for_symbol",
            "duplicate_count": metrics["duplicate_count"] + repeated_observations,
            "fetched_page_count": fetched_page_count,
            "fetched_observation_count": fetched_observation_count,
            "new_bronze_event_count": new_bronze_event_count,
            "observed_candle_count": observed,
            "missing_candle_count": expected - observed,
            "first_observed_candle": min(actual).isoformat() if actual else None,
            "last_observed_candle": max(actual).isoformat() if actual else None,
            "actual_coverage_start": min(actual).isoformat() if actual else None,
            "actual_coverage_end": max(actual).isoformat() if actual else None,
            "ingestion_status": "complete" if observed == expected else "incomplete",
            "failure_details": None,
        }
        atomic_parquet(bronze_path, observations, BRONZE_SCHEMA)
        atomic_parquet(silver_path, canonical, SILVER_SCHEMA)
        _write_report(_report_path(request.data_root, request.symbol), report)
        return report
    except Exception as exc:
        failure = {
            **summary,
            "actual_coverage_start": None,
            "actual_coverage_end": None,
            "observed_candle_count": None,
            "missing_candle_count": None,
            "first_observed_candle": None,
            "last_observed_candle": None,
            "missing_timestamps": None,
            "unobserved_timestamps": None,
            "missing_within_verified_coverage_count": None,
            "pre_availability_candle_count": None,
            "pre_availability_periods": None,
            "unknown_coverage_candle_count": None,
            "unknown_coverage_periods": None,
            "availability_conflict_timestamps": None,
            "coverage_status": "failed",
            "duplicate_count": None,
            "conflict_revision_count": None,
            "rejected_record_count": None,
            "fetched_page_count": fetched_page_count,
            "fetched_observation_count": fetched_observation_count,
            "new_bronze_event_count": new_bronze_event_count,
            "quality_metrics_scope": "all_stored_bronze_observations_for_symbol",
            "ingestion_status": "failed",
            "failure_details": f"{type(exc).__name__}: {exc}",
        }
        _write_report(_report_path(request.data_root, request.symbol), failure)
        raise
