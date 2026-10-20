"""Offline contracts for hourly Binance Spot history."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import ccxt
import duckdb
import polars as pl
import pytest

from quant.ingestion.ohlcv import HOUR_MS, PaginationError, fetch_pages
from quant.ingestion.pipeline import Request, ingest, plan
from quant.ingestion.storage import dataset_path, read_rows

START = datetime(2021, 1, 1, tzinfo=UTC)
NOW = START + timedelta(hours=5, minutes=20)
BASE_MS = int(START.timestamp() * 1000)


def candle(hour: int, close: float = 10.5) -> list:
    return [BASE_MS + hour * HOUR_MS, 10.0, 11.0, 9.0, close, 2.0]


class MockExchange:
    def __init__(self, pages: dict[int, list | Exception]):
        self.pages = pages
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> list:
        self.calls.append((symbol, timeframe, since, limit))
        result = self.pages.get(since, [])
        if isinstance(result, Exception):
            raise result
        return result


def request(tmp_path, *, end_hour: int = 2, **kwargs) -> Request:
    return Request(
        symbol="BTC/USDT",
        start=START,
        end=START + timedelta(hours=end_hour),
        data_root=tmp_path,
        **kwargs,
    )


def silver(tmp_path) -> list[dict]:
    return read_rows(dataset_path(tmp_path, "silver", "BTC/USDT"))


def bronze(tmp_path) -> list[dict]:
    return read_rows(dataset_path(tmp_path, "bronze", "BTC/USDT"))


def availability_file(tmp_path, start: datetime | None, evidence: str | None):
    path = tmp_path / "availability.json"
    path.write_text(
        json.dumps(
            {
                "BTC/USDT": {
                    "verified_start_utc": start.isoformat() if start else None,
                    "evidence": evidence,
                }
            }
        )
    )
    return path


def test_normal_ingestion_and_utc_schema(tmp_path) -> None:
    result = ingest(
        request(tmp_path),
        exchange=MockExchange({BASE_MS: [candle(i) for i in range(3)]}),
        now=NOW,
    )
    assert result["ingestion_status"] == "complete"
    assert result["expected_candle_count"] == result["observed_candle_count"] == 3
    assert result["missing_candle_count"] == result["rejected_record_count"] == 0
    assert result["coverage_status"] == "complete"
    assert result["verified_instrument_availability_start"] is None
    assert result["first_observed_candle"] == START.isoformat()
    rows = silver(tmp_path)
    assert len(rows) == 3
    assert rows[0]["timestamp"] == START
    assert rows[0]["timestamp"].utcoffset() == timedelta(0)
    assert rows[0]["ingested_at"].utcoffset() == timedelta(0)
    assert (
        pl.read_parquet(dataset_path(tmp_path, "silver", "BTC/USDT")).schema["open"]
        == pl.Float64
    )
    saved = json.loads((tmp_path / "reports/binance/1h/BTC-USDT.json").read_text())
    assert saved == result


def test_pagination_across_bounded_pages(tmp_path) -> None:
    exchange = MockExchange(
        {BASE_MS: [candle(0), candle(1)], BASE_MS + 2 * HOUR_MS: [candle(2)]}
    )
    report = ingest(request(tmp_path, page_size=2), exchange=exchange, now=NOW)
    assert report["ingestion_status"] == "complete"
    assert [call[2:] for call in exchange.calls] == [
        (BASE_MS, 2),
        (BASE_MS + 2 * HOUR_MS, 1),
    ]


def test_empty_response_is_incomplete(tmp_path) -> None:
    report = ingest(request(tmp_path), exchange=MockExchange({}), now=NOW)
    assert report["ingestion_status"] == "incomplete"
    assert report["missing_candle_count"] == 3
    assert silver(tmp_path) == []


def test_empty_page_does_not_end_scan(tmp_path) -> None:
    exchange = MockExchange({BASE_MS + 2 * HOUR_MS: [candle(2)]})
    report = ingest(request(tmp_path, page_size=2), exchange=exchange, now=NOW)
    assert len(exchange.calls) == 2
    assert report["missing_candle_count"] == 2


def test_future_only_page_before_listing_is_recorded_as_gap(tmp_path) -> None:
    exchange = MockExchange(
        {
            BASE_MS: [candle(2)],
            BASE_MS + HOUR_MS: [candle(2)],
            BASE_MS + 2 * HOUR_MS: [candle(2)],
        }
    )
    report = ingest(request(tmp_path, page_size=1), exchange=exchange, now=NOW)
    assert report["ingestion_status"] == "incomplete"
    assert report["missing_candle_count"] == 2
    assert len(bronze(tmp_path)) == 1


def test_duplicate_candles_counted_but_canonical_unique(tmp_path) -> None:
    report = ingest(
        request(tmp_path, end_hour=0),
        exchange=MockExchange({BASE_MS: [candle(0), candle(0)]}),
        now=NOW,
    )
    assert report["duplicate_count"] == 1
    assert report["conflict_revision_count"] == 0
    assert len(silver(tmp_path)) == len(bronze(tmp_path)) == 1


def test_conflicting_revision_preserved_and_latest_wins(tmp_path) -> None:
    ingest(
        request(tmp_path, end_hour=0),
        exchange=MockExchange({BASE_MS: [candle(0)]}),
        now=NOW,
    )
    revised = candle(0, 10.8)
    report = ingest(
        request(tmp_path, end_hour=0),
        exchange=MockExchange({BASE_MS: [revised]}),
        now=NOW,
    )
    assert report["conflict_revision_count"] == 1
    assert len(bronze(tmp_path)) == 2
    assert silver(tmp_path)[0]["close"] == 10.8


def test_provider_value_reversion_becomes_canonical(tmp_path) -> None:
    run = request(tmp_path, end_hour=0)
    original = candle(0)
    revised = candle(0, 10.8)
    ingest(run, exchange=MockExchange({BASE_MS: [original]}), now=NOW)
    ingest(run, exchange=MockExchange({BASE_MS: [revised]}), now=NOW)
    report = ingest(run, exchange=MockExchange({BASE_MS: [original]}), now=NOW)
    assert len(bronze(tmp_path)) == 3
    assert silver(tmp_path)[0]["close"] == 10.5
    assert report["conflict_revision_count"] == 1


def test_missing_hour_detected_without_fill(tmp_path) -> None:
    report = ingest(
        request(tmp_path),
        exchange=MockExchange({BASE_MS: [candle(0), candle(2)]}),
        now=NOW,
    )
    assert report["ingestion_status"] == "incomplete"
    assert report["missing_candle_count"] == 1
    assert report["coverage_status"] == "unknown"
    assert report["unknown_coverage_candle_count"] == 1
    assert report["missing_within_verified_coverage_count"] == 0
    assert report["unobserved_timestamps"] == [
        (START + timedelta(hours=1)).isoformat()
    ]
    assert [row["timestamp"] for row in silver(tmp_path)] == [
        START,
        START + timedelta(hours=2),
    ]


def test_explicit_verified_start_separates_preavailability_and_missing(
    tmp_path,
) -> None:
    evidence = "https://example.org/verified-instrument-record"
    config = availability_file(tmp_path, START + timedelta(hours=1), evidence)
    run = Request(
        symbol="BTC/USDT",
        start=START,
        end_exclusive=START + timedelta(hours=4),
        data_root=tmp_path,
        availability_config=config,
    )
    report = ingest(
        run,
        exchange=MockExchange({BASE_MS: [candle(1), candle(3)]}),
        now=NOW,
    )
    assert report["requested_end_exclusive"] == (START + timedelta(hours=4)).isoformat()
    assert report["expected_candle_count"] == 4
    assert report["observed_candle_count"] == 2
    assert report["missing_candle_count"] == 2
    assert report["pre_availability_candle_count"] == 1
    assert report["unknown_coverage_candle_count"] == 0
    assert report["missing_within_verified_coverage_count"] == 1
    assert report["missing_timestamps"] == [(START + timedelta(hours=2)).isoformat()]
    assert report["unobserved_timestamps"] == [
        START.isoformat(),
        (START + timedelta(hours=2)).isoformat(),
    ]
    assert report["availability_evidence"] == evidence
    assert report["first_observed_candle"] == (START + timedelta(hours=1)).isoformat()
    assert report["coverage_status"] == "incomplete"


def test_first_observed_is_not_inferred_listing_date(tmp_path) -> None:
    report = ingest(
        request(tmp_path),
        exchange=MockExchange({BASE_MS: [candle(1), candle(2)]}),
        now=NOW,
    )
    assert report["verified_instrument_availability_start"] is None
    assert report["first_observed_candle"] == (START + timedelta(hours=1)).isoformat()
    assert report["unknown_coverage_candle_count"] == 1
    assert report["pre_availability_candle_count"] == 0
    assert report["unknown_coverage_periods"] == [
        {
            "start": START.isoformat(),
            "end_exclusive": (START + timedelta(hours=1)).isoformat(),
        }
    ]


def test_verified_availability_requires_evidence(tmp_path) -> None:
    config = availability_file(tmp_path, START, None)
    with pytest.raises(ValueError, match="requires evidence"):
        plan(request(tmp_path, availability_config=config), now=NOW)


def test_observation_before_verified_start_flags_conflict(tmp_path) -> None:
    config = availability_file(tmp_path, START + timedelta(hours=1), "verified record")
    report = ingest(
        request(tmp_path, end_hour=1, availability_config=config),
        exchange=MockExchange({BASE_MS: [candle(0), candle(1)]}),
        now=NOW,
    )
    assert report["coverage_status"] == "availability_conflict"
    assert report["availability_conflict_timestamps"] == [START.isoformat()]


def test_exclusive_end_counts_exact_hours(tmp_path) -> None:
    run = Request(
        symbol="BTC/USDT",
        start=START,
        end_exclusive=START + timedelta(hours=4),
        data_root=tmp_path,
        page_size=2,
    )
    exchange = MockExchange(
        {
            BASE_MS: [candle(0), candle(1)],
            BASE_MS + 2 * HOUR_MS: [candle(2), candle(3)],
        }
    )
    report = ingest(run, exchange=exchange, now=NOW)
    assert report["requested_end"] == (START + timedelta(hours=3)).isoformat()
    assert report["requested_end_exclusive"] == (START + timedelta(hours=4)).isoformat()
    assert report["expected_candle_count"] == 4
    assert report["fetched_page_count"] == 2
    assert report["last_observed_candle"] == (START + timedelta(hours=3)).isoformat()


@pytest.mark.parametrize(
    "bad",
    [
        [BASE_MS, 10, 9, 8, 10, 2],
        [BASE_MS, 10, 11, 9, 10, -1],
        [BASE_MS, float("nan"), 11, 9, 10, 2],
        [BASE_MS, 0, 11, 9, 10, 2],
        [BASE_MS + 1, 10, 11, 9, 10, 2],
    ],
)
def test_invalid_ohlcv_rejected(tmp_path, bad) -> None:
    report = ingest(
        request(tmp_path, end_hour=0), exchange=MockExchange({BASE_MS: [bad]}), now=NOW
    )
    assert report["rejected_record_count"] == 1
    assert report["missing_candle_count"] == 1
    assert len(bronze(tmp_path)) == 1


def test_incomplete_current_candle_excluded(tmp_path) -> None:
    report = ingest(
        request(tmp_path, end_hour=4),
        exchange=MockExchange({BASE_MS: [candle(i) for i in range(6)]}),
        now=NOW,
    )
    assert report["ingestion_status"] == "complete"
    assert report["rejected_record_count"] == 1
    assert len(silver(tmp_path)) == 5


def test_preclose_observation_needs_postclose_refetch(tmp_path) -> None:
    early = START + timedelta(hours=1, minutes=20)
    later = START + timedelta(hours=2, minutes=20)
    run = request(tmp_path, end_hour=1)
    with pytest.raises(ValueError, match="fully closed"):
        ingest(run, exchange=MockExchange({BASE_MS: [candle(1)]}), now=early)
    initial = ingest(
        request(tmp_path, end_hour=0),
        exchange=MockExchange({BASE_MS: [candle(0), candle(1)]}),
        now=early,
    )
    assert initial["rejected_record_count"] == 1
    assert len(bronze(tmp_path)) == 2
    without_refetch = ingest(run, exchange=MockExchange({}), now=later)
    assert without_refetch["missing_candle_count"] == 1
    assert len(silver(tmp_path)) == 1
    refreshed = ingest(run, exchange=MockExchange({BASE_MS: [candle(1)]}), now=later)
    assert refreshed["ingestion_status"] == "complete"
    assert len(bronze(tmp_path)) == 3
    assert len(silver(tmp_path)) == 2


def test_transient_failure_retried_and_permanent_failure_reported(tmp_path) -> None:
    class RetryExchange(MockExchange):
        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            if not self.calls:
                self.calls.append((symbol, timeframe, since, limit))
                raise ccxt.RateLimitExceeded("temporary")
            return super().fetch_ohlcv(symbol, timeframe, since, limit)

    exchange = RetryExchange({BASE_MS: [candle(0)]})
    pages = list(
        fetch_pages(exchange, "BTC/USDT", BASE_MS, BASE_MS, sleep=lambda _: None)
    )
    assert pages == [[candle(0)]]
    assert len(exchange.calls) == 2
    with pytest.raises(ccxt.BadSymbol):
        ingest(
            request(tmp_path, end_hour=0),
            exchange=MockExchange({BASE_MS: ccxt.BadSymbol("bad")}),
            now=NOW,
        )
    saved = json.loads((tmp_path / "reports/binance/1h/BTC-USDT.json").read_text())
    assert saved["ingestion_status"] == "failed"
    assert "BadSymbol" in saved["failure_details"]


def test_transient_failure_exhausts_bounded_retries() -> None:
    exchange = MockExchange({BASE_MS: ccxt.NetworkError("offline")})
    delays = []
    with pytest.raises(ccxt.NetworkError):
        list(
            fetch_pages(
                exchange,
                "BTC/USDT",
                BASE_MS,
                BASE_MS,
                max_retries=2,
                sleep=delays.append,
            )
        )
    assert len(exchange.calls) == 3
    assert delays == [1, 2]


def test_pagination_stalls_and_repeated_pages() -> None:
    exchange = MockExchange({BASE_MS: [candle(0)], BASE_MS + HOUR_MS: [candle(0)]})
    with pytest.raises(PaginationError):
        list(fetch_pages(exchange, "BTC/USDT", BASE_MS, BASE_MS + HOUR_MS, page_size=1))


def test_interrupted_silver_write_is_recoverable(tmp_path, monkeypatch) -> None:
    from quant.ingestion import pipeline

    original = pipeline.atomic_parquet
    failed = False

    def interrupted(path, rows, schema):
        nonlocal failed
        if "silver" in path.parts and not failed:
            failed = True
            raise OSError("simulated interruption")
        original(path, rows, schema)

    monkeypatch.setattr(pipeline, "atomic_parquet", interrupted)
    with pytest.raises(OSError, match="interruption"):
        ingest(
            request(tmp_path, end_hour=0),
            exchange=MockExchange({BASE_MS: [candle(0)]}),
            now=NOW,
        )
    assert len(bronze(tmp_path)) == 1
    assert not dataset_path(tmp_path, "silver", "BTC/USDT").exists()
    report = ingest(
        request(tmp_path, end_hour=0),
        exchange=MockExchange({BASE_MS: [candle(0)]}),
        now=NOW,
    )
    assert report["ingestion_status"] == "complete"
    assert len(silver(tmp_path)) == 1


def test_atomic_replace_failure_preserves_previous_snapshot(
    tmp_path, monkeypatch
) -> None:
    from quant.ingestion import storage

    path = dataset_path(tmp_path, "silver", "BTC/USDT")
    previous = {
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "timestamp": START,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 2.0,
        "ingested_at": NOW,
    }
    storage.atomic_parquet(path, [previous], storage.SILVER_SCHEMA)
    replacement = {**previous, "close": 10.8}
    with monkeypatch.context() as patcher:
        patcher.setattr(
            storage.os,
            "replace",
            lambda *_: (_ for _ in ()).throw(OSError("interrupted")),
        )
        with pytest.raises(OSError, match="interrupted"):
            storage.atomic_parquet(path, [replacement], storage.SILVER_SCHEMA)
    assert read_rows(path) == [previous]
    assert list(path.parent.glob(".*.tmp")) == []


def test_repeat_ingestion_is_idempotent(tmp_path) -> None:
    exchange = MockExchange({BASE_MS: [candle(0)]})
    run = request(tmp_path, end_hour=0)
    ingest(run, exchange=exchange, now=NOW)
    before = silver(tmp_path)
    ingest(run, exchange=exchange, now=NOW)
    assert silver(tmp_path) == before
    assert len(bronze(tmp_path)) == 1


def test_incremental_overlap_revises_existing_candle(tmp_path) -> None:
    ingest(
        request(tmp_path),
        exchange=MockExchange({BASE_MS: [candle(i) for i in range(3)]}),
        now=NOW,
    )
    revised = candle(2, 10.8)
    exchange = MockExchange({BASE_MS + HOUR_MS: [candle(1), revised, candle(3)]})
    incremental = Request(
        symbol="BTC/USDT",
        start=START,
        end=START + timedelta(hours=3),
        mode="incremental",
        overlap_hours=1,
        data_root=tmp_path,
    )
    report = ingest(incremental, exchange=exchange, now=NOW)
    assert exchange.calls[0][2] == BASE_MS + HOUR_MS
    assert report["ingestion_status"] == "complete"
    assert silver(tmp_path)[2]["close"] == 10.8
    assert len(silver(tmp_path)) == 4


def test_timestamp_utc_normalization_and_naive_rejection(tmp_path) -> None:
    shifted = START.astimezone(timezone(timedelta(hours=7)))
    report = ingest(
        Request(symbol="BTC/USDT", start=shifted, end=shifted, data_root=tmp_path),
        exchange=MockExchange({BASE_MS: [candle(0)]}),
        now=NOW,
    )
    assert report["requested_start"] == START.isoformat()
    assert silver(tmp_path)[0]["timestamp"] == START
    with pytest.raises(ValueError, match="timezone-aware"):
        plan(Request(symbol="BTC/USDT", start=datetime(2021, 1, 1)), now=NOW)


def test_duckdb_queries_silver_parquet(tmp_path) -> None:
    ingest(
        request(tmp_path),
        exchange=MockExchange({BASE_MS: [candle(i) for i in range(3)]}),
        now=NOW,
    )
    path = dataset_path(tmp_path, "silver", "BTC/USDT")
    result = duckdb.sql(
        "SELECT count(*), min(timestamp), max(timestamp) FROM read_parquet(?)",
        params=[str(path)],
    ).fetchone()
    assert result[0] == 3
    assert result[1].astimezone(UTC) == START
    assert result[2].astimezone(UTC) == START + timedelta(hours=2)


def test_dry_run_never_uses_exchange_or_writes(tmp_path) -> None:
    class ForbiddenExchange:
        def fetch_ohlcv(self, *args, **kwargs):
            raise AssertionError("dry run fetched market data")

    report = ingest(
        request(tmp_path, dry_run=True), exchange=ForbiddenExchange(), now=NOW
    )
    assert report["ingestion_status"] == "dry_run"
    assert not (tmp_path / "bronze").exists()
    assert not (tmp_path / "reports").exists()
