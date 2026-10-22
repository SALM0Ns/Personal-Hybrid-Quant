"""Synthetic, offline tests for the read-only historical chart preview."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import duckdb
import pytest

from quant.app.preview import (
    PreviewDataError,
    PreviewNotFoundError,
    load_preview,
)
from quant.app.server import make_handler

START = datetime(2024, 1, 1, tzinfo=UTC)


def candle(hour: int, **changes: object) -> dict:
    row = {
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "timestamp": START + timedelta(hours=hour),
        "open": 100.0 + hour,
        "high": 102.0 + hour,
        "low": 99.0 + hour,
        "close": 101.0 + hour,
        "volume": 2.0,
    }
    row.update(changes)
    return row


def silver(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "silver" / "binance" / "1h" / "BTC-USDT.parquet"
    path.parent.mkdir(parents=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            """CREATE TABLE candles (
                exchange VARCHAR, symbol VARCHAR, timeframe VARCHAR,
                timestamp TIMESTAMPTZ, open DOUBLE, high DOUBLE,
                low DOUBLE, close DOUBLE, volume DOUBLE
            )"""
        )
        connection.executemany(
            "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                tuple(
                    row[key]
                    for key in (
                        "exchange",
                        "symbol",
                        "timeframe",
                        "timestamp",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    )
                )
                for row in rows
            ],
        )
        escaped_path = str(path).replace("'", "''")
        connection.execute(f"COPY candles TO '{escaped_path}' (FORMAT PARQUET)")
    return path


def test_sorted_bounded_preview_is_read_only_and_no_signal(tmp_path: Path) -> None:
    path = silver(tmp_path, [candle(2), candle(0), candle(1)])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    preview = load_preview(tmp_path, limit=2, as_of=START + timedelta(days=2))
    assert [row["time"] for row in preview["candles"]] == [
        int((START + timedelta(hours=hour)).timestamp()) for hour in (1, 2)
    ]
    assert preview["latest_candle_timestamp"] == "2024-01-01T02:00:00Z"
    assert preview["quality_status"] == "CONTIGUOUS WINDOW"
    assert preview["signal"] == "NO SIGNAL"
    assert preview["source"] == "HISTORICAL PREVIEW — NOT LIVE"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_duplicate_timestamps_are_rejected(tmp_path: Path) -> None:
    silver(tmp_path, [candle(0), candle(1), candle(1)])
    with pytest.raises(PreviewDataError, match="duplicate"):
        load_preview(tmp_path, as_of=START + timedelta(days=2))


def test_missing_hours_are_reported_not_filled(tmp_path: Path) -> None:
    silver(tmp_path, [candle(0), candle(3)])
    preview = load_preview(tmp_path, as_of=START + timedelta(days=2))
    assert preview["missing_hours"] == 2
    assert preview["candle_count"] == 2
    assert preview["quality_status"] == "GAPS DETECTED"


@pytest.mark.parametrize(
    "changes",
    [
        {"open": 0},
        {"high": 99},
        {"low": 103},
        {"volume": -1},
        {"close": float("nan")},
        {"close": None},
        {"timestamp": START + timedelta(minutes=30)},
    ],
)
def test_invalid_ohlcv_is_rejected(tmp_path: Path, changes: dict) -> None:
    silver(tmp_path, [candle(0, **changes)])
    with pytest.raises(PreviewDataError):
        load_preview(tmp_path, as_of=START + timedelta(days=2))


def test_incomplete_candle_is_rejected(tmp_path: Path) -> None:
    silver(tmp_path, [candle(1)])
    with pytest.raises(PreviewDataError, match="incomplete"):
        load_preview(tmp_path, as_of=START + timedelta(hours=1, minutes=30))


def test_candle_at_exact_close_boundary_is_displayed(tmp_path: Path) -> None:
    silver(tmp_path, [candle(0, volume=0)])
    preview = load_preview(tmp_path, as_of=START + timedelta(hours=1))
    assert preview["candle_count"] == 1
    assert preview["signal"] == "NO SIGNAL"


def test_missing_dataset_is_reported(tmp_path: Path) -> None:
    with pytest.raises(PreviewNotFoundError, match="not found"):
        load_preview(tmp_path)


def test_http_refresh_returns_preview_and_no_signal(tmp_path: Path) -> None:
    silver(tmp_path, [candle(0)])
    with ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/preview"
            ) as response:
                payload = json.load(response)
                assert response.headers["Cache-Control"] == "no-store"
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert payload["signal"] == "NO SIGNAL"
    assert payload["candle_count"] == 1


def test_frontend_keeps_historical_warning_and_no_signal() -> None:
    root = Path(__file__).resolve().parents[1] / "web"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert "HISTORICAL PREVIEW — NOT LIVE" in html
    assert 'signal.textContent = "NO SIGNAL"' in js
    assert "BUY" not in js and "SELL" not in js
