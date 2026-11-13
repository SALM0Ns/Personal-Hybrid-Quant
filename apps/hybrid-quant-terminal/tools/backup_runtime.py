"""Create a no-overwrite pre-cutover snapshot of required runtime evidence."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from mt5_market_data.mt5_bridge import (
    MANIFEST_FIELDS,
    BridgeService,
    _batch_digest,
    _fields,
)
from mt5_market_data.revision_review import load_reviews

DEV = Path(__file__).resolve().parents[1]


def _configured_sources() -> tuple[Path, Path, tuple[str, ...]]:
    """Require explicit local pre-cutover inputs; never infer another authority."""
    source = os.environ.get("MT5_PRECUTOVER_PROJECT_ROOT", "")
    handoff = os.environ.get("MT5_PRECUTOVER_HANDOFF", "")
    raw_files = os.environ.get("MT5_PRECUTOVER_RUNTIME_FILES", "")
    if (
        not source.strip()
        or not handoff.strip()
        or not raw_files.strip()
        or "\x00" in source
        or "\x00" in handoff
    ):
        raise SystemExit("Pre-cutover backup configuration is missing")
    source_path = Path(source).expanduser()
    handoff_path = Path(handoff).expanduser()
    if not source_path.is_absolute() or not handoff_path.is_absolute():
        raise SystemExit("Pre-cutover source paths must be absolute")
    try:
        files = json.loads(raw_files)
    except (ValueError, TypeError) as exc:
        raise SystemExit("Pre-cutover runtime file list is invalid") from exc
    if not isinstance(files, list) or not files:
        raise SystemExit("Pre-cutover runtime file list is invalid")
    for item in files:
        if not isinstance(item, str) or not item or "\\" in item or "\x00" in item:
            raise SystemExit("Pre-cutover runtime file list is invalid")
        relative = PurePosixPath(item)
        if (
            not relative.parts
            or relative.is_absolute()
            or str(relative) != item
            or any(part in (".", "..") for part in relative.parts)
        ):
            raise SystemExit("Pre-cutover runtime file list is invalid")
    file_set = set(files)
    paths = [PurePosixPath(item) for item in files]
    evidence_dirs = {
        p.parent for p in paths if len(p.parts) >= 3 and p.parts[0] == "evidence"
    }
    complete_evidence = any(
        str(parent / "receipt.json") in file_set
        and str(parent / "build-receipt.json") in file_set
        and sum(p.parent == parent and p.suffix.lower() == ".csv" for p in paths) >= 2
        for parent in evidence_dirs
    )
    if (
        len(files) != len(file_set)
        or not {"broker_spec_snapshot.csv", "broker_native_probe.csv"}.issubset(
            file_set
        )
        or not complete_evidence
    ):
        raise SystemExit("Pre-cutover runtime file list is incomplete or duplicated")
    return source_path, handoff_path, tuple(files)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    receipt = DEV / "runtime/cutover-receipt.json"
    if receipt.exists() or receipt.is_symlink():
        raise SystemExit(
            "Pre-cutover backup tool cannot back up the active migrated runtime"
        )
    original, handoff, runtime_files = _configured_sources()
    state_dir = original / "runtime/mt5_bridge/state"
    if any(
        (state_dir / name).exists()
        for name in ("revision-ledger.pending", "revision-reviews.pending")
    ):
        raise SystemExit("Incomplete revision transaction; no backup created")
    bridge = BridgeService.__new__(BridgeService)
    bridge.state_dir = state_dir
    state = bridge._read_state()
    revisions = bridge._read_revision_ledger()
    reviews = load_reviews(state_dir, revisions)
    if reviews:
        raise SystemExit(
            "Review annotations require separately audited evidence copying"
        )
    expected_state = {}
    for name in ("checkpoint.json", "revision-ledger.json", "revision-ledger.required"):
        path = state_dir / name
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"Required state unavailable: {name}")
        expected_state[name] = digest(path.read_bytes())
    identities = set(state["batches"])
    for revision in revisions.values():
        for side in ("original", "revised"):
            identities.add(revision[side]["batch_id"])
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = DEV / "runtime-backups"
    root.mkdir(exist_ok=True)
    partial = root / f"precutover-{stamp}.partial"
    final = root / f"precutover-{stamp}"
    if final.exists() or partial.exists():
        raise SystemExit("Backup destination exists")
    partial.mkdir(mode=0o700)
    records = []

    def capture(source: Path, relative: Path, expected: str | None = None) -> bytes:
        if source.is_symlink() or not source.is_file():
            raise SystemExit(f"Required input unavailable: {source.name}")
        before = source.stat()
        data = source.read_bytes()
        after = source.stat()
        actual = digest(data)
        if (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ) or (expected and actual != expected):
            raise SystemExit(f"Input changed or failed hash validation: {source.name}")
        target = partial / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if digest(target.read_bytes()) != actual:
            raise SystemExit(f"Backup hash mismatch: {relative}")
        records.append(
            {
                "path": str(relative),
                "source": str(source),
                "sha256": actual,
                "bytes": len(data),
                "mtime_ns": before.st_mtime_ns,
                "mode": oct(before.st_mode & 0o777),
            }
        )
        return data

    for name, expected in expected_state.items():
        capture(state_dir / name, Path("state") / name, expected)
    for name in runtime_files:
        capture(original / "runtime" / name, Path("runtime") / name)
    for identity in sorted(identities):
        raw = capture(
            handoff / f"{identity}.manifest.csv",
            Path("handoff") / f"{identity}.manifest.csv",
            state["batches"].get(identity),
        )
        fields = _fields(raw, MANIFEST_FIELDS)
        if fields["batch_id"] != identity or _batch_digest(fields) != identity:
            raise SystemExit(f"Manifest identity invalid: {identity}")
        capture(
            handoff / f"{identity}.csv",
            Path("handoff") / f"{identity}.csv",
            fields["payload_sha256"],
        )
    for name, expected in expected_state.items():
        if digest((state_dir / name).read_bytes()) != expected:
            raise SystemExit("Runtime changed during backup; partial backup retained")
    metadata = {
        "schema": "mt5-runtime-backup-v1",
        "created_utc": datetime.now(UTC).isoformat(),
        "source_project": str(original),
        "source_handoff": str(handoff),
        "state_hashes": expected_state,
        "market_candle_counts": {
            key: len(value.get("candles", []))
            for key, value in state["markets"].items()
        },
        "unresolved_revisions": len(revisions),
        "review_annotations": len(reviews),
        "captured_batch_identities": len(identities),
        "files": records,
        "note": "Handoff remains active externally; only checkpoint/revision-referenced pairs are captured. Newer handoff files must be preserved for replay.",
    }
    data = (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode()
    with (partial / "backup-manifest.json").open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.rename(partial, final)
    print("backup", final)
    print(
        "files",
        len(records),
        "referenced batches",
        len(identities),
        "revisions",
        len(revisions),
    )
    print("checkpoint", expected_state["checkpoint.json"])
    print("ledger", expected_state["revision-ledger.json"])
    print("manifest_sha256", digest(data))


if __name__ == "__main__":
    main()
