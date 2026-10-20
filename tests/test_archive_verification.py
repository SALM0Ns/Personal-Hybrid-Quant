"""Offline checks for Binance public-archive verification boundaries."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

import pytest

from quant.validation.archive_verification import (
    HOUR_MS,
    checksum_expected,
    parse_monthly_zip,
)


def _archive(close_offset: int) -> tuple[bytes, str, int]:
    filename = "BTCUSDT-1h-2021-02.zip"
    open_ms = int(datetime(2021, 2, 11, 3, tzinfo=UTC).timestamp() * 1000)
    row = f"{open_ms},10,12,9,11,2,{open_ms + close_offset},22,4,1,11,0\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename.removesuffix(".zip") + ".csv", row)
    return buffer.getvalue(), filename, open_ms


def test_checksum_names_exact_archive() -> None:
    filename = "BTCUSDT-1h-2021-02.zip"
    digest = "a" * 64
    assert checksum_expected(f"{digest}  {filename}\n", filename) == digest
    with pytest.raises(ValueError, match="filename"):
        checksum_expected(f"{digest}  ETHUSDT-1h-2021-02.zip\n", filename)


def test_shortened_close_is_retained_and_flagged() -> None:
    payload, filename, open_ms = _archive(42_000)
    rows, shortened = parse_monthly_zip(payload, filename, "2021-02")
    assert rows[open_ms] == (10.0, 12.0, 9.0, 11.0, 2.0)
    assert shortened == {open_ms: open_ms + 42_000}


def test_full_close_passes_and_out_of_hour_close_fails() -> None:
    payload, filename, open_ms = _archive(HOUR_MS - 1)
    rows, shortened = parse_monthly_zip(payload, filename, "2021-02")
    assert list(rows) == [open_ms]
    assert shortened == {}
    invalid, _, _ = _archive(HOUR_MS)
    with pytest.raises(ValueError, match="invalid hourly open or close time"):
        parse_monthly_zip(invalid, filename, "2021-02")
