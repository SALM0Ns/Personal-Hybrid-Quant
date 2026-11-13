"""Synthetic file-handoff regression tests; no terminal or broker is contacted."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mt5_market_data.mt5_bridge import BridgeError, BridgeService


def csv_fields(values):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["field", "value"])
    writer.writerows(values.items())
    return buffer.getvalue().encode()


def publish(root: Path, rows=None, **overrides):
    root.mkdir(parents=True, exist_ok=True)
    if rows is None:
        rows = [
            "2024.01.01 09:00:00,1,2,0.5,1.5,3,1,0",
            "2024.01.01 10:00:00,1,2,0.5,1.5,3,1,0",
        ]
    payload = (
        "timestamp,open,high,low,close,tick_volume,spread_points,real_volume\n"
        + "\n".join(rows)
        + "\n"
    ).encode()
    sha = hashlib.sha256(payload).hexdigest()
    server = overrides.pop("broker_server", "Exness-Demo")
    symbol = overrides.pop("symbol", "EURUSDm")
    timeframe = overrides.pop("timeframe", "H1")
    identity = f"mt5-live-v1\n{server}\n{symbol}\n{timeframe}\n{sha}\n".encode()
    batch = hashlib.sha256(identity).hexdigest()
    fields = {
        "schema_version": "mt5-live-v1",
        "batch_id": batch,
        "payload_filename": f"{batch}.csv",
        "payload_sha256": sha,
        "broker_server": server,
        "account_mode": "demo",
        "source_id": "exness-mt5",
        "symbol": symbol,
        "timeframe": timeframe,
        "row_count": str(len(rows)),
        "exported_at_server": "2024.01.01 11:05:00",
        "series_synchronized": "1",
        "copy_start_shift": "1",
        "requested_bars": str(len(rows)),
        "copyrates_returned": str(len(rows)),
        "timestamp_semantics": "broker_server_clock_unverified",
    }
    fields.update(overrides)
    (root / f"{batch}.csv").write_bytes(payload)
    (root / f"{batch}.manifest.csv").write_bytes(csv_fields(fields))
    return batch, fields


def heartbeat(
    root,
    *,
    seq=1,
    tick="2024.01.01 11:01:00",
    connected="1",
    seen="1",
    age="1000",
    instance="1-2",
    sync="1",
    symbol="EURUSDm",
    timeframe="H1",
):
    fields = {
        "schema_version": "mt5-heartbeat-v1",
        "source_id": "exness-mt5",
        "broker_server": "Exness-Demo",
        "account_mode": "demo",
        "symbol": symbol,
        "timeframe": timeframe,
        "instance_id": instance,
        "sequence": str(seq),
        "terminal_connected": connected,
        "series_synchronized": sync,
        "target_tick_time": tick,
        "quote_seen_since_start": seen,
        "quote_age_ms": age,
        "server_quote_time": tick,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{symbol}_{timeframe}.heartbeat.csv").write_bytes(csv_fields(fields))


def contiguous_rows(count=50, end=datetime(2024, 1, 1, 10)):
    start = end - timedelta(hours=count - 1)
    return [
        f"{(start + timedelta(hours=i)).strftime('%Y.%m.%d %H:%M:%S')},1,2,0.5,1.5,3,1,0"
        for i in range(count)
    ]


def service(tmp_path):
    return BridgeService(tmp_path / "incoming", tmp_path / "state")


def test_valid_batch_replay_restart_and_source_identity(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1
    result = reader.get("EURUSDm", "H1")
    assert result["health"]["history_count"] == 2
    assert result["health"]["status"] == "UNVERIFIED"
    assert result["candles"][0]["timestamp"].tzinfo is None
    checkpoint = (tmp_path / "state/checkpoint.json").read_bytes()
    assert reader.poll()["processed"] == 0
    assert (tmp_path / "state/checkpoint.json").read_bytes() == checkpoint
    restarted = service(tmp_path)
    assert restarted.poll()["processed"] == 0
    assert restarted.get("EURUSDm", "H1")["candles"] == result["candles"]


def test_missing_manifest_and_partial_publication_do_not_ingest(tmp_path):
    incoming = tmp_path / "incoming"
    batch, _ = publish(incoming)
    (incoming / f"{batch}.manifest.csv").unlink()
    reader = service(tmp_path)
    result = reader.poll()
    assert result["processed"] == 0
    assert any("no completion manifest" in e["reason"] for e in result["errors"])
    assert reader.get("EURUSDm", "H1")["candles"] == []
    publish(incoming)
    (incoming / f"{batch}.csv").unlink()
    assert service(tmp_path).poll()["errors"]


@pytest.mark.parametrize(
    "override",
    [
        {"schema_version": "other"},
        {"payload_sha256": "a" * 64},
        {"batch_id": "b" * 64},
        {"payload_filename": "../../escape.csv"},
        {"row_count": "3"},
        {"copyrates_returned": "3", "requested_bars": "3"},
        {"copy_start_shift": "0"},
        {"series_synchronized": "0"},
    ],
)
def test_bad_manifest_rejected(tmp_path, override):
    publish(tmp_path / "incoming", **override)
    reader = service(tmp_path)
    assert reader.poll()["errors"]
    assert reader.get("EURUSDm", "H1")["candles"] == []


@pytest.mark.parametrize(
    "rows",
    [
        ["2024.01.01 09:00:00,1,0.5,0.4,1.5,3,1,0"],
        ["2024.01.01 09:00:00,1,2,0.5,1.5,3,1,0"] * 2,
        [
            "2024.01.01 10:00:00,1,2,0.5,1.5,3,1,0",
            "2024.01.01 09:00:00,1,2,0.5,1.5,3,1,0",
        ],
        ["2024.01.01 11:00:00,1,2,0.5,1.5,3,1,0"],
    ],
)
def test_invalid_ohlc_duplicates_order_and_incomplete_bar_rejected(tmp_path, rows):
    publish(tmp_path / "incoming", rows)
    reader = service(tmp_path)
    assert reader.poll()["errors"]
    assert not reader.get("EURUSDm", "H1")["candles"]


def test_payload_hash_mismatch_and_partial_manifest_fail(tmp_path):
    incoming = tmp_path / "incoming"
    batch, _ = publish(incoming)
    (incoming / f"{batch}.csv").write_bytes(b"tampered")
    reader = service(tmp_path)
    assert "hash" in reader.poll()["errors"][0]["reason"]
    (incoming / f"{batch}.manifest.csv").write_bytes(b"field,value\npartial")
    assert reader.poll()["errors"]


def test_conflicting_duplicate_fails_without_changing_checkpoint(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    checkpoint = (tmp_path / "state/checkpoint.json").read_bytes()
    publish(incoming, ["2024.01.01 10:00:00,1,3,0.5,1.5,3,1,0"])
    errors = reader.poll()["errors"]
    assert any("conflicting duplicate" in e["reason"] for e in errors)
    assert (tmp_path / "state/checkpoint.json").read_bytes() == checkpoint
    assert reader.get("EURUSDm", "H1")["candles"][-1]["high"] == 2


def test_late_candle_closes_unknown_gap_without_filling(tmp_path):
    incoming = tmp_path / "incoming"
    publish(
        incoming,
        [
            "2024.01.01 08:00:00,1,2,0.5,1.5,3,1,0",
            "2024.01.01 10:00:00,1,2,0.5,1.5,3,1,0",
        ],
    )
    reader = service(tmp_path)
    reader.poll()
    assert reader.get("EURUSDm", "H1")["health"]["unresolved_gap_count"] == 1
    publish(incoming, ["2024.01.01 09:00:00,1,2,0.5,1.5,3,1,0"])
    assert reader.poll()["processed"] == 1
    result = reader.get("EURUSDm", "H1")
    assert result["health"]["unresolved_gap_count"] == 0
    assert len(result["candles"]) == 3


def test_validated_candle_conflict_is_market_scoped_and_replay_safe(tmp_path):
    incoming = tmp_path / "incoming"
    original, _ = publish(incoming, contiguous_rows())
    publish(incoming, contiguous_rows(), symbol="XAUUSDm")
    heartbeat(incoming, seq=1)
    heartbeat(incoming, seq=1, symbol="XAUUSDm")
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 2
    checkpoint = (tmp_path / "state/checkpoint.json").read_bytes()

    revision, _ = publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00")
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00", symbol="XAUUSDm")
    result = reader.poll()
    assert result["processed"] == 0
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["market"] == "EURUSDm|H1"
    assert error["file"] == f"{revision}.manifest.csv"
    assert "2024-01-01T10:00:00" in error["reason"]
    assert original in error["reason"] and revision in error["reason"]
    eur = reader.get("EURUSDm", "H1")
    assert eur["health"]["status"] == "UNVERIFIED"
    assert any("revision unresolved" in reason for reason in eur["health"]["reasons"])
    assert eur["candles"][-1]["spread_points"] == 1
    assert reader.get("XAUUSDm", "H1")["health"]["status"] == "LIVE"
    assert (tmp_path / "state/checkpoint.json").read_bytes() == checkpoint
    assert (incoming / f"{original}.csv").exists()
    assert (incoming / f"{revision}.csv").exists()
    assert (incoming / f"{revision}.manifest.csv").exists()

    assert reader.poll()["errors"] == result["errors"]
    restarted = service(tmp_path)
    assert restarted.poll()["errors"] == result["errors"]
    assert (tmp_path / "state/checkpoint.json").read_bytes() == checkpoint
    assert restarted.get("EURUSDm", "H1")["candles"][-1]["spread_points"] == 1


def test_unattributable_malformed_manifest_still_blocks_all_markets(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming, contiguous_rows(), symbol="XAUUSDm")
    heartbeat(incoming, seq=1, symbol="XAUUSDm")
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1
    (incoming / "malformed.manifest.csv").write_bytes(b"field,value\ninvalid")
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00", symbol="XAUUSDm")
    result = reader.poll()
    assert len(result["errors"]) == 1
    assert "market" not in result["errors"][0]
    xau = reader.get("XAUUSDm", "H1")["health"]
    assert xau["status"] == "UNVERIFIED"
    assert any("handoff" in reason for reason in xau["reasons"])


def test_out_of_order_batches_preserve_latest_broker_export_time(tmp_path):
    incoming = tmp_path / "incoming"
    publish(
        incoming,
        ["2024.01.01 10:00:00,1,2,0.5,1.5,3,1,0"],
        exported_at_server="2024.01.01 11:05:00",
    )
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1
    publish(
        incoming,
        ["2024.01.01 08:00:00,1,2,0.5,1.5,3,1,0"],
        exported_at_server="2024.01.01 10:05:00",
    )
    assert reader.poll()["processed"] == 1
    key = "EURUSDm|H1"
    assert reader._state["markets"][key]["last_exported_at_server"] == (
        "2024.01.01 11:05:00"
    )
    assert service(tmp_path)._state["markets"][key]["last_exported_at_server"] == (
        "2024.01.01 11:05:00"
    )


def test_partial_recovery_stays_explicit_and_server_conflict_rejected(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming, requested_bars="3")
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1
    assert reader.get("EURUSDm", "H1")["health"]["recovery_incomplete"]
    publish(incoming, broker_server="Exness-Other")
    assert any("broker server differs" in x["reason"] for x in reader.poll()["errors"])


def test_interrupted_checkpoint_never_partially_applies_batch(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    real_replace = __import__("os").replace
    monkeypatch.setattr(
        "mt5_market_data.mt5_bridge.os.replace",
        lambda *_: (_ for _ in ()).throw(OSError("interrupted")),
    )
    assert reader.poll()["errors"]
    assert reader.get("EURUSDm", "H1")["candles"] == []
    monkeypatch.setattr("mt5_market_data.mt5_bridge.os.replace", real_replace)
    assert reader.poll()["processed"] == 1
    assert len(service(tmp_path).get("EURUSDm", "H1")["candles"]) == 2


def test_live_requires_new_heartbeat_and_target_tick_progression(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming, contiguous_rows())
    heartbeat(incoming, seq=1)
    reader = service(tmp_path)
    reader.poll()
    first = reader.get("EURUSDm", "H1")["health"]
    assert (
        first["status"] == "UNVERIFIED" and first["connection_status"] == "UNVERIFIED"
    )
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00")
    reader.poll()
    health = reader.get("EURUSDm", "H1")["health"]
    assert health["status"] == "LIVE" and health["target_quote_status"] == "ADVANCING"
    assert health["target_quote_age_seconds"] is not None
    assert service(tmp_path).get("EURUSDm", "H1")["health"]["status"] == "UNVERIFIED"


def test_offline_requires_advancing_heartbeat_and_stale_quote_never_means_market_closed(
    tmp_path, monkeypatch
):
    incoming = tmp_path / "incoming"
    publish(incoming, contiguous_rows())
    now = [100.0]
    monkeypatch.setattr("mt5_market_data.mt5_bridge.time.monotonic", lambda: now[0])
    heartbeat(incoming, seq=1, connected="0")
    reader = service(tmp_path)
    reader.poll()
    assert reader.get("EURUSDm", "H1")["health"]["status"] == "UNVERIFIED"
    heartbeat(incoming, seq=2, connected="0")
    reader.poll()
    assert reader.get("EURUSDm", "H1")["health"]["status"] == "OFFLINE"
    heartbeat(incoming, seq=3, tick="2024.01.01 11:02:00")
    reader.poll()
    assert reader.get("EURUSDm", "H1")["health"]["status"] == "LIVE"
    now[0] += 100
    heartbeat(incoming, seq=4, tick="2024.01.01 11:02:00", age="101000")
    reader.poll()
    assert reader.get("EURUSDm", "H1")["health"]["status"] == "STALE"


def test_corrupt_checkpoint_fails_closed(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    with (tmp_path / "state/checkpoint.json").open("ab") as handle:
        handle.write(b"corrupt")
    with pytest.raises(BridgeError, match="checkpoint"):
        service(tmp_path)


def test_processed_manifest_replay_does_not_reread_payload_and_conflicts_fail(
    tmp_path, monkeypatch
):
    incoming = tmp_path / "incoming"
    batch, fields = publish(incoming)
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1

    def fail_payload(*_):
        raise AssertionError("a previously processed payload must not be reread")

    monkeypatch.setattr("mt5_market_data.mt5_bridge._safe_file", fail_payload)
    assert reader.poll()["processed"] == 0
    fields["exported_at_server"] = "2024.01.01 11:06:00"
    (incoming / f"{batch}.manifest.csv").write_bytes(csv_fields(fields))
    assert any("conflicting manifest" in e["reason"] for e in reader.poll()["errors"])
    assert (
        reader.get("EURUSDm", "H1")["health"]["source_attestation"]
        == "terminal_attested_not_authenticated"
    )


def test_non_exness_or_non_demo_manifest_fails_closed(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming, broker_server="Other-Broker")
    reader = service(tmp_path)
    assert reader.poll()["errors"]
    assert not reader.get("EURUSDm", "H1")["candles"]
    second = tmp_path / "second"
    publish(second, account_mode="live")
    reader = BridgeService(second, tmp_path / "second-state")
    assert reader.poll()["errors"]
    assert not reader.get("EURUSDm", "H1")["candles"]


def test_old_gap_reported_but_current_contiguous_segment_can_be_live(tmp_path):
    incoming = tmp_path / "incoming"
    rows = ["2023.12.20 00:00:00,1,2,0.5,1.5,3,1,0", *contiguous_rows()]
    publish(incoming, rows)
    heartbeat(incoming, seq=1)
    reader = service(tmp_path)
    reader.poll()
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00")
    reader.poll()
    h = reader.get("EURUSDm", "H1")["health"]
    assert h["status"] == "LIVE" and h["current_segment_count"] == 50
    assert h["unresolved_gap_count"] == 1 and h["historical_coverage_verified"] is False
    assert any("unresolved" in reason for reason in h["reasons"])


def test_recent_gap_or_short_segment_prevents_live(tmp_path):
    incoming = tmp_path / "incoming"
    rows = contiguous_rows(49)
    rows.insert(0, "2023.12.20 00:00:00,1,2,0.5,1.5,3,1,0")
    publish(incoming, rows)
    heartbeat(incoming, seq=1)
    reader = service(tmp_path)
    reader.poll()
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00")
    reader.poll()
    h = reader.get("EURUSDm", "H1")["health"]
    assert h["status"] == "UNVERIFIED" and h["current_segment_count"] == 49
    assert h["unresolved_gap_count"] == 1


def test_unverified_account_heartbeat_cannot_supply_quote_or_live_status(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming, contiguous_rows())
    heartbeat(incoming, seq=1)
    reader = service(tmp_path)
    reader.poll()
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00")
    reader.poll()
    assert reader.get("EURUSDm", "H1")["health"]["status"] == "LIVE"
    hb = incoming / "EURUSDm_H1.heartbeat.csv"
    text = (
        hb.read_text()
        .replace("sequence,2", "sequence,3")
        .replace("account_mode,demo", "account_mode,unverified")
        .replace("series_synchronized,1", "series_synchronized,0")
        .replace("target_tick_time,2024.01.01 11:02:00", "target_tick_time,")
        .replace("quote_seen_since_start,1", "quote_seen_since_start,0")
        .replace("quote_age_ms,1000", "quote_age_ms,")
    )
    hb.write_text(text)
    reader.poll()
    h = reader.get("EURUSDm", "H1")["health"]
    assert h["status"] == "UNVERIFIED" and any("demo" in r for r in h["reasons"])


def test_oversized_payload_and_excessive_requested_history_fail_closed(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming, requested_bars="4097")
    reader = service(tmp_path)
    assert any("counts" in error["reason"] for error in reader.poll()["errors"])
    second = tmp_path / "other"
    batch, _ = publish(second)
    (second / f"{batch}.csv").write_bytes(b"x" * 4_000_001)
    reader = BridgeService(second, tmp_path / "state2")
    assert any("size limit" in error["reason"] for error in reader.poll()["errors"])


@pytest.mark.parametrize("symbol", ["EURUSDm", "XAUUSDm"])
@pytest.mark.parametrize("timeframe", ["M15", "H1", "H4"])
def test_all_six_market_timeframe_combinations_accept_valid_completed_bars(
    tmp_path, symbol, timeframe
):
    starts = {
        "M15": ("2024.01.01 09:00:00", "2024.01.01 09:15:00"),
        "H1": ("2024.01.01 09:00:00", "2024.01.01 10:00:00"),
        "H4": ("2024.01.01 00:00:00", "2024.01.01 04:00:00"),
    }
    rows = [f"{stamp},1,2,0.5,1.5,3,1,0" for stamp in starts[timeframe]]
    publish(tmp_path / "incoming", rows, symbol=symbol, timeframe=timeframe)
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1
    result = reader.get(symbol, timeframe)
    assert len(result["candles"]) == 2
    assert result["health"]["unresolved_gap_count"] == 0


def test_fresh_quotes_with_delayed_ingestion_are_stale(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    publish(incoming, contiguous_rows())
    heartbeat(incoming, seq=1)
    monkeypatch.setattr(
        "mt5_market_data.mt5_bridge._now_utc", lambda: "2020-01-01T00:00:00Z"
    )
    reader = service(tmp_path)
    reader.poll()
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00")
    reader.poll()
    h = reader.get("EURUSDm", "H1")["health"]
    assert h["status"] == "STALE" and any("ingestion" in r for r in h["reasons"])


def test_advancing_target_quote_far_beyond_latest_bar_is_stale(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming, contiguous_rows())
    heartbeat(incoming, seq=1, tick="2024.01.01 13:00:00")
    reader = service(tmp_path)
    reader.poll()
    heartbeat(incoming, seq=2, tick="2024.01.01 13:01:00")
    reader.poll()
    h = reader.get("EURUSDm", "H1")["health"]
    assert h["status"] == "STALE" and any("bar is stale" in r for r in h["reasons"])


def test_persistent_revision_ledger_preserves_evidence_and_survives_missing_source(
    tmp_path,
):
    incoming = tmp_path / "incoming"
    original, original_fields = publish(incoming, contiguous_rows())
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1
    checkpoint = (tmp_path / "state/checkpoint.json").read_bytes()
    original_manifest = (incoming / f"{original}.manifest.csv").read_bytes()
    revised, revised_fields = publish(
        incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"]
    )
    revised_manifest = (incoming / f"{revised}.manifest.csv").read_bytes()
    assert reader.poll()["errors"]
    ledger_path = tmp_path / "state/revision-ledger.json"
    ledger_bytes = ledger_path.read_bytes()
    record = next(iter(json.loads(ledger_bytes)["ledger"]["revisions"].values()))
    assert (record["symbol"], record["timeframe"], record["timestamp"]) == (
        "EURUSDm",
        "H1",
        "2024-01-01T10:00:00",
    )
    assert record["decision_status"] == "UNRESOLVED"
    assert record["original"]["values"]["spread_points"] == 1
    assert record["revised"]["values"]["spread_points"] == 9
    for side, batch, fields, raw in (
        ("original", original, original_fields, original_manifest),
        ("revised", revised, revised_fields, revised_manifest),
    ):
        assert record[side]["batch_id"] == batch
        assert record[side]["manifest_sha256"] == hashlib.sha256(raw).hexdigest()
        assert record[side]["payload_sha256"] == fields["payload_sha256"]
        assert record[side]["manifest_evidence"] == "verified"
    assert record["detected_at_utc"].endswith("Z")
    assert (tmp_path / "state/checkpoint.json").read_bytes() == checkpoint
    assert reader.poll()["errors"]
    assert ledger_path.read_bytes() == ledger_bytes
    # Synthetic evidence removal must not silently resolve an already recorded conflict.
    (incoming / f"{revised}.manifest.csv").unlink()
    (incoming / f"{revised}.csv").unlink()
    heartbeat(incoming, seq=1)
    restarted = service(tmp_path)
    restarted.poll()
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00")
    restarted.poll()
    health = restarted.get("EURUSDm", "H1")["health"]
    assert health["status"] == "UNVERIFIED"
    assert health["unresolved_revision_count"] == 1
    assert any("persistent ledger" in reason for reason in health["reasons"])
    assert ledger_path.read_bytes() == ledger_bytes


def test_revision_records_unavailable_original_manifest_without_inventing_hash(
    tmp_path,
):
    incoming = tmp_path / "incoming"
    original, _ = publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    expected = hashlib.sha256(
        (incoming / f"{original}.manifest.csv").read_bytes()
    ).hexdigest()
    (incoming / f"{original}.manifest.csv").unlink()
    (incoming / f"{original}.csv").unlink()
    publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    assert reader.poll()["errors"]
    record = next(
        iter(
            json.loads((tmp_path / "state/revision-ledger.json").read_bytes())[
                "ledger"
            ]["revisions"].values()
        )
    )
    assert record["original"]["manifest_sha256"] == expected
    assert record["original"]["payload_sha256"] is None
    assert record["original"]["manifest_evidence"] == "unavailable"
    assert service(tmp_path).get("EURUSDm", "H1")["health"]["status"] == "UNVERIFIED"


def test_revision_ledger_corruption_and_forged_resolution_fail_closed(tmp_path):
    from mt5_market_data.pipeline import json_bytes

    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    reader.poll()
    path = tmp_path / "state/revision-ledger.json"
    envelope = json.loads(path.read_bytes())
    path.write_bytes(b'{"invalid": true}')
    with pytest.raises(
        BridgeError, match="revision ledger failed integrity validation"
    ):
        service(tmp_path)
    record = next(iter(envelope["ledger"]["revisions"].values()))
    record["decision_status"] = "ACCEPTED"
    envelope["sha256"] = hashlib.sha256(json_bytes(envelope["ledger"])).hexdigest()
    path.write_bytes(json_bytes(envelope))
    with pytest.raises(
        BridgeError, match="revision ledger failed integrity validation"
    ):
        service(tmp_path)


def test_revision_ledger_write_failure_blocks_globally(tmp_path, monkeypatch):
    import mt5_market_data.mt5_bridge as bridge_module

    incoming = tmp_path / "incoming"
    publish(incoming, contiguous_rows(), symbol="XAUUSDm")
    publish(incoming, contiguous_rows())
    heartbeat(incoming, seq=1, symbol="XAUUSDm")
    reader = service(tmp_path)
    reader.poll()
    revised, _ = publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    heartbeat(incoming, seq=2, tick="2024.01.01 11:02:00", symbol="XAUUSDm")
    original_replace = bridge_module.os.replace

    def reject_ledger(src, dst):
        if Path(dst).name == "revision-ledger.json":
            raise OSError("ledger unavailable")
        return original_replace(src, dst)

    monkeypatch.setattr(bridge_module.os, "replace", reject_ledger)
    result = reader.poll()
    assert any(
        e["reason"] == "ledger unavailable" and "market" not in e
        for e in result["errors"]
    )
    assert reader.get("XAUUSDm", "H1")["health"]["status"] == "UNVERIFIED"
    assert not (tmp_path / "state/revision-ledger.json").exists()
    assert (tmp_path / "state/revision-ledger.pending").exists()
    # Even if the synthetic conflicting source disappears, the running service
    # and a restarted service must not claim that the conflict was resolved.
    (incoming / f"{revised}.manifest.csv").unlink()
    (incoming / f"{revised}.csv").unlink()
    assert reader.poll()["errors"]
    assert reader.get("XAUUSDm", "H1")["health"]["status"] == "UNVERIFIED"
    with pytest.raises(BridgeError, match="incomplete persistence transaction"):
        service(tmp_path)


def test_deleted_revision_ledger_cannot_silently_clear_warning(tmp_path):
    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    reader.poll()
    path = tmp_path / "state/revision-ledger.json"
    assert path.exists()
    assert (tmp_path / "state/revision-ledger.required").exists()
    path.unlink()
    with pytest.raises(
        BridgeError, match="revision ledger failed integrity validation"
    ):
        service(tmp_path)


def test_semantically_invalid_ledger_is_rejected_even_with_recomputed_hash(tmp_path):
    from mt5_market_data.pipeline import json_bytes

    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    reader.poll()
    path = tmp_path / "state/revision-ledger.json"
    envelope = json.loads(path.read_bytes())
    record = next(iter(envelope["ledger"]["revisions"].values()))
    record["revised"]["values"]["open"] = -1
    envelope["sha256"] = hashlib.sha256(json_bytes(envelope["ledger"])).hexdigest()
    path.write_bytes(json_bytes(envelope))
    with pytest.raises(
        BridgeError, match="revision ledger failed integrity validation"
    ):
        service(tmp_path)


def test_invalid_cached_source_identity_leaves_durable_conflict_marker(tmp_path):
    from mt5_market_data.pipeline import json_bytes

    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    checkpoint_path = tmp_path / "state/checkpoint.json"
    envelope = json.loads(checkpoint_path.read_bytes())
    envelope["state"]["markets"]["EURUSDm|H1"]["candles"][-1]["source_batch_id"] = ""
    envelope["sha256"] = hashlib.sha256(json_bytes(envelope["state"])).hexdigest()
    checkpoint_path.write_bytes(json_bytes(envelope))
    reader = service(tmp_path)
    revised, _ = publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    assert any("source batch identity" in e["reason"] for e in reader.poll()["errors"])
    assert (tmp_path / "state/revision-ledger.pending").exists()
    (incoming / f"{revised}.manifest.csv").unlink()
    (incoming / f"{revised}.csv").unlink()
    assert reader.poll()["errors"]
    assert reader.get("EURUSDm", "H1")["health"]["status"] == "UNVERIFIED"
    with pytest.raises(BridgeError, match="incomplete persistence transaction"):
        service(tmp_path)


def test_missing_later_cached_field_still_sets_sticky_and_durable_fault(tmp_path):
    from mt5_market_data.pipeline import json_bytes

    incoming = tmp_path / "incoming"
    publish(incoming)
    reader = service(tmp_path)
    reader.poll()
    checkpoint = tmp_path / "state/checkpoint.json"
    envelope = json.loads(checkpoint.read_bytes())
    candle = envelope["state"]["markets"]["EURUSDm|H1"]["candles"][-1]
    del candle["real_volume"]
    envelope["sha256"] = hashlib.sha256(json_bytes(envelope["state"])).hexdigest()
    checkpoint.write_bytes(json_bytes(envelope))
    reader = service(tmp_path)
    revised, _ = publish(incoming, ["2024.01.01 10:00:00,1,3,0.5,1.5,3,9,0"])
    assert any(
        "malformed source evidence" in e["reason"] for e in reader.poll()["errors"]
    )
    assert (tmp_path / "state/revision-ledger.pending").exists()
    (incoming / f"{revised}.manifest.csv").unlink()
    (incoming / f"{revised}.csv").unlink()
    assert reader.poll()["errors"]
    assert reader.get("EURUSDm", "H1")["health"]["status"] == "UNVERIFIED"
    with pytest.raises(BridgeError, match="incomplete persistence transaction"):
        service(tmp_path)


def _review_case(tmp_path):
    incoming = tmp_path / "incoming"
    original, _ = publish(incoming, contiguous_rows())
    reader = service(tmp_path)
    assert reader.poll()["processed"] == 1
    revised, _ = publish(incoming, ["2024.01.01 10:00:00,1,2,0.5,1.5,3,9,0"])
    assert reader.poll()["errors"]
    ledger_path = tmp_path / "state/revision-ledger.json"
    ledger_bytes = ledger_path.read_bytes()
    revision_id = next(iter(json.loads(ledger_bytes)["ledger"]["revisions"]))
    return reader, revision_id, original, revised, ledger_bytes


def test_legacy_revision_ledger_has_no_annotations_and_is_not_rewritten(tmp_path):
    reader, _, _, _, before = _review_case(tmp_path)
    assert reader.revision_review_annotations() == {}
    assert service(tmp_path).revision_review_annotations() == {}
    assert (tmp_path / "state/revision-ledger.json").read_bytes() == before
    assert not (tmp_path / "state/revision-reviews.json").exists()


@pytest.mark.parametrize("status", ["ACCEPTED_WITH_EVIDENCE", "REJECTED_WITH_EVIDENCE"])
def test_human_revision_annotation_preserves_bytes_and_never_unblocks(tmp_path, status):
    reader, revision, original, revised, before = _review_case(tmp_path)
    accepted, rejected = (
        (revised, original) if status.startswith("ACCEPTED") else (original, revised)
    )
    arguments = {
        "revision_id": revision,
        "decision_status": status,
        "accepted_batch_id": accepted,
        "rejected_batch_id": rejected,
        "evidence_bytes": b"synthetic evidence bytes",
        "evidence_reference": "synthetic owner review reference",
        "rationale": "Synthetic review only, no proof of broker authority.",
    }
    review_id = reader.record_revision_decision(**arguments)
    record = reader.revision_review_annotations()[review_id]
    assert record["decision_status"] == status
    assert record["accepted_batch_id"] == accepted
    assert record["rejected_batch_id"] == rejected
    assert record["attestation"] == "human_asserted_not_authenticated"
    assert record["effect"] == "ANNOTATION_ONLY_CONFLICT_REMAINS_UNRESOLVED"
    digest = hashlib.sha256(arguments["evidence_bytes"]).hexdigest()
    assert record["evidence_sha256"] == digest
    assert (tmp_path / "state/revision-evidence" / digest).read_bytes() == arguments[
        "evidence_bytes"
    ]
    sidecar = tmp_path / "state/revision-reviews.json"
    saved = sidecar.read_bytes()
    assert reader.record_revision_decision(**arguments) == review_id
    assert sidecar.read_bytes() == saved
    assert (tmp_path / "state/revision-ledger.json").read_bytes() == before
    restarted = service(tmp_path)
    assert (
        restarted.revision_review_annotations() == reader.revision_review_annotations()
    )
    assert restarted.get("EURUSDm", "H1")["health"]["status"] == "UNVERIFIED"
    assert restarted.get("EURUSDm", "H1")["health"]["unresolved_revision_count"] == 1


@pytest.mark.parametrize(
    "override",
    [
        {"evidence_bytes": b""},
        {"evidence_reference": "   "},
        {"rationale": ""},
        {"decision_status": "UNRESOLVED"},
        {"decision_status": "ACCEPTED"},
        {"revision_id": "f" * 64},
        {"accepted_batch_id": "f" * 64},
        {"rejected_batch_id": "f" * 64},
    ],
)
def test_revision_annotation_invalid_evidence_or_identity_is_rejected_without_writes(
    tmp_path, override
):
    reader, revision, original, revised, before = _review_case(tmp_path)
    arguments = {
        "revision_id": revision,
        "decision_status": "ACCEPTED_WITH_EVIDENCE",
        "accepted_batch_id": revised,
        "rejected_batch_id": original,
        "evidence_bytes": b"evidence",
        "evidence_reference": "reference",
        "rationale": "reason",
    }
    arguments.update(override)
    with pytest.raises(BridgeError):
        reader.record_revision_decision(**arguments)
    assert (tmp_path / "state/revision-ledger.json").read_bytes() == before
    assert not (tmp_path / "state/revision-reviews.json").exists()
    assert not (tmp_path / "state/revision-reviews.pending").exists()


def test_annotation_evidence_tampering_blocks_running_and_restarted_service(tmp_path):
    reader, revision, original, revised, _ = _review_case(tmp_path)
    reader.record_revision_decision(
        revision_id=revision,
        decision_status="ACCEPTED_WITH_EVIDENCE",
        accepted_batch_id=revised,
        rejected_batch_id=original,
        evidence_bytes=b"synthetic evidence",
        evidence_reference="reference",
        rationale="reason",
    )
    evidence = (
        tmp_path
        / "state/revision-evidence"
        / hashlib.sha256(b"synthetic evidence").hexdigest()
    )
    evidence.write_bytes(b"modified")
    assert reader.poll()["errors"]
    assert reader.get("XAUUSDm", "H1")["health"]["status"] == "UNVERIFIED"
    with pytest.raises(BridgeError, match="review ledger failed integrity"):
        service(tmp_path)


def test_deleting_revision_ledger_and_marker_during_process_is_detected(tmp_path):
    reader, _, _, _, _ = _review_case(tmp_path)
    (tmp_path / "state/revision-ledger.json").unlink()
    (tmp_path / "state/revision-ledger.required").unlink()
    assert reader.poll()["errors"]
    assert reader.get("XAUUSDm", "H1")["health"]["status"] == "UNVERIFIED"


def test_review_write_failure_stays_blocked_and_pending_survives_restart(
    tmp_path, monkeypatch
):
    import mt5_market_data.revision_review as review_module

    reader, revision, original, revised, _ = _review_case(tmp_path)
    real_replace = review_module.os.replace

    def reject_review(src, dst):
        if Path(dst).name == "revision-reviews.json":
            raise OSError("synthetic failed review write")
        return real_replace(src, dst)

    monkeypatch.setattr(review_module.os, "replace", reject_review)
    with pytest.raises(BridgeError, match="could not be persisted"):
        reader.record_revision_decision(
            revision_id=revision,
            decision_status="REJECTED_WITH_EVIDENCE",
            accepted_batch_id=original,
            rejected_batch_id=revised,
            evidence_bytes=b"synthetic evidence",
            evidence_reference="reference",
            rationale="reason",
        )
    assert reader.poll()["errors"]
    assert (tmp_path / "state/revision-reviews.pending").exists()
    with pytest.raises(BridgeError, match="review ledger failed integrity"):
        service(tmp_path)


def test_review_evidence_directory_symlink_fails_closed_without_escape(tmp_path):
    reader, revision, original, revised, _ = _review_case(tmp_path)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (tmp_path / "state/revision-evidence").symlink_to(outside, target_is_directory=True)
    with pytest.raises(BridgeError, match="could not be persisted"):
        reader.record_revision_decision(
            revision_id=revision,
            decision_status="ACCEPTED_WITH_EVIDENCE",
            accepted_batch_id=revised,
            rejected_batch_id=original,
            evidence_bytes=b"synthetic evidence",
            evidence_reference="synthetic reference",
            rationale="synthetic rationale",
        )
    assert list(outside.iterdir()) == []
    assert (tmp_path / "state/revision-reviews.pending").exists()
    assert reader.poll()["errors"]
    with pytest.raises(BridgeError, match="review ledger failed integrity"):
        service(tmp_path)


@pytest.mark.parametrize(
    "name",
    ["revision-reviews.json", "revision-reviews.required", "revision-reviews.pending"],
)
def test_dangling_review_ledger_symlinks_fail_closed(tmp_path, name):
    _review_case(tmp_path)
    (tmp_path / "state" / name).symlink_to(tmp_path / "missing-target")
    with pytest.raises(BridgeError, match="review ledger failed integrity"):
        service(tmp_path)


@pytest.mark.parametrize(
    "name",
    [
        "revision-ledger.json",
        "revision-ledger.required",
        "revision-ledger.pending",
        "checkpoint.json",
    ],
)
def test_legacy_state_symlinks_fail_closed(tmp_path, name):
    _review_case(tmp_path)
    path = tmp_path / "state" / name
    path.unlink(missing_ok=True)
    path.symlink_to(tmp_path / "missing-target")
    with pytest.raises(BridgeError, match="cannot be symlinks|cannot be a symlink"):
        service(tmp_path)


def test_review_tampering_fails_even_with_recomputed_envelope_hash(tmp_path):
    from mt5_market_data.pipeline import json_bytes

    reader, revision, original, revised, _ = _review_case(tmp_path)
    reader.record_revision_decision(
        revision_id=revision,
        decision_status="ACCEPTED_WITH_EVIDENCE",
        accepted_batch_id=revised,
        rejected_batch_id=original,
        evidence_bytes=b"synthetic evidence",
        evidence_reference="reference",
        rationale="synthetic reason",
    )
    path = tmp_path / "state/revision-reviews.json"
    envelope = json.loads(path.read_bytes())
    record = next(iter(envelope["reviews"]["records"].values()))
    record["attestation"] = "verified_broker_authority"
    envelope["sha256"] = hashlib.sha256(json_bytes(envelope["reviews"])).hexdigest()
    path.write_bytes(json_bytes(envelope))
    assert reader.poll()["errors"]
    with pytest.raises(BridgeError, match="review ledger failed integrity"):
        service(tmp_path)


def test_required_live_runtime_never_falls_back_to_empty(tmp_path, monkeypatch):
    from mt5_market_data import mt5_bridge

    monkeypatch.setenv("MT5_REQUIRE_EXISTING_RUNTIME", "1")
    monkeypatch.setattr(mt5_bridge, "PROJECT_ROOT", tmp_path)
    with pytest.raises(mt5_bridge.BridgeError, match="required live checkpoint"):
        mt5_bridge.BridgeService()
    assert not (tmp_path / "runtime").exists()
