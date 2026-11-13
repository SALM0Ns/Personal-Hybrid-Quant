from __future__ import annotations

import csv
import json
from pathlib import Path

import polars as pl
import pytest

from mt5_market_data.pipeline import SCHEMA, digest, ingest
from mt5_market_data.validation import COLUMNS, InputError, parse_metadata


@pytest.fixture
def project(tmp_path):
    # --basetemp is explicitly inside the approved project directory.
    return tmp_path


def make_export(root: Path, rows=None, *, first=None, last=None, **changes):
    if rows is None:
        rows = [
            ["2024.01.01 00:00:00", "1.0", "1.2", "0.9", "1.1", "10", "2", "0"],
            ["2024.01.01 01:00:00", "1.1", "1.3", "1.0", "1.2", "11", "2", "0"],
        ]
    meta = {
        "format_version": "mt5-export-v1",
        "broker_server": "Example-Demo",
        "symbol": "EURUSDm",
        "timeframe": "H1",
        "requested_start": "2024.01.01 00:00:00",
        "requested_end_exclusive": "2024.01.01 04:00:00",
        "actual_first": first if first is not None else (rows[0][0] if rows else ""),
        "actual_last": last if last is not None else (rows[-1][0] if rows else ""),
        "exported_at_server": "2024.01.02 00:00:00",
        "exported_at_local": "2024.01.02 07:00:00",
        "row_count": str(len(rows)),
        "copyrates_returned": str(len(rows)),
        "timestamp_semantics": "broker_server_clock_unverified",
    }
    meta.update(changes)
    root.mkdir(parents=True, exist_ok=True)
    data = root / "input.csv"
    metadata = root / "input.metadata.csv"
    with data.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    with metadata.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["field", "value"])
        writer.writerows(meta.items())
    return data, metadata


def test_valid_export_preserves_metadata_hashes_and_typed_parquet(project):
    data, meta = make_export(project)
    report = ingest(data, meta, root=project)
    assert report["status"] == "accepted"
    assert report["row_count"] == 2
    assert report["source_csv_sha256"] == digest(data.read_bytes())
    assert report["source_metadata_sha256"] == digest(meta.read_bytes())
    bronze = project / "data" / "bronze" / report["source_batch_sha256"]
    assert (bronze / "source.csv").read_bytes() == data.read_bytes()
    assert (bronze / "metadata.csv").read_bytes() == meta.read_bytes()
    base = project / "data/silver/symbol=EURUSDm/timeframe=H1"
    pointer = json.loads((base / "current.json").read_bytes())
    name, expected = next(iter(pointer["parquet_sha256"].items()))
    path = base / "snapshots" / pointer["snapshot_sha256"] / name
    assert digest(path.read_bytes()) == expected
    frame = pl.read_parquet(path)
    assert frame.schema == SCHEMA
    assert frame["timestamp"].dtype == pl.Datetime("us")
    assert frame["broker_server"].to_list() == ["Example-Demo"] * 2
    assert report["timestamp_semantics"] == "broker_server_clock_unverified"


def test_repeat_ingestion_is_idempotent(project):
    data, meta = make_export(project)
    first = ingest(data, meta, root=project)
    second = ingest(data, meta, root=project)
    assert first == second
    assert second["silver_row_count"] == 2
    assert len(list((project / "data/bronze").iterdir())) == 1


def test_overlap_deduplicates_without_losing_prior_rows(project):
    data, meta = make_export(project)
    ingest(data, meta, root=project)
    rows = [
        ["2024.01.01 01:00:00", "1.1", "1.3", "1.0", "1.2", "11", "2", "0"],
        ["2024.01.01 02:00:00", "1.2", "1.4", "1.1", "1.3", "12", "2", "0"],
    ]
    data, meta = make_export(project, rows)
    report = ingest(data, meta, root=project)
    assert report["status"] == "accepted"
    assert report["silver_row_count"] == 3


def test_conflicting_revision_is_rejected_and_pointer_unchanged(project):
    data, meta = make_export(project)
    ingest(data, meta, root=project)
    pointer = project / "data/silver/symbol=EURUSDm/timeframe=H1/current.json"
    before = pointer.read_bytes()
    data, meta = make_export(
        project, [["2024.01.01 00:00:00", "1", "1.4", "0.9", "1.3", "10", "2", "0"]]
    )
    report = ingest(data, meta, root=project)
    assert report["errors"] == ["conflicting_existing_observation"]
    assert pointer.read_bytes() == before


def test_empty_export_is_reported_not_published(project):
    data, meta = make_export(project, [])
    report = ingest(data, meta, root=project)
    assert report["status"] == "rejected"
    assert "empty_export" in report["errors"]
    assert report["actual_first"] is None
    assert (
        not list((project / "data/silver").rglob("*.parquet"))
        if (project / "data/silver").exists()
        else True
    )


def test_partial_history_reports_unverified_ranges(project):
    data, meta = make_export(
        project, [["2024.01.01 01:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"]]
    )
    report = ingest(data, meta, root=project)
    assert report["status"] == "accepted"
    assert len(report["unknown_coverage_periods"]) == 2
    assert not report["observed_timestamp_gaps"]


def test_observed_gap_is_not_classified_as_outage(project):
    data, meta = make_export(
        project,
        [
            ["2024.01.01 00:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"],
            ["2024.01.01 03:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"],
        ],
    )
    report = ingest(data, meta, root=project)
    gap = report["observed_timestamp_gaps"][0]
    assert report["unknown_coverage_periods"] == [
        {"start": "2024-01-01T01:00:00", "end_exclusive": "2024-01-01T03:00:00"}
    ]
    assert gap["nominal_missing_bars"] == 2
    assert gap["classification"] == "unverified_calendar_or_missing"


@pytest.mark.parametrize("kind", ["duplicate", "order", "ohlc", "incomplete"])
def test_invalid_rows_fail_closed_with_counts(project, kind):
    rows = [
        ["2024.01.01 00:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"],
        ["2024.01.01 01:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"],
    ]
    changes = {}
    if kind == "duplicate":
        rows[1][0] = rows[0][0]
    elif kind == "order":
        rows.reverse()
    elif kind == "ohlc":
        rows[0][2] = "0.5"
    else:
        changes["exported_at_server"] = "2024.01.01 01:30:00"
    data, meta = make_export(project, rows, **changes)
    report = ingest(data, meta, root=project)
    assert report["status"] == "rejected"
    assert {
        "duplicate": "duplicate_count",
        "order": "non_monotonic_count",
        "ohlc": "invalid_ohlc_count",
        "incomplete": "incomplete_at_export",
    }[kind] in report["errors"]
    assert not (project / "data/silver").exists()


def test_non_numeric_csv_rejected_without_silver(project):
    data, meta = make_export(
        project, [["2024.01.01 00:00:00", "nan?", "1", "1", "1", "1", "1", "0"]]
    )
    report = ingest(data, meta, root=project)
    assert report["status"] == "rejected"
    assert report["errors"] == ["malformed_csv"]
    assert "numeric" in report["failure_details"]
    assert report["invalid_ohlc_count"] is None
    assert not (project / "data/silver").exists()


def test_metadata_duplicate_and_wrong_identity_rejected(project):
    data, meta = make_export(project)
    raw = meta.read_bytes() + b"symbol,EURUSDm\r\n"
    with pytest.raises(InputError, match="duplicate"):
        parse_metadata(raw)
    data, meta = make_export(project, symbol="EURUSD")
    with pytest.raises(InputError, match="Unsupported"):
        ingest(data, meta, root=project)
    bronze_batches = list((project / "data/bronze").iterdir())
    assert len(bronze_batches) == 1
    assert (bronze_batches[0] / "source.csv").read_bytes() == data.read_bytes()
    assert (bronze_batches[0] / "metadata.csv").read_bytes() == meta.read_bytes()


def test_metadata_row_count_or_actual_range_mismatch_rejected(project):
    data, meta = make_export(project, row_count="3", copyrates_returned="3")
    report = ingest(data, meta, root=project)
    assert "row_count_mismatch" in report["errors"]


def test_source_from_another_server_does_not_mix(project):
    data, meta = make_export(project)
    ingest(data, meta, root=project)
    data, meta = make_export(project, broker_server="Other-Demo")
    with pytest.raises(InputError, match="Broker server"):
        ingest(data, meta, root=project)


@pytest.mark.parametrize("symbol,timeframe", [("EURUSDm", "M15"), ("XAUUSDm", "H4")])
def test_supported_symbol_timeframes(project, symbol, timeframe):
    data, meta = make_export(
        project,
        [["2024.01.01 00:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"]],
        symbol=symbol,
        timeframe=timeframe,
    )
    assert ingest(data, meta, root=project)["status"] == "accepted"


def test_tampered_silver_fails_closed(project):
    data, meta = make_export(project)
    first = ingest(data, meta, root=project)
    base = project / "data/silver/symbol=EURUSDm/timeframe=H1"
    part = (
        base
        / "snapshots"
        / first["silver_snapshot_sha256"]
        / next(iter(first["parquet_sha256"]))
    )
    part.write_bytes(b"tampered")
    with pytest.raises(InputError, match="hash mismatch"):
        ingest(data, meta, root=project)


def test_future_candle_and_outside_requested_range_rejected(project):
    data, meta = make_export(
        project, [["2024.01.01 05:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"]]
    )
    report = ingest(data, meta, root=project)
    assert "outside_requested_range" in report["errors"]


def test_output_partitions_by_year(project):
    rows = [
        ["2024.12.31 23:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"],
        ["2025.01.01 00:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"],
    ]
    data, meta = make_export(
        project,
        rows,
        requested_start="2024.12.31 23:00:00",
        requested_end_exclusive="2025.01.01 01:00:00",
        exported_at_server="2025.01.01 02:00:00",
    )
    report = ingest(data, meta, root=project)
    assert report["status"] == "accepted"
    assert set(report["parquet_sha256"]) == {
        "year=2024/part.parquet",
        "year=2025/part.parquet",
    }


def test_mismatched_metadata_actual_range_rejected(project):
    data, meta = make_export(project, first="2023.01.01 00:00:00")
    report = ingest(data, meta, root=project)
    assert "actual_first_mismatch" in report["errors"]
    assert not (project / "data/silver").exists()


def test_bad_csv_header_produces_failure_report(project):
    data, meta = make_export(project)
    data.write_text("timestamp,close\n2024.01.01 00:00:00,1\n")
    report = ingest(data, meta, root=project)
    assert report["status"] == "rejected"
    assert report["row_count"] is None
    assert report["unknown_coverage_periods"]
    assert len(list((project / "data/reports").rglob("*.json"))) == 1


def test_misaligned_timestamp_is_rejected_without_guessing_timezone(project):
    data, meta = make_export(
        project, [["2024.01.01 00:01:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"]]
    )
    report = ingest(data, meta, root=project)
    assert report["misaligned_timestamp_count"] == 1
    assert "misaligned_timestamp_count" in report["errors"]
    assert not (project / "data/silver").exists()


def test_h4_does_not_assume_unverified_four_hour_anchor(project):
    data, meta = make_export(
        project,
        [["2024.01.01 01:00:00", "1", "1.2", "0.9", "1.1", "1", "1", "0"]],
        timeframe="H4",
    )
    assert ingest(data, meta, root=project)["status"] == "accepted"
