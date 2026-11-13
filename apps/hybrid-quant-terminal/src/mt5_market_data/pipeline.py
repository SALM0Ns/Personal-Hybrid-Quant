"""Content-addressed Bronze and immutable, partitioned Silver snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import polars as pl

from .validation import (
    PERIODS,
    InputError,
    coverage,
    parse_candles,
    parse_metadata,
    parse_time,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = {
    "broker_server": pl.String,
    "symbol": pl.String,
    "timeframe": pl.String,
    "timestamp": pl.Datetime("us"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "tick_volume": pl.Int64,
    "spread_points": pl.Int64,
    "real_volume": pl.Int64,
    "source_batch_sha256": pl.String,
}
VALUES = ("open", "high", "low", "close", "tick_volume", "spread_points", "real_volume")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def within(path: Path, root: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise InputError("All input and output paths must stay inside the project root")
    return path


def write_once(path: Path, data: bytes) -> None:
    path = within(path, PROJECT_ROOT)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise InputError(
                f"Existing immutable file conflicts: {path.name}"
            ) from None


def replace_json(path: Path, payload: bytes) -> None:
    path = within(path, PROJECT_ROOT)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pointer-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _read_snapshot(base: Path, server: str) -> list[dict]:
    current = base / "current.json"
    if not current.exists():
        return []
    try:
        pointer = json.loads(current.read_bytes())
        snapshot_id = pointer["snapshot_sha256"]
        if len(snapshot_id) != 64 or any(
            c not in "0123456789abcdef" for c in snapshot_id
        ):
            raise InputError("Invalid current snapshot identity")
        if pointer["broker_server"] != server:
            raise InputError("Broker server differs from existing Silver snapshot")
        snapshot = base / "snapshots" / snapshot_id
        rows = []
        for relative, expected in sorted(pointer["parquet_sha256"].items()):
            path = within(snapshot / relative, snapshot)
            data = path.read_bytes()
            if digest(data) != expected:
                raise InputError("Existing Silver Parquet hash mismatch")
            import io

            frame = pl.read_parquet(io.BytesIO(data))
            if frame.schema != SCHEMA:
                raise InputError("Existing Silver schema mismatch")
            rows.extend(frame.to_dicts())
        if len({r["timestamp"] for r in rows}) != len(rows):
            raise InputError("Existing Silver contains duplicate timestamps")
        return rows
    except (OSError, KeyError, TypeError, ValueError, pl.exceptions.PolarsError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("Existing Silver snapshot is unreadable or invalid") from exc


def _write_snapshot(base: Path, rows: list[dict], server: str) -> dict:
    import io

    ordered = sorted(rows, key=lambda row: row["timestamp"])
    identity_rows = [
        {**r, "timestamp": r["timestamp"].isoformat(timespec="seconds")}
        for r in ordered
    ]
    snapshot_id = digest(json_bytes({"schema": "silver-v1", "rows": identity_rows}))
    destination = base / "snapshots" / snapshot_id
    payloads = {}
    for year in sorted({r["timestamp"].year for r in ordered}):
        frame = pl.DataFrame(
            [r for r in ordered if r["timestamp"].year == year], schema=SCHEMA
        )
        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        payloads[f"year={year}/part.parquet"] = buffer.getvalue()
    hashes = {name: digest(data) for name, data in payloads.items()}
    if destination.exists():
        actual = {
            str(p.relative_to(destination))
            for p in destination.rglob("*")
            if p.is_file()
        }
        if actual != set(payloads) or any(
            (destination / n).read_bytes() != b for n, b in payloads.items()
        ):
            raise InputError("Existing immutable Silver snapshot conflicts")
    else:
        (base / "snapshots").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=base / "snapshots", prefix=".staging-"
        ) as tmp:
            stage = Path(tmp)
            for name, body in payloads.items():
                write_once(stage / name, body)
            os.rename(stage, destination)
    pointer = {
        "snapshot_sha256": snapshot_id,
        "broker_server": server,
        "row_count": len(ordered),
        "parquet_sha256": hashes,
    }
    replace_json(base / "current.json", json_bytes(pointer))
    return pointer


def ingest(csv_path: Path, metadata_path: Path, *, root: Path = PROJECT_ROOT) -> dict:
    root = within(root, PROJECT_ROOT)
    csv_path = within(csv_path, root)
    metadata_path = within(metadata_path, root)
    csv_bytes, metadata_bytes = csv_path.read_bytes(), metadata_path.read_bytes()
    csv_sha, meta_sha = digest(csv_bytes), digest(metadata_bytes)
    batch_id = digest(json_bytes({"csv_sha256": csv_sha, "metadata_sha256": meta_sha}))
    bronze = within(root / "data" / "bronze" / batch_id, root)
    write_once(bronze / "source.csv", csv_bytes)
    write_once(bronze / "metadata.csv", metadata_bytes)
    write_once(
        bronze / "hashes.json",
        json_bytes({"csv_sha256": csv_sha, "metadata_sha256": meta_sha}),
    )
    metadata = parse_metadata(metadata_bytes)
    try:
        rows, counts = parse_candles(csv_bytes, metadata)
    except InputError as exc:
        # Parsing stopped: counts and endpoints are unknown, not zero.
        result = {
            "report_version": "quality-v1",
            "broker_server": metadata["broker_server"],
            "symbol": metadata["symbol"],
            "timeframe": metadata["timeframe"],
            "requested_start": metadata["requested_start"],
            "requested_end_exclusive": metadata["requested_end_exclusive"],
            "actual_first": None,
            "actual_last": None,
            "row_count": None,
            "duplicate_count": None,
            "invalid_ohlc_count": None,
            "misaligned_timestamp_count": None,
            "non_monotonic_count": None,
            "observed_timestamp_gaps": None,
            "unknown_coverage_periods": [
                {
                    "start": metadata["requested_start"],
                    "end_exclusive": metadata["requested_end_exclusive"],
                }
            ],
            "source_csv_sha256": csv_sha,
            "source_metadata_sha256": meta_sha,
            "source_batch_sha256": batch_id,
            "timestamp_semantics": metadata["timestamp_semantics"],
            "parquet_sha256": {},
            "status": "rejected",
            "errors": ["malformed_csv"],
            "failure_details": str(exc),
        }
        report = json_bytes(result)
        report_path = (
            root
            / "data"
            / "reports"
            / metadata["symbol"]
            / metadata["timeframe"]
            / f"{batch_id}-{digest(report)}.json"
        )
        write_once(report_path, report)
        return result
    result = {
        "report_version": "quality-v1",
        "broker_server": metadata["broker_server"],
        "symbol": metadata["symbol"],
        "timeframe": metadata["timeframe"],
        "requested_start": metadata["requested_start"],
        "requested_end_exclusive": metadata["requested_end_exclusive"],
        "timestamp_semantics": metadata["timestamp_semantics"],
        "exported_at_server": metadata["exported_at_server"],
        "exported_at_local": metadata["exported_at_local"],
        "source_csv_sha256": csv_sha,
        "source_metadata_sha256": meta_sha,
        "source_batch_sha256": batch_id,
        "row_count": len(rows),
        **counts,
        **coverage(rows, metadata),
        "parquet_sha256": {},
        "status": "rejected",
        "limitations": [
            "Broker timezone and historical publication times are unverified.",
            "Observed gaps are unclassified; market schedules are not verified.",
        ],
    }
    problems = []
    if len(rows) != int(metadata["row_count"]):
        problems.append("row_count_mismatch")
    if not rows:
        problems.append("empty_export")
    for key in counts:
        if counts[key]:
            problems.append(key)
    if rows:
        start, end = (
            parse_time(metadata["requested_start"]),
            parse_time(metadata["requested_end_exclusive"]),
        )
        export_time = parse_time(metadata["exported_at_server"])
        step = timedelta(seconds=PERIODS[metadata["timeframe"]])
        if any(not start <= row["timestamp"] < end for row in rows):
            problems.append("outside_requested_range")
        if any(row["timestamp"] + step > export_time for row in rows):
            problems.append("incomplete_at_export")
        for field, expected in (
            ("actual_first", rows[0]["timestamp"]),
            ("actual_last", rows[-1]["timestamp"]),
        ):
            if not metadata[field] or parse_time(metadata[field]) != expected:
                problems.append(field + "_mismatch")
    elif metadata["actual_first"] or metadata["actual_last"]:
        problems.append("empty_export_actual_range_mismatch")
    base = (
        root
        / "data"
        / "silver"
        / f"symbol={metadata['symbol']}"
        / f"timeframe={metadata['timeframe']}"
    )
    base = within(base, root)
    if not problems:
        existing = _read_snapshot(base, metadata["broker_server"])
        combined = {r["timestamp"]: r for r in existing}
        for row in rows:
            prior = combined.get(row["timestamp"])
            if prior and any(prior[k] != row[k] for k in VALUES):
                problems.append("conflicting_existing_observation")
                break
            if prior is None:
                combined[row["timestamp"]] = {
                    "broker_server": metadata["broker_server"],
                    "symbol": metadata["symbol"],
                    "timeframe": metadata["timeframe"],
                    **row,
                    "source_batch_sha256": batch_id,
                }
        if not problems:
            pointer = _write_snapshot(
                base, list(combined.values()), metadata["broker_server"]
            )
            result.update(
                status="accepted",
                silver_row_count=pointer["row_count"],
                silver_snapshot_sha256=pointer["snapshot_sha256"],
                parquet_sha256=pointer["parquet_sha256"],
            )
    result["errors"] = problems
    report = json_bytes(result)
    report_path = (
        root
        / "data"
        / "reports"
        / metadata["symbol"]
        / metadata["timeframe"]
        / f"{batch_id}-{digest(report)}.json"
    )
    write_once(report_path, report)
    return result
