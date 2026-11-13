"""Local, non-authoritative human review annotations for source revisions.

These records never resolve a conflict or change the canonical candle cache.
Evidence is caller supplied; its hash verifies retained bytes, not its authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .pipeline import json_bytes

SCHEMA = "mt5-revision-review-v1"
REQUIRED = b"mt5-revision-review-v1\n"
MAX_EVIDENCE_BYTES = 4_000_000
HEX = re.compile(r"[0-9a-f]{64}\Z")
OUTCOMES = {"ACCEPTED_WITH_EVIDENCE", "REJECTED_WITH_EVIDENCE"}
ATTESTATION = "human_asserted_not_authenticated"
EFFECT = "ANNOTATION_ONLY_CONFLICT_REMAINS_UNRESOLVED"


class ReviewInputError(ValueError):
    """The requested annotation is invalid and has not been written."""


class ReviewIntegrityError(ValueError):
    """Stored annotations or evidence are incomplete or inconsistent."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= maximum
        and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    )


def _identity(record: dict) -> dict:
    return {
        name: record[name]
        for name in (
            "revision_id",
            "decision_status",
            "accepted_batch_id",
            "rejected_batch_id",
            "evidence_sha256",
            "evidence_reference",
            "rationale",
            "attestation",
            "effect",
        )
    }


def _validate_identity(identity: dict, revisions: dict) -> None:
    if (
        set(identity)
        != {
            "revision_id",
            "decision_status",
            "accepted_batch_id",
            "rejected_batch_id",
            "evidence_sha256",
            "evidence_reference",
            "rationale",
            "attestation",
            "effect",
        }
        or not isinstance(identity["revision_id"], str)
        or not HEX.fullmatch(identity["revision_id"])
        or identity["revision_id"] not in revisions
        or not isinstance(identity["decision_status"], str)
        or identity["decision_status"] not in OUTCOMES
        or not isinstance(identity["evidence_sha256"], str)
        or not HEX.fullmatch(identity["evidence_sha256"])
        or not _text(identity["evidence_reference"], 512)
        or not _text(identity["rationale"], 2000)
        or identity["attestation"] != ATTESTATION
        or identity["effect"] != EFFECT
    ):
        raise ReviewInputError("invalid review identity or evidence metadata")
    record = revisions[identity["revision_id"]]
    original = record["original"]["batch_id"]
    revised = record["revised"]["batch_id"]
    if original == revised:
        raise ReviewInputError("revision source identities must differ")
    expected = (
        (revised, original)
        if identity["decision_status"] == "ACCEPTED_WITH_EVIDENCE"
        else (original, revised)
    )
    if (identity["accepted_batch_id"], identity["rejected_batch_id"]) != expected:
        raise ReviewInputError("review source identities do not match its outcome")


def _evidence_path(state_dir: Path, digest: str, *, create: bool = False) -> Path:
    root = state_dir / "revision-evidence"
    if root.is_symlink():
        raise ReviewIntegrityError("review evidence directory cannot be a symlink")
    if create:
        root.mkdir(parents=False, exist_ok=True)
    if not root.is_dir() or root.resolve().parent != state_dir.resolve():
        raise ReviewIntegrityError(
            "review evidence directory is unavailable or outside state"
        )
    path = root / digest
    if path.is_symlink() or path.parent.resolve() != root.resolve():
        raise ReviewIntegrityError("review evidence path is invalid")
    return path


def _read_evidence(path: Path, digest: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReviewIntegrityError("review evidence missing or invalid")
    with path.open("rb") as file:
        data = file.read(MAX_EVIDENCE_BYTES + 1)
    if not data or len(data) > MAX_EVIDENCE_BYTES or _digest(data) != digest:
        raise ReviewIntegrityError("review evidence failed integrity validation")
    return data


def load_reviews(state_dir: Path, revisions: dict) -> dict:
    """Validate annotation ledger and retained evidence; absent legacy state is valid."""
    ledger = state_dir / "revision-reviews.json"
    marker = state_dir / "revision-reviews.required"
    pending = state_dir / "revision-reviews.pending"
    if any(path.is_symlink() for path in (ledger, marker, pending)):
        raise ReviewIntegrityError("review ledger paths cannot be symlinks")
    if pending.exists():
        raise ReviewIntegrityError("review ledger has an incomplete transaction")
    if not ledger.exists() and not marker.exists():
        return {}
    try:
        if not ledger.is_file() or marker.read_bytes() != REQUIRED:
            raise ReviewIntegrityError("review ledger marker invalid")
        envelope = json.loads(ledger.read_bytes())
        body = envelope["reviews"]
        if (
            set(envelope) != {"reviews", "sha256"}
            or envelope["sha256"] != _digest(json_bytes(body))
            or set(body) != {"version", "records"}
            or body["version"] != SCHEMA
            or not isinstance(body["records"], dict)
        ):
            raise ReviewIntegrityError("review ledger malformed")
        for review_id, record in body["records"].items():
            if set(record) != set(_identity(record)) | {"review_id", "recorded_at_utc"}:
                raise ReviewIntegrityError("review record fields invalid")
            identity = _identity(record)
            _validate_identity(identity, revisions)
            timestamp = datetime.fromisoformat(record["recorded_at_utc"])
            if timestamp.utcoffset() != timedelta(0):
                raise ReviewIntegrityError("review timestamp is not UTC")
            if review_id != record["review_id"] or review_id != _digest(
                json_bytes(identity)
            ):
                raise ReviewIntegrityError("review identity mismatch")
            _read_evidence(
                _evidence_path(state_dir, identity["evidence_sha256"]),
                identity["evidence_sha256"],
            )
        return body["records"]
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
    ) as exc:
        raise ReviewIntegrityError("review ledger failed integrity validation") from exc


def append_review(
    state_dir: Path,
    revisions: dict,
    reviews: dict,
    *,
    revision_id: str,
    decision_status: str,
    accepted_batch_id: str,
    rejected_batch_id: str,
    evidence_bytes: bytes,
    evidence_reference: str,
    rationale: str,
) -> tuple[str, dict]:
    """Append a human assertion with retained bytes; the conflict stays unresolved.

    ACCEPTED means the newly detected/revised source was accepted by the human;
    REJECTED means that source was rejected. Neither claim is authenticated.
    """
    if (
        not isinstance(evidence_bytes, bytes)
        or not 0 < len(evidence_bytes) <= MAX_EVIDENCE_BYTES
    ):
        raise ReviewInputError("evidence bytes are missing or exceed the limit")
    identity = {
        "revision_id": revision_id,
        "decision_status": decision_status,
        "accepted_batch_id": accepted_batch_id,
        "rejected_batch_id": rejected_batch_id,
        "evidence_sha256": _digest(evidence_bytes),
        "evidence_reference": evidence_reference,
        "rationale": rationale,
        "attestation": ATTESTATION,
        "effect": EFFECT,
    }
    _validate_identity(identity, revisions)
    persisted = load_reviews(state_dir, revisions)
    if persisted != reviews:
        raise ReviewIntegrityError("review ledger changed unexpectedly")
    review_id = _digest(json_bytes(identity))
    # Validate stored evidence even on idempotent replay.
    if review_id in reviews:
        evidence = _evidence_path(state_dir, identity["evidence_sha256"])
        _read_evidence(evidence, identity["evidence_sha256"])
        return review_id, reviews
    state_dir.mkdir(parents=True, exist_ok=True)
    pending = state_dir / "revision-reviews.pending"
    with pending.open("xb") as file:
        file.write(b"review annotation transaction in progress\n")
        file.flush()
        os.fsync(file.fileno())
    evidence = _evidence_path(state_dir, identity["evidence_sha256"], create=True)
    if evidence.exists():
        if _read_evidence(evidence, identity["evidence_sha256"]) != evidence_bytes:
            raise ReviewIntegrityError("existing review evidence conflicts")
    else:
        fd = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(evidence_bytes)
            file.flush()
            os.fsync(file.fileno())
    marker = state_dir / "revision-reviews.required"
    if not marker.exists():
        with marker.open("xb") as file:
            file.write(REQUIRED)
            file.flush()
            os.fsync(file.fileno())
    elif marker.read_bytes() != REQUIRED:
        raise ReviewIntegrityError("review ledger marker invalid")
    updated = dict(reviews)
    updated[review_id] = {
        **identity,
        "review_id": review_id,
        "recorded_at_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    body = {"version": SCHEMA, "records": updated}
    serialized = json_bytes({"reviews": body, "sha256": _digest(json_bytes(body))})
    fd, name = tempfile.mkstemp(
        prefix=".revision-reviews-", suffix=".tmp", dir=state_dir
    )
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, state_dir / "revision-reviews.json")
        pending.unlink()
    finally:
        Path(name).unlink(missing_ok=True)
    return review_id, updated
