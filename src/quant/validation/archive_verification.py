"""Read-only comparison of Binance public monthly klines with local Silver."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
GAPS = (
    "2021-02-11 04:00",
    "2021-03-06 02:00",
    "2021-04-20 02:00",
    "2021-04-20 03:00",
    "2021-04-25 05:00",
    "2021-04-25 06:00",
    "2021-04-25 07:00",
    "2021-08-13 02:00",
    "2021-08-13 03:00",
    "2021-08-13 04:00",
    "2021-08-13 05:00",
    "2021-09-29 07:00",
    "2021-09-29 08:00",
    "2023-03-24 13:00",
)
GAP_HOURS = tuple(
    datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=UTC) for value in GAPS
)
MONTHS = tuple(sorted({value.strftime("%Y-%m") for value in GAP_HOURS}))
HOUR_MS = 3_600_000


def checksum_expected(text: str, filename: str) -> str:
    """Accept only a SHA-256 line naming the exact ZIP being verified."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("CHECKSUM must contain exactly one nonempty line")
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", lines[0])
    if match is None or match.group(2) != filename:
        raise ValueError("CHECKSUM has an invalid digest or filename")
    return match.group(1).lower()


def parse_monthly_zip(
    data: bytes, filename: str, month: str
) -> tuple[dict[int, tuple[float, ...]], dict[int, int]]:
    """Validate ZIP and CSV, retaining valid shortened close times as evidence."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        expected_csv = filename.removesuffix(".zip") + ".csv"
        if names != [expected_csv] or archive.testzip() is not None:
            raise ValueError("ZIP member name or CRC failed validation")
        payload = archive.read(expected_csv).decode("utf-8-sig")

    rows: dict[int, tuple[float, ...]] = {}
    shortened_closes: dict[int, int] = {}
    for line_number, row in enumerate(csv.reader(io.StringIO(payload)), start=1):
        try:
            if len(row) != 12:
                raise ValueError("expected 12 CSV columns")
            open_ms, close_ms = int(row[0]), int(row[6])
            if open_ms % HOUR_MS or not open_ms <= close_ms < open_ms + HOUR_MS:
                raise ValueError("invalid hourly open or close time")
            if datetime.fromtimestamp(open_ms / 1000, UTC).strftime("%Y-%m") != month:
                raise ValueError("candle is outside the archive month")
            values = tuple(float(Decimal(value)) for value in row[1:6])
            opening, high, low, close, volume = values
            if not all(math.isfinite(value) for value in values):
                raise ValueError("non-finite OHLCV")
            if min(opening, high, low, close) <= 0 or volume < 0:
                raise ValueError("non-positive price or negative volume")
            if high < max(opening, low, close) or low > min(opening, high, close):
                raise ValueError("inconsistent OHLC")
            if open_ms in rows:
                raise ValueError("duplicate candle open")
            rows[open_ms] = values
            if close_ms != open_ms + HOUR_MS - 1:
                shortened_closes[open_ms] = close_ms
        except (ValueError, InvalidOperation, OverflowError) as exc:
            raise ValueError(f"invalid CSV line {line_number}: {exc}") from exc
    if not rows:
        raise ValueError("archive contains no candles")
    return rows, shortened_closes


def _download(url: str, path: Path) -> str:
    """Download once with bounded retries; never replace an existing archive."""
    if path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "QNT-001B-verification/1.0"}
            )
            with (
                urllib.request.urlopen(request, timeout=30) as response,
                temporary.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            return datetime.now(UTC).isoformat()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(f"HTTP 404: {url}") from exc
            if attempt == 2:
                raise
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise
        finally:
            temporary.unlink(missing_ok=True)
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _silver_rows(root: Path, symbol: str) -> dict[int, tuple[float, ...]]:
    path = root / "silver" / "binance" / "1h" / f"{symbol[:-4]}-USDT.parquet"
    with duckdb.connect(":memory:") as connection:
        connection.execute("SET TimeZone='UTC'")
        rows = connection.execute(
            "SELECT timestamp, open, high, low, close, volume FROM read_parquet(?)",
            [str(path)],
        ).fetchall()
    return {int(row[0].timestamp() * 1000): tuple(row[1:]) for row in rows}


def verify(data_root: Path = Path("data")) -> dict:
    archive_root = data_root / "verification" / "qnt-001b" / "archives"
    silver = {symbol: _silver_rows(data_root, symbol) for symbol in SYMBOLS}
    manifest: list[dict] = []
    archives: dict[tuple[str, str], dict[int, tuple[float, ...]] | None] = {}
    shortened: dict[tuple[str, str], dict[int, int]] = {}

    for symbol in SYMBOLS:
        for month in MONTHS:
            filename = f"{symbol}-1h-{month}.zip"
            url = f"{BASE_URL}/{symbol}/1h/{filename}"
            path = archive_root / filename
            checksum_path = archive_root / f"{filename}.CHECKSUM"
            record = {
                "symbol": symbol,
                "timeframe": "1h",
                "covered_period": month,
                "source_url": url,
                "checksum_url": f"{url}.CHECKSUM",
                "archive_filename": filename,
                "retrieved_at_utc": None,
                "checksum_retrieved_at_utc": None,
                "checksum_status": "not_checked",
                "expected_sha256": None,
                "archive_sha256": None,
                "archive_rows": None,
                "shortened_close_count": None,
                "shortened_close_timestamps_utc": None,
                "shortened_close_details": None,
                "error": None,
            }
            try:
                record["retrieved_at_utc"] = _download(url, path)
            except FileNotFoundError as exc:
                record["checksum_status"] = "archive_unavailable"
                record["error"] = str(exc)
                archives[(symbol, month)] = None
                manifest.append(record)
                continue
            except Exception as exc:
                record["checksum_status"] = "archive_unavailable"
                record["error"] = f"{type(exc).__name__}: {exc}"
                archives[(symbol, month)] = None
                manifest.append(record)
                continue
            try:
                record["checksum_retrieved_at_utc"] = _download(
                    f"{url}.CHECKSUM", checksum_path
                )
                data = path.read_bytes()
                expected = checksum_expected(
                    checksum_path.read_text(encoding="utf-8"), filename
                )
                actual = hashlib.sha256(data).hexdigest()
                record["expected_sha256"] = expected
                record["archive_sha256"] = actual
                if actual != expected:
                    raise ValueError(
                        f"SHA-256 mismatch: expected {expected}, got {actual}"
                    )
                rows, shortened_closes = parse_monthly_zip(data, filename, month)
                record["checksum_status"] = "verified"
                record["archive_rows"] = len(rows)
                record["shortened_close_count"] = len(shortened_closes)
                record["shortened_close_timestamps_utc"] = [
                    datetime.fromtimestamp(ts / 1000, UTC).isoformat()
                    for ts in sorted(shortened_closes)
                ]
                record["shortened_close_details"] = [
                    {
                        "open_utc": datetime.fromtimestamp(ts / 1000, UTC).isoformat(),
                        "recorded_close_utc": datetime.fromtimestamp(
                            close_ms / 1000, UTC
                        ).isoformat(),
                    }
                    for ts, close_ms in sorted(shortened_closes.items())
                ]
                archives[(symbol, month)] = rows
                shortened[(symbol, month)] = shortened_closes
            except Exception as exc:
                record["checksum_status"] = "verification_failed"
                record["error"] = f"{type(exc).__name__}: {exc}"
                archives[(symbol, month)] = None
            manifest.append(record)

    findings: list[dict] = []
    for symbol in SYMBOLS:
        for hour in GAP_HOURS:
            month = hour.strftime("%Y-%m")
            rows = archives[(symbol, month)]
            manifest_record = next(
                item
                for item in manifest
                if item["symbol"] == symbol and item["covered_period"] == month
            )
            timestamp_ms = int(hour.timestamp() * 1000)
            if rows is None:
                classification = manifest_record["checksum_status"]
            else:
                classification = (
                    "found_in_archive"
                    if timestamp_ms in rows
                    else "absent_from_archive"
                )
            neighbors = []
            for offset in (-1, 1):
                neighbor_ms = timestamp_ms + offset * HOUR_MS
                archive_values = rows.get(neighbor_ms) if rows is not None else None
                silver_values = silver[symbol].get(neighbor_ms)
                neighbors.append(
                    {
                        "timestamp_utc": datetime.fromtimestamp(
                            neighbor_ms / 1000, UTC
                        ).isoformat(),
                        "archive_present": archive_values is not None,
                        "archive_close_time_shortened": (
                            neighbor_ms in shortened[(symbol, month)]
                            if rows is not None
                            else None
                        ),
                        "silver_present": silver_values is not None,
                        "ohlcv_equal": archive_values == silver_values
                        if archive_values is not None and silver_values is not None
                        else None,
                    }
                )
            findings.append(
                {
                    "symbol": symbol,
                    "timestamp_utc": hour.isoformat(),
                    "classification": classification,
                    "silver_present": timestamp_ms in silver[symbol],
                    "archive_ohlcv": rows.get(timestamp_ms)
                    if rows is not None
                    else None,
                    "neighbors": neighbors,
                }
            )

    comparisons = []
    for symbol in SYMBOLS:
        for month in MONTHS:
            rows = archives[(symbol, month)]
            if rows is None:
                continue
            common = rows.keys() & silver[symbol].keys()
            mismatches = [
                timestamp
                for timestamp in common
                if rows[timestamp] != silver[symbol][timestamp]
            ]
            comparisons.append(
                {
                    "symbol": symbol,
                    "covered_period": month,
                    "archive_rows": len(rows),
                    "matching_silver_rows": len(common) - len(mismatches),
                    "ohlcv_mismatch_count": len(mismatches),
                    "ohlcv_mismatch_timestamps_utc": [
                        datetime.fromtimestamp(ts / 1000, UTC).isoformat()
                        for ts in sorted(mismatches)
                    ],
                    "archive_only_count": len(rows.keys() - silver[symbol].keys()),
                    "silver_only_count": sum(
                        1
                        for ts in silver[symbol]
                        if datetime.fromtimestamp(ts / 1000, UTC).strftime("%Y-%m")
                        == month
                        and ts not in rows
                    ),
                }
            )

    result = {
        "verification_completed_at_utc": datetime.now(UTC).isoformat(),
        "source_documentation": "https://github.com/binance/binance-public-data/blob/master/README.md",
        "archives": manifest,
        "findings": findings,
        "monthly_comparisons": comparisons,
    }
    artifact = data_root / "verification" / "qnt-001b" / "verification.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    report = verify()
    print(
        json.dumps(
            {
                "archives": len(report["archives"]),
                "verified": sum(
                    item["checksum_status"] == "verified" for item in report["archives"]
                ),
                "findings": len(report["findings"]),
                "classifications": {
                    status: sum(
                        item["classification"] == status for item in report["findings"]
                    )
                    for status in sorted(
                        {item["classification"] for item in report["findings"]}
                    )
                },
            },
            indent=2,
        )
    )
