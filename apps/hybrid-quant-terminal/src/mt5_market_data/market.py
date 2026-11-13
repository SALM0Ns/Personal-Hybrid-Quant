"""Read and cross-check immutable local Silver snapshots without changing them."""

from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

import polars as pl

from .pipeline import PROJECT_ROOT, SCHEMA, digest, json_bytes, within
from .validation import PERIODS

FIELDS = ("open", "high", "low", "close")


def load_snapshot(
    symbol: str,
    timeframe: str,
    *,
    root: Path = PROJECT_ROOT,
    permitted_root: Path = PROJECT_ROOT,
):
    if symbol not in {"EURUSDm", "XAUUSDm"} or timeframe not in PERIODS:
        raise ValueError("unsupported symbol or timeframe")
    # Historical read-only roots may be explicitly configured by the local
    # operator; all paths remain confined to that root and hash validation stays on.
    root = within(root, permitted_root)
    base = within(
        root / "data" / "silver" / f"symbol={symbol}" / f"timeframe={timeframe}", root
    )
    pointer = json.loads((base / "current.json").read_bytes())
    snapshot_id = pointer["snapshot_sha256"]
    if len(snapshot_id) != 64 or any(x not in "0123456789abcdef" for x in snapshot_id):
        raise ValueError("invalid Silver snapshot identity")
    snapshot = base / "snapshots" / snapshot_id
    rows = []
    for relative, expected_hash in sorted(pointer["parquet_sha256"].items()):
        path = within(snapshot / relative, snapshot)
        body = path.read_bytes()
        if digest(body) != expected_hash:
            raise ValueError("Silver Parquet hash mismatch")
        import io

        frame = pl.read_parquet(io.BytesIO(body))
        if frame.schema != SCHEMA:
            raise ValueError("unexpected Silver schema")
        rows.extend(frame.to_dicts())
    rows.sort(key=lambda x: x["timestamp"])
    if len(rows) != pointer["row_count"] or not rows:
        raise ValueError("Silver row count mismatch or empty snapshot")
    previous = None
    for row in rows:
        t = row["timestamp"]
        if t.tzinfo is not None or t.second or t.microsecond:
            raise ValueError("unexpected broker-clock timestamp")
        if previous is not None and t <= previous:
            raise ValueError("duplicate Silver timestamps")
        if (
            row["symbol"] != symbol
            or row["timeframe"] != timeframe
            or row["broker_server"] != pointer["broker_server"]
        ):
            raise ValueError("Silver market identity mismatch")
        o, h, low, close = (row[k] for k in FIELDS)
        if (
            not all(math.isfinite(x) and x > 0 for x in (o, h, low, close))
            or h < max(o, low, close)
            or low > min(o, h, close)
        ):
            raise ValueError("invalid Silver OHLC")
        previous = t
    serial = [
        {**r, "timestamp": r["timestamp"].isoformat(timespec="seconds")} for r in rows
    ]
    if digest(json_bytes({"schema": "silver-v1", "rows": serial})) != snapshot_id:
        raise ValueError("Silver snapshot logical hash mismatch")
    return rows, {
        "snapshot_sha256": snapshot_id,
        "parquet_sha256": pointer["parquet_sha256"],
    }


def check_alignment(m15: list[dict], higher: list[dict], timeframe: str):
    """Require each higher candle's constituent 15-minute candles and OHLC match."""
    if timeframe not in ("H1", "H4"):
        raise ValueError("higher timeframe must be H1 or H4")
    count = PERIODS[timeframe] // PERIODS["M15"]
    indexed = {r["timestamp"]: r for r in m15}
    checks = {}
    summary = {"matched": 0, "missing_m15": 0, "ohlc_mismatch": 0}
    for bar in higher:
        parts = [
            indexed.get(bar["timestamp"] + timedelta(minutes=15 * i))
            for i in range(count)
        ]
        if any(part is None for part in parts):
            status = "missing_m15"
        else:
            actual = (
                parts[0]["open"],
                max(x["high"] for x in parts),
                min(x["low"] for x in parts),
                parts[-1]["close"],
            )
            status = (
                "matched"
                if all(
                    math.isclose(bar[k], value, rel_tol=1e-9, abs_tol=1e-9)
                    for k, value in zip(FIELDS, actual)
                )
                else "ohlc_mismatch"
            )
        checks[bar["timestamp"]] = status
        summary[status] += 1
    return checks, summary


def load_market(symbol: str, *, root: Path = PROJECT_ROOT):
    datasets, identities = {}, {}
    for timeframe in ("M15", "H1", "H4"):
        datasets[timeframe], identities[timeframe] = load_snapshot(
            symbol, timeframe, root=root
        )
    h1, h1_summary = check_alignment(datasets["M15"], datasets["H1"], "H1")
    h4, h4_summary = check_alignment(datasets["M15"], datasets["H4"], "H4")
    return (
        datasets,
        {"H1": h1, "H4": h4},
        {"H1": h1_summary, "H4": h4_summary},
        identities,
    )
