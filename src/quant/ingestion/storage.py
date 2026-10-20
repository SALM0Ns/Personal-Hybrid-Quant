"""Local Parquet snapshots; Bronze is the recovery source for Silver."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import polars as pl

BRONZE_SCHEMA = {
    "exchange": pl.String,
    "symbol": pl.String,
    "timeframe": pl.String,
    "source": pl.String,
    "observation_id": pl.String,
    "content_hash": pl.String,
    "observed_at": pl.Datetime("us", "UTC"),
    "raw_ohlcv": pl.String,
}
SILVER_SCHEMA = {
    "exchange": pl.String,
    "symbol": pl.String,
    "timeframe": pl.String,
    "timestamp": pl.Datetime("us", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "ingested_at": pl.Datetime("us", "UTC"),
}


def dataset_path(root: Path, layer: str, symbol: str) -> Path:
    safe_symbol = symbol.replace("/", "-")
    return root / layer / "binance" / "1h" / f"{safe_symbol}.parquet"


def read_rows(path: Path) -> list[dict]:
    return pl.read_parquet(path).to_dicts() if path.exists() else []


def atomic_parquet(path: Path, rows: list[dict], schema: dict) -> None:
    """Replace a complete single-file snapshot without exposing partial bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        pl.DataFrame(rows, schema=schema).write_parquet(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
