"""Synthetic tests for the dormant, explicitly configured pre-cutover backup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import backup_runtime

SYNTHETIC_FILES = [
    "broker_spec_snapshot.csv",
    "broker_native_probe.csv",
    "evidence/example/spec.csv",
    "evidence/example/probe.csv",
    "evidence/example/receipt.json",
    "evidence/example/build-receipt.json",
]


def configure(monkeypatch, source: Path, handoff: Path, files=SYNTHETIC_FILES):
    monkeypatch.setenv("MT5_PRECUTOVER_PROJECT_ROOT", str(source))
    monkeypatch.setenv("MT5_PRECUTOVER_HANDOFF", str(handoff))
    monkeypatch.setenv("MT5_PRECUTOVER_RUNTIME_FILES", json.dumps(files))


def test_active_cutover_refuses_before_configuration_read(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_runtime, "DEV", tmp_path)
    receipt = tmp_path / "runtime/cutover-receipt.json"
    receipt.parent.mkdir()
    receipt.write_text("{}")
    monkeypatch.setattr(
        backup_runtime,
        "_configured_sources",
        lambda: (_ for _ in ()).throw(AssertionError("must not read configuration")),
    )
    with pytest.raises(SystemExit, match="cannot back up the active migrated runtime"):
        backup_runtime.main()
    assert not (tmp_path / "runtime-backups").exists()


def test_dangling_cutover_receipt_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_runtime, "DEV", tmp_path)
    receipt = tmp_path / "runtime/cutover-receipt.json"
    receipt.parent.mkdir()
    receipt.symlink_to(tmp_path / "missing-receipt")
    with pytest.raises(SystemExit, match="cannot back up the active migrated runtime"):
        backup_runtime.main()
    assert not (tmp_path / "runtime-backups").exists()


def test_missing_configuration_does_not_create_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_runtime, "DEV", tmp_path)
    for name in (
        "MT5_PRECUTOVER_PROJECT_ROOT",
        "MT5_PRECUTOVER_HANDOFF",
        "MT5_PRECUTOVER_RUNTIME_FILES",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="configuration is missing"):
        backup_runtime.main()
    assert not (tmp_path / "runtime-backups").exists()


def test_valid_configuration_is_explicit_and_preserves_file_order(
    tmp_path, monkeypatch
):
    source, handoff = tmp_path / "source", tmp_path / "handoff"
    configure(monkeypatch, source, handoff)
    assert backup_runtime._configured_sources() == (
        source,
        handoff,
        tuple(SYNTHETIC_FILES),
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "files",
    [
        [],
        ["broker_spec_snapshot.csv", "broker_native_probe.csv"],
        SYNTHETIC_FILES[:-1],
        [*SYNTHETIC_FILES, SYNTHETIC_FILES[0]],
        [*SYNTHETIC_FILES, "../outside.csv"],
        [*SYNTHETIC_FILES, "/outside.csv"],
        [*SYNTHETIC_FILES, "evidence//bad.csv"],
        [*SYNTHETIC_FILES, "."],
        [*SYNTHETIC_FILES, "evidence/invalid\\path.csv"],
        [*SYNTHETIC_FILES, None],
    ],
)
def test_invalid_or_incomplete_evidence_lists_are_rejected(
    tmp_path, monkeypatch, files
):
    configure(monkeypatch, tmp_path / "source", tmp_path / "handoff", files)
    with pytest.raises(SystemExit, match="runtime file list"):
        backup_runtime._configured_sources()
    assert list(tmp_path.iterdir()) == []


def test_relative_sources_are_rejected(tmp_path, monkeypatch):
    configure(monkeypatch, Path("relative"), tmp_path / "handoff")
    with pytest.raises(SystemExit, match="absolute"):
        backup_runtime._configured_sources()


def test_malformed_json_is_rejected(tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path / "source", tmp_path / "handoff")
    monkeypatch.setenv("MT5_PRECUTOVER_RUNTIME_FILES", "[")
    with pytest.raises(SystemExit, match="runtime file list"):
        backup_runtime._configured_sources()


def test_explicit_synthetic_sources_capture_same_files_without_mutating_them(
    tmp_path, monkeypatch
):
    dev, source, handoff = (tmp_path / n for n in ("dev", "source", "handoff"))
    dev.mkdir()
    handoff.mkdir()
    state = source / "runtime/mt5_bridge/state"
    state.mkdir(parents=True)
    inputs = {}
    for name in ("checkpoint.json", "revision-ledger.json", "revision-ledger.required"):
        path = state / name
        path.write_bytes(("synthetic state " + name).encode())
        inputs[path] = path.read_bytes()
    for name in SYNTHETIC_FILES:
        path = source / "runtime" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic evidence " + name).encode())
        inputs[path] = path.read_bytes()
    configure(monkeypatch, source, handoff)
    monkeypatch.setattr(backup_runtime, "DEV", dev)
    monkeypatch.setattr(
        backup_runtime.BridgeService,
        "_read_state",
        lambda _: {"batches": {}, "markets": {}},
    )
    monkeypatch.setattr(
        backup_runtime.BridgeService, "_read_revision_ledger", lambda _: {}
    )
    monkeypatch.setattr(backup_runtime, "load_reviews", lambda *_: {})
    backup_runtime.main()
    backup = next((dev / "runtime-backups").iterdir())
    manifest = json.loads((backup / "backup-manifest.json").read_bytes())
    entries = {row["path"]: row for row in manifest["files"]}
    assert len(entries) == len(inputs)
    for path, expected in inputs.items():
        relative = (
            Path("state") / path.name
            if path.parent == state
            else Path("runtime") / path.relative_to(source / "runtime")
        )
        assert path.read_bytes() == expected
        assert (backup / relative).read_bytes() == expected
        assert entries[str(relative)]["sha256"] == hashlib.sha256(expected).hexdigest()
    assert manifest["captured_batch_identities"] == 0
