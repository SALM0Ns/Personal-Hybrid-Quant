"""Local, read-only MT5 file-handoff consumer and isolated runtime checkpoint.

The producer directory is never modified. The state file is replaced as a single
transaction after the whole batch is validated. Broker times stay timezone-naive.
Only a running consumer that has observed advancing producer and target quote
sequences can consider a feed LIVE. There is no verified session calendar.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import math
import os
import re
import stat
import tempfile
import threading
import time
import weakref
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from .pipeline import PROJECT_ROOT, json_bytes
from .revision_review import (
    ReviewInputError,
    ReviewIntegrityError,
    append_review,
    load_reviews,
)
from .validation import COLUMNS, MARKETS, PERIODS, InputError, parse_candles, parse_time

SCHEMA = "mt5-live-v1"
HEARTBEAT_SCHEMA = "mt5-heartbeat-v1"
SOURCE_ID = "exness-mt5"
MANIFEST_FIELDS = {
    "schema_version",
    "batch_id",
    "payload_filename",
    "payload_sha256",
    "broker_server",
    "account_mode",
    "source_id",
    "symbol",
    "timeframe",
    "row_count",
    "exported_at_server",
    "series_synchronized",
    "copy_start_shift",
    "requested_bars",
    "copyrates_returned",
    "timestamp_semantics",
}
HEARTBEAT_FIELDS = {
    "schema_version",
    "source_id",
    "broker_server",
    "account_mode",
    "symbol",
    "timeframe",
    "instance_id",
    "sequence",
    "terminal_connected",
    "series_synchronized",
    "target_tick_time",
    "quote_seen_since_start",
    "quote_age_ms",
    "server_quote_time",
}
HEX = re.compile(r"[0-9a-f]{64}\Z")
SERVER = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
HEARTBEAT_MAX_SECONDS = 90
QUOTE_MAX_SECONDS = 90
MAX_PAYLOAD_BYTES = 4_000_000
MAX_MANIFEST_BYTES = 32_000


class BridgeError(ValueError):
    """The producer data or checkpoint is malformed or conflicts."""


class ConsumerOwnershipError(BridgeError):
    """A live consumer cannot establish exclusive process ownership."""


_ACTIVE_LEASES = weakref.WeakSet()


def _invalidate_leases_after_fork() -> None:
    # A child must never use the parent's inherited open-file-description lock.
    for lease in list(_ACTIVE_LEASES):
        lease._close_in_forked_child()
    _ACTIVE_LEASES.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_invalidate_leases_after_fork)


class _ConsumerLease:
    """Cooperative kernel-held exclusive ownership; metadata is not authority."""

    def __init__(self, path: Path, state_dir: Path, handoff_dir: Path | None):
        self._fd = None
        self._path = path
        self._pid = os.getpid()
        if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(
            PROJECT_ROOT.resolve()
        ):
            raise ConsumerOwnershipError("consumer lease directory is unsafe")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not hasattr(os, "O_NOFOLLOW"):
            raise ConsumerOwnershipError("safe consumer lock opening is unavailable")
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise ConsumerOwnershipError(
                "consumer lease cannot be opened safely"
            ) from exc
        self._fd = fd
        try:
            st = os.fstat(fd)
            if (
                not stat.S_ISREG(st.st_mode)
                or st.st_nlink != 1
                or st.st_uid != os.getuid()
            ):
                raise ConsumerOwnershipError(
                    "consumer lease is not a safely owned regular file"
                )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                raise ConsumerOwnershipError(
                    "another consumer already owns the authoritative runtime"
                ) from exc
            record = {
                "schema": "mt5-consumer-lease-v1",
                "pid": self._pid,
                "runtime_identity": hashlib.sha256(str(state_dir).encode()).hexdigest(),
                "handoff_identity": hashlib.sha256(
                    str(handoff_dir).encode()
                ).hexdigest()
                if handoff_dir
                else None,
                "acquired_at_utc": datetime.now(UTC).isoformat(),
                "note": "advisory process record; flock is authoritative, not this metadata",
            }
            data = json_bytes(record)
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            if os.write(fd, data) != len(data):
                raise ConsumerOwnershipError(
                    "consumer lease owner record was not fully written"
                )
            os.fsync(fd)
            _ACTIVE_LEASES.add(self)
        except BaseException:
            self.close()
            raise

    def assert_owner(self) -> None:
        if self._fd is None or self._pid != os.getpid():
            raise ConsumerOwnershipError(
                "consumer lease is closed or inherited after fork"
            )
        try:
            held = os.fstat(self._fd)
            current = os.stat(self._path, follow_symlinks=False)
            if (held.st_dev, held.st_ino) != (
                current.st_dev,
                current.st_ino,
            ) or held.st_nlink != 1:
                raise ConsumerOwnershipError("consumer lease file was replaced")
        except OSError as exc:
            raise ConsumerOwnershipError(
                "consumer lease descriptor is unavailable"
            ) from exc

    def _close_in_forked_child(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        _ACTIVE_LEASES.discard(self)

    def __del__(self):
        try:
            self.close()
        except OSError:
            pass


class CandleConflictError(BridgeError):
    """A fully validated batch conflicts with a known market candle."""

    def __init__(self, market: str, timestamp: str, existing: str, incoming: str):
        self.market = market
        super().__init__(
            f"conflicting duplicate candle at {timestamp}; "
            f"existing batch {existing}, incoming batch {incoming}; "
            "revision unresolved"
        )


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_limited(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise BridgeError("handoff file exceeds size limit")
    return data


def _fields(data: bytes, expected: set[str]) -> dict[str, str]:
    if len(data) > MAX_MANIFEST_BYTES:
        raise BridgeError("handoff metadata exceeds size limit")
    try:
        rows = list(
            csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise BridgeError("handoff metadata is not valid UTF-8 CSV") from exc
    if not rows or rows[0] != ["field", "value"]:
        raise BridgeError("handoff metadata header is invalid")
    result: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) != 2 or row[0] in result:
            raise BridgeError("handoff metadata field is malformed or duplicated")
        result[row[0]] = row[1]
    if set(result) != expected:
        raise BridgeError("handoff metadata has missing or unexpected fields")
    return result


def _uint(value: str, name: str, *, positive: bool = False) -> int:
    if not value.isascii() or not value.isdigit() or len(value) > 18:
        raise BridgeError(f"invalid {name}")
    result = int(value)
    if positive and not result:
        raise BridgeError(f"invalid {name}")
    return result


def _broker_time(value: str, *, optional: bool = False) -> datetime | None:
    if optional and not value:
        return None
    try:
        return parse_time(value)
    except InputError as exc:
        raise BridgeError("invalid broker-clock timestamp") from exc


def _key(symbol: str, timeframe: str) -> str:
    if symbol not in MARKETS or timeframe not in PERIODS:
        raise BridgeError("unsupported market identity")
    return f"{symbol}|{timeframe}"


def _validate_market(fields: dict[str, str]) -> str:
    key = _key(fields["symbol"], fields["timeframe"])
    if (
        fields["source_id"] != SOURCE_ID
        or not SERVER.fullmatch(fields["broker_server"])
        or not fields["broker_server"].lower().startswith("exness")
    ):
        raise BridgeError("invalid source or broker identity")
    return key


def _batch_digest(fields: dict[str, str]) -> str:
    identity = "\n".join(
        (
            SCHEMA,
            fields["broker_server"],
            fields["symbol"],
            fields["timeframe"],
            fields["payload_sha256"],
            "",
        )
    )
    return _hash(identity.encode("utf-8"))


def _safe_file(root: Path, filename: str) -> Path:
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise BridgeError("invalid handoff filename")
    path = root / filename
    if not path.resolve().is_relative_to(root.resolve()):
        raise BridgeError("handoff path escapes the incoming directory")
    return path


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _times(rows: list[dict], timeframe: str) -> list[dict]:
    step = timedelta(seconds=PERIODS[timeframe])
    result = []
    for left, right in pairwise(rows):
        a, b = (
            datetime.fromisoformat(left["timestamp"]),
            datetime.fromisoformat(right["timestamp"]),
        )
        delta = b - a
        if delta != step:
            result.append(
                {
                    "after": left["timestamp"],
                    "before": right["timestamp"],
                    "missing_intervals": max(0, int(delta // step) - 1),
                    "classification": "UNKNOWN_SESSION_OR_MISSING",
                }
            )
    return result


class BridgeService:
    """Single-consumer broker handoff reader; no MT5 or trading API access."""

    def __init__(
        self,
        handoff_dir: Path | None = None,
        state_dir: Path | None = None,
        *,
        enforce_consumer_lease: bool = False,
    ):
        setting = os.environ.get("MT5_BRIDGE_HANDOFF")
        self.handoff_dir = (
            Path(handoff_dir).expanduser()
            if handoff_dir is not None
            else (Path(setting).expanduser() if setting else None)
        )
        target = (
            Path(state_dir)
            if state_dir is not None
            else PROJECT_ROOT / "runtime/mt5_bridge/state"
        )
        self.state_dir = target.resolve()
        if not self.state_dir.is_relative_to(PROJECT_ROOT.resolve()):
            raise BridgeError("runtime checkpoint must remain inside the project")
        authoritative = (PROJECT_ROOT / "runtime/mt5_bridge/state").resolve()
        is_authoritative = self.state_dir == authoritative
        required = (
            "checkpoint.json",
            "revision-ledger.json",
            "revision-ledger.required",
        )
        if (
            is_authoritative
            or (
                state_dir is None
                and os.environ.get("MT5_REQUIRE_EXISTING_RUNTIME") == "1"
            )
        ) and any(not (self.state_dir / name).is_file() for name in required):
            raise BridgeError("required live checkpoint or revision ledger is missing")

        # The existing local cutover receipt is the only registered live handoff.
        # Its paths bind one protected source to one state; they are not proof of
        # broker authentication. Do not silently fall back to a machine-specific
        # path or permit a different checkpoint to consume that handoff.
        receipt_path = PROJECT_ROOT / "runtime/cutover-receipt.json"
        registered_handoff = None
        try:
            if receipt_path.is_symlink():
                raise ValueError("symlinked cutover receipt")
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_bytes())
                handoff = receipt.get("handoff")
                if (
                    receipt.get("schema") != "mt5-runtime-cutover-v1"
                    or receipt.get("authoritative_state") != str(authoritative)
                    or not isinstance(handoff, str)
                    or not handoff
                    or not Path(handoff).is_absolute()
                ):
                    raise ValueError("runtime receipt mismatch")
                registered_handoff = Path(handoff).resolve()
            elif is_authoritative:
                raise ValueError("missing cutover receipt")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise ConsumerOwnershipError(
                "authoritative runtime receipt is missing or invalid"
            ) from exc

        if self.handoff_dir is not None:
            selected_handoff = self.handoff_dir.resolve()
            if is_authoritative and selected_handoff != registered_handoff:
                raise ConsumerOwnershipError(
                    "configured handoff does not match authoritative runtime receipt"
                )
            if not is_authoritative and selected_handoff == registered_handoff:
                raise ConsumerOwnershipError(
                    "live MT5 handoff is bound to the authoritative runtime"
                )
            if (
                not is_authoritative
                and registered_handoff is None
                and not selected_handoff.is_relative_to(
                    (PROJECT_ROOT / ".test-tmp").resolve()
                )
            ):
                raise ConsumerOwnershipError(
                    "runtime receipt is missing; unregistered handoff refused"
                )
        self._ownership_required = is_authoritative or enforce_consumer_lease
        self._closed = False
        self._lease = None
        if self._ownership_required:
            lock_path = (
                PROJECT_ROOT / ".local-dev/bridge-consumer.lock"
                if is_authoritative
                else self.state_dir.parent / f".{self.state_dir.name}.consumer.lock"
            )
            self._lease = _ConsumerLease(lock_path, self.state_dir, self.handoff_dir)
        try:
            self._lock = threading.RLock()
            self._state = self._read_state()
            self._revisions = self._read_revision_ledger()
            try:
                self._reviews = load_reviews(self.state_dir, self._revisions)
            except ReviewIntegrityError as exc:
                raise BridgeError(
                    "revision review ledger failed integrity validation"
                ) from exc
            self._revision_fault: str | None = None
            self._heartbeat: dict[str, dict] = {}
            self._errors: list[dict[str, str]] = []
        except BaseException:
            self.close()
            raise

    def _assert_write_authority(self) -> None:
        if self._closed:
            raise ConsumerOwnershipError("consumer has been closed")
        if self._ownership_required:
            if self._lease is None:
                raise ConsumerOwnershipError("consumer lease is unavailable")
            self._lease.assert_owner()

    def close(self) -> None:
        lock = getattr(self, "_lock", None)
        if lock is None:
            self._close_owned_lease()
        else:
            with lock:
                self._close_owned_lease()

    def _close_owned_lease(self) -> None:
        self._closed = True
        if self._lease is not None:
            self._lease.close()
            self._lease = None

    def _verify_persisted_revisions(self) -> None:
        """Detect external ledger or retained-evidence changes during this process."""
        if self._revision_fault:
            return
        try:
            if self._read_revision_ledger() != self._revisions:
                raise BridgeError("revision ledger changed unexpectedly")
            if load_reviews(self.state_dir, self._revisions) != self._reviews:
                raise BridgeError("revision review ledger changed unexpectedly")
        except (BridgeError, ReviewIntegrityError, OSError) as exc:
            self._revision_fault = f"Revision integrity check failed: {exc}"

    def record_revision_decision(
        self,
        *,
        revision_id: str,
        decision_status: str,
        accepted_batch_id: str,
        rejected_batch_id: str,
        evidence_bytes: bytes,
        evidence_reference: str,
        rationale: str,
    ) -> str:
        """Record a self-asserted, evidence-bound annotation; never unblock a feed.

        ACCEPTED and REJECTED both refer to the newly detected source. These
        are human assertions, not authenticated authority. The
        original revision remains UNRESOLVED and candle values never change.
        """
        self._assert_write_authority()
        with self._lock:
            self._assert_write_authority()
            self._verify_persisted_revisions()
            if self._revision_fault:
                raise BridgeError(self._revision_fault)
            try:
                review_id, self._reviews = append_review(
                    self.state_dir,
                    self._revisions,
                    self._reviews,
                    revision_id=revision_id,
                    decision_status=decision_status,
                    accepted_batch_id=accepted_batch_id,
                    rejected_batch_id=rejected_batch_id,
                    evidence_bytes=evidence_bytes,
                    evidence_reference=evidence_reference,
                    rationale=rationale,
                )
                return review_id
            except ReviewInputError as exc:
                raise BridgeError(str(exc)) from exc
            except (
                ReviewIntegrityError,
                OSError,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                self._revision_fault = (
                    "Revision review evidence could not be persisted or validated."
                )
                raise BridgeError(self._revision_fault) from exc

    def revision_review_annotations(self) -> dict:
        """Return a defensive copy of recorded annotations and verify their bytes."""
        with self._lock:
            self._verify_persisted_revisions()
            if self._revision_fault:
                raise BridgeError(self._revision_fault)
            return json.loads(json.dumps(self._reviews))

    def _read_state(self) -> dict:
        path = self.state_dir / "checkpoint.json"
        if path.is_symlink():
            raise BridgeError("runtime checkpoint cannot be a symlink")
        if not path.exists():
            return {"version": "mt5-bridge-state-v1", "markets": {}, "batches": {}}
        try:
            envelope = json.loads(path.read_bytes())
            body = envelope["state"]
            if (
                envelope["sha256"] != _hash(json_bytes(body))
                or body["version"] != "mt5-bridge-state-v1"
            ):
                raise ValueError
            if not isinstance(body["markets"], dict) or not isinstance(
                body["batches"], dict
            ):
                raise TypeError
            return body
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise BridgeError("runtime checkpoint failed integrity validation") from exc

    def _read_revision_ledger(self) -> dict:
        """Load unresolved conflict evidence; malformed persisted data fails closed."""
        path = self.state_dir / "revision-ledger.json"
        marker = self.state_dir / "revision-ledger.required"
        pending = self.state_dir / "revision-ledger.pending"
        if any(candidate.is_symlink() for candidate in (path, marker, pending)):
            raise BridgeError("revision ledger paths cannot be symlinks")
        if pending.exists():
            raise BridgeError(
                "revision ledger has an incomplete persistence transaction"
            )
        if not path.exists() and not marker.exists():
            return {}
        try:
            if not path.is_file() or marker.read_bytes() != b"mt5-revision-ledger-v1\n":
                raise ValueError
            envelope = json.loads(path.read_bytes())
            body = envelope["ledger"]
            if (
                set(envelope) != {"ledger", "sha256"}
                or envelope["sha256"] != _hash(json_bytes(body))
                or set(body) != {"version", "revisions"}
                or body["version"] != "mt5-revision-ledger-v1"
                or not isinstance(body["revisions"], dict)
            ):
                raise ValueError
            for revision_id, record in body["revisions"].items():
                if (
                    set(record)
                    != {
                        "revision_id",
                        "symbol",
                        "timeframe",
                        "timestamp",
                        "detected_at_utc",
                        "decision_status",
                        "decision_reason",
                        "ordering_note",
                        "original",
                        "revised",
                    }
                    or record["revision_id"] != revision_id
                    or not HEX.fullmatch(revision_id)
                    or record["decision_status"] != "UNRESOLVED"
                    or record["decision_reason"]
                    != "Conflicting source observations; authoritative version not established."
                    or record["ordering_note"]
                    != "Original is previously cached; revised is newly detected; neither is authoritative or necessarily earlier."
                ):
                    raise ValueError
                _key(record["symbol"], record["timeframe"])
                ts = datetime.fromisoformat(record["timestamp"])
                detected = datetime.fromisoformat(record["detected_at_utc"])
                if ts.tzinfo is not None or detected.utcoffset() != timedelta(0):
                    raise ValueError
                for version in (record["original"], record["revised"]):
                    if (
                        set(version)
                        != {
                            "batch_id",
                            "manifest_sha256",
                            "payload_sha256",
                            "manifest_evidence",
                            "values",
                        }
                        or not HEX.fullmatch(version["batch_id"])
                        or not HEX.fullmatch(version["manifest_sha256"])
                        or version["manifest_evidence"]
                        not in {"verified", "unavailable", "mismatch"}
                        or (
                            version["payload_sha256"] is not None
                            and not HEX.fullmatch(version["payload_sha256"])
                        )
                        or (version["manifest_evidence"] == "verified")
                        != (version["payload_sha256"] is not None)
                        or set(version["values"]) != set(COLUMNS)
                        or version["values"]["timestamp"] != record["timestamp"]
                    ):
                        raise ValueError
                for version in (record["original"], record["revised"]):
                    values = version["values"]
                    prices = [values[name] for name in ("open", "high", "low", "close")]
                    if any(
                        type(value) not in (int, float)
                        or not math.isfinite(value)
                        or value <= 0
                        for value in prices
                    ):
                        raise ValueError
                    o, h, low, c = prices
                    if h < max(o, low, c) or low > min(o, h, c):
                        raise ValueError
                    if any(
                        type(values[name]) is not int or values[name] < 0
                        for name in ("tick_volume", "spread_points", "real_volume")
                    ):
                        raise ValueError
                expected_id = _hash(
                    json_bytes(
                        {
                            "symbol": record["symbol"],
                            "timeframe": record["timeframe"],
                            "timestamp": record["timestamp"],
                            "original_batch_id": record["original"]["batch_id"],
                            "revised_batch_id": record["revised"]["batch_id"],
                        }
                    )
                )
                if (
                    expected_id != revision_id
                    or record["original"]["values"] == record["revised"]["values"]
                ):
                    raise ValueError
            return body["revisions"]
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OverflowError,
        ) as exc:
            raise BridgeError("revision ledger failed integrity validation") from exc

    def _original_manifest_evidence(
        self, batch: str, key: str
    ) -> tuple[str, str | None, str]:
        """Bind an accepted row to its recorded manifest; never invent missing evidence."""
        assert self.handoff_dir is not None
        digest = self._state["batches"].get(batch)
        if not isinstance(digest, str) or not HEX.fullmatch(digest):
            raise BridgeError("accepted candle lacks its recorded manifest identity")
        path = _safe_file(self.handoff_dir, f"{batch}.manifest.csv")
        try:
            raw = _read_limited(path, MAX_MANIFEST_BYTES)
        except OSError:
            return digest, None, "unavailable"
        if _hash(raw) != digest:
            return digest, None, "mismatch"
        try:
            fields = _fields(raw, MANIFEST_FIELDS)
            if (
                _validate_market(fields) != key
                or fields["batch_id"] != batch
                or not HEX.fullmatch(fields["payload_sha256"])
                or _batch_digest(fields) != batch
            ):
                return digest, None, "mismatch"
        except BridgeError:
            return digest, None, "mismatch"
        return digest, fields["payload_sha256"], "verified"

    def _record_revisions(
        self, key: str, fields: dict, manifest_hash: str, pairs: list[tuple[dict, dict]]
    ) -> None:
        """Atomically persist all detected conflicts before rejecting a batch."""
        self._assert_write_authority()
        new_revisions = dict(self._revisions)
        pending = self.state_dir / "revision-ledger.pending"
        symbol, timeframe = key.split("|", 1)

        def identity_for(original: dict, revised: dict) -> tuple[str, str, str]:
            stamp = revised["timestamp"]
            original_batch = original.get("source_batch_id")
            if not isinstance(original_batch, str) or not HEX.fullmatch(original_batch):
                raise BridgeError("accepted candle lacks its source batch identity")
            identity = {
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": stamp,
                "original_batch_id": original_batch,
                "revised_batch_id": fields["batch_id"],
            }
            return _hash(json_bytes(identity)), stamp, original_batch

        # Avoid disk writes for exact replays; failed prechecks are repeated
        # only after the durable pending marker has been created.
        try:
            if all(identity_for(a, b)[0] in new_revisions for a, b in pairs):
                return
        except (BridgeError, KeyError, TypeError, ValueError, AttributeError):
            pass
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with pending.open("xb") as handle:
            handle.write(b"unresolved revision persistence in progress\n")
            handle.flush()
            os.fsync(handle.fileno())
        for original, revised in pairs:
            revision_id, stamp, original_batch = identity_for(original, revised)
            if revision_id in new_revisions:
                continue
            orig_manifest, orig_payload, evidence = self._original_manifest_evidence(
                original_batch, key
            )
            new_revisions[revision_id] = {
                "revision_id": revision_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": stamp,
                "detected_at_utc": _now_utc(),
                "decision_status": "UNRESOLVED",
                "decision_reason": "Conflicting source observations; authoritative version not established.",
                "ordering_note": "Original is previously cached; revised is newly detected; neither is authoritative or necessarily earlier.",
                "original": {
                    "batch_id": original_batch,
                    "manifest_sha256": orig_manifest,
                    "payload_sha256": orig_payload,
                    "manifest_evidence": evidence,
                    "values": {column: original[column] for column in COLUMNS},
                },
                "revised": {
                    "batch_id": fields["batch_id"],
                    "manifest_sha256": manifest_hash,
                    "payload_sha256": fields["payload_sha256"],
                    "manifest_evidence": "verified",
                    "values": {column: revised[column] for column in COLUMNS},
                },
            }
        if new_revisions == self._revisions:
            return
        body = {"version": "mt5-revision-ledger-v1", "revisions": new_revisions}
        data = json_bytes({"ledger": body, "sha256": _hash(json_bytes(body))})
        self.state_dir.mkdir(parents=True, exist_ok=True)
        marker = self.state_dir / "revision-ledger.required"
        if not marker.exists():
            with marker.open("xb") as handle:
                handle.write(b"mt5-revision-ledger-v1\n")
                handle.flush()
                os.fsync(handle.fileno())
        elif marker.read_bytes() != b"mt5-revision-ledger-v1\n":
            raise BridgeError("revision ledger marker failed integrity validation")
        fd, name = tempfile.mkstemp(
            prefix=".revision-ledger-", suffix=".tmp", dir=self.state_dir
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.state_dir / "revision-ledger.json")
            pending.unlink()
        finally:
            Path(name).unlink(missing_ok=True)
        self._revisions = new_revisions

    def _save(self, new_state: dict) -> None:
        self._assert_write_authority()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        body = json_bytes({"state": new_state, "sha256": _hash(json_bytes(new_state))})
        fd, name = tempfile.mkstemp(
            prefix=".checkpoint-", suffix=".tmp", dir=self.state_dir
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.state_dir / "checkpoint.json")
        finally:
            Path(name).unlink(missing_ok=True)
        self._state = new_state

    def _consume(self, path: Path) -> bool:
        self._assert_write_authority()
        assert self.handoff_dir is not None
        incoming = self.handoff_dir
        raw_manifest = _read_limited(path, MAX_MANIFEST_BYTES)
        fields = _fields(raw_manifest, MANIFEST_FIELDS)
        key = _validate_market(fields)
        if (
            fields["schema_version"] != SCHEMA
            or fields["timestamp_semantics"] != "broker_server_clock_unverified"
        ):
            raise BridgeError("unsupported handoff schema or timestamp semantics")
        if fields["account_mode"] != "demo":
            raise BridgeError("batch is not attested as an Exness demo account")
        if fields["series_synchronized"] != "1" or fields["copy_start_shift"] != "1":
            raise BridgeError("batch does not attest synchronized completed bars")
        expected = fields["payload_sha256"]
        identity = fields["batch_id"]
        if (
            not HEX.fullmatch(expected)
            or not HEX.fullmatch(identity)
            or identity != _batch_digest(fields)
        ):
            raise BridgeError("batch identity or payload hash is invalid")
        if (
            path.name != f"{identity}.manifest.csv"
            or fields["payload_filename"] != f"{identity}.csv"
        ):
            raise BridgeError("batch filenames do not match the batch identity")
        manifest_hash = _hash(raw_manifest)
        prior = self._state["batches"].get(identity)
        if prior is not None:
            if prior != manifest_hash:
                raise BridgeError("existing batch identity has conflicting manifest")
            return False
        count = _uint(fields["row_count"], "row count", positive=True)
        requested = _uint(fields["requested_bars"], "requested bars", positive=True)
        returned = _uint(fields["copyrates_returned"], "CopyRates count", positive=True)
        if count != returned or returned > requested or requested > 4096:
            raise BridgeError("inconsistent CopyRates counts")
        export_time = _broker_time(fields["exported_at_server"])
        payload = _read_limited(
            _safe_file(incoming, fields["payload_filename"]), MAX_PAYLOAD_BYTES
        )
        if len(payload) > MAX_PAYLOAD_BYTES or _hash(payload) != expected:
            raise BridgeError("payload hash or size mismatch")
        try:
            parsed, counts = parse_candles(payload, {"timeframe": fields["timeframe"]})
        except InputError as exc:
            raise BridgeError("invalid candle CSV") from exc
        if len(parsed) != count or any(counts.values()):
            raise BridgeError("candle count, OHLC, timestamps, or ordering invalid")
        step = timedelta(seconds=PERIODS[fields["timeframe"]])
        if any(row["timestamp"] + step > export_time for row in parsed):
            raise BridgeError("candle is not closed by the producer's server cutoff")
        previous = self._state["markets"].get(key)
        if (
            previous is not None
            and previous["broker_server"] != fields["broker_server"]
        ):
            raise BridgeError("broker server differs from existing runtime cache")
        current = {row["timestamp"]: row for row in (previous or {}).get("candles", [])}
        conflicts: list[tuple[dict, dict]] = []
        for row in parsed:
            stamp = row["timestamp"].isoformat(timespec="seconds")
            item = {**row, "timestamp": stamp}
            if stamp in current:
                if any(current[stamp][column] != item[column] for column in COLUMNS):
                    conflicts.append((current[stamp], item))
            else:
                current[stamp] = {**item, "source_batch_id": identity}
        if conflicts:
            try:
                self._record_revisions(key, fields, manifest_hash, conflicts)
            except (BridgeError, OSError) as exc:
                self._revision_fault = (
                    f"Revision evidence could not be persisted: {exc}"
                )
                raise
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                self._revision_fault = "Revision evidence could not be persisted: malformed source evidence"
                raise BridgeError(self._revision_fault) from exc
            original, revised = conflicts[0]
            raise CandleConflictError(
                key, revised["timestamp"], original["source_batch_id"], identity
            )
        merged = [current[stamp] for stamp in sorted(current)]
        latest_export = fields["exported_at_server"]
        previous_export = (previous or {}).get("last_exported_at_server")
        if previous_export and _broker_time(previous_export) > export_time:
            # Content-hash filename order is not broker export-time order.
            latest_export = previous_export
        market = {
            "broker_server": fields["broker_server"],
            "symbol": fields["symbol"],
            "timeframe": fields["timeframe"],
            "source_id": SOURCE_ID,
            "timestamp_semantics": fields["timestamp_semantics"],
            "candles": merged,
            "last_ingestion_utc": _now_utc(),
            "last_exported_at_server": latest_export,
            "recovery_incomplete": bool(
                (previous or {}).get("recovery_incomplete") or returned < requested
            ),
            "gaps": _times(merged, fields["timeframe"]),
        }
        new_state = {
            **self._state,
            "markets": {**self._state["markets"], key: market},
            "batches": {**self._state["batches"], identity: manifest_hash},
        }
        self._save(new_state)
        return True

    def _observe_heartbeat(self, path: Path, key: str) -> None:
        first = _read_limited(path, MAX_MANIFEST_BYTES)
        if first != _read_limited(path, MAX_MANIFEST_BYTES):
            raise BridgeError("heartbeat changed while being read")
        fields = _fields(first, HEARTBEAT_FIELDS)
        if (
            _validate_market(fields) != key
            or fields["schema_version"] != HEARTBEAT_SCHEMA
        ):
            raise BridgeError("heartbeat identity or schema mismatch")
        if path.name != f"{fields['symbol']}_{fields['timeframe']}.heartbeat.csv":
            raise BridgeError("heartbeat filename does not match identity")
        for flag in (
            "terminal_connected",
            "series_synchronized",
            "quote_seen_since_start",
        ):
            if fields[flag] not in {"0", "1"}:
                raise BridgeError("invalid heartbeat flag")
        if fields["account_mode"] not in {"demo", "unverified"}:
            raise BridgeError("invalid heartbeat account mode")
        if fields["account_mode"] == "unverified" and (
            fields["series_synchronized"] != "0"
            or fields["target_tick_time"]
            or fields["quote_seen_since_start"] != "0"
            or fields["quote_age_ms"]
        ):
            raise BridgeError("unverified account heartbeat claims market data")
        if not TOKEN.fullmatch(fields["instance_id"]):
            raise BridgeError("invalid heartbeat instance")
        seq = _uint(fields["sequence"], "heartbeat sequence", positive=True)
        tick = _broker_time(fields["target_tick_time"], optional=True)
        _broker_time(fields["server_quote_time"], optional=True)
        if fields["quote_age_ms"]:
            _uint(fields["quote_age_ms"], "quote age")
        if fields["quote_seen_since_start"] == "1" and (
            tick is None or not fields["quote_age_ms"]
        ):
            raise BridgeError("inconsistent target quote evidence")
        prev = self._heartbeat.get(key)
        if prev and prev["instance"] == fields["instance_id"]:
            if seq < prev["sequence"]:
                raise BridgeError("heartbeat sequence went backwards")
            if seq == prev["sequence"]:
                if prev["raw"] != first:
                    raise BridgeError("heartbeat changed without sequence advancement")
                return
            progressed = bool(
                prev["tick"] is not None and tick is not None and tick > prev["tick"]
            )
            if prev["tick"] is not None and tick is not None and tick < prev["tick"]:
                raise BridgeError("target quote timestamp went backwards")
            prior_advance = prev["tick_advanced_at"]
        else:
            progressed = False
            prior_advance = None
        now = time.monotonic()
        self._heartbeat[key] = {
            "fields": fields,
            "raw": first,
            "sequence": seq,
            "instance": fields["instance_id"],
            "tick": tick,
            "received_at": now,
            "tick_advanced_at": now if progressed else prior_advance,
            "producer_progressed": bool(
                prev and prev["instance"] == fields["instance_id"]
            ),
        }

    def poll(self) -> dict:
        """Read published manifests and heartbeat files; never write to MT5."""
        self._assert_write_authority()
        with self._lock:
            self._assert_write_authority()
            errors: list[dict[str, str]] = []
            processed = 0
            self._verify_persisted_revisions()
            if self._revision_fault:
                self._errors = [
                    {"file": "revision-ledger", "reason": self._revision_fault}
                ]
                return {"processed": 0, "errors": self._errors}
            if self.handoff_dir is None or not self.handoff_dir.is_dir():
                self._errors = [
                    {"file": "incoming", "reason": "handoff directory unavailable"}
                ]
                return {"processed": 0, "errors": self._errors}
            for symbol in sorted(MARKETS):
                for timeframe in PERIODS:
                    key = _key(symbol, timeframe)
                    heartbeat = self.handoff_dir / f"{symbol}_{timeframe}.heartbeat.csv"
                    if not heartbeat.exists() and key in self._heartbeat:
                        errors.append(
                            {
                                "file": heartbeat.name,
                                "reason": "previously observed heartbeat is missing",
                            }
                        )
                    if heartbeat.exists():
                        try:
                            if not heartbeat.resolve().is_relative_to(
                                self.handoff_dir.resolve()
                            ):
                                raise BridgeError(
                                    "heartbeat path escapes incoming directory"
                                )
                            self._observe_heartbeat(heartbeat, key)
                        except (BridgeError, OSError) as exc:
                            errors.append({"file": heartbeat.name, "reason": str(exc)})
            for payload in sorted(self.handoff_dir.glob("*.csv")):
                if (
                    HEX.fullmatch(payload.stem)
                    and not (self.handoff_dir / f"{payload.stem}.manifest.csv").exists()
                ):
                    errors.append(
                        {
                            "file": payload.name,
                            "reason": "payload has no completion manifest",
                        }
                    )
            for path in sorted(self.handoff_dir.glob("*.manifest.csv")):
                try:
                    if not path.resolve().is_relative_to(self.handoff_dir.resolve()):
                        raise BridgeError("manifest path escapes incoming directory")
                    if self._consume(path):
                        processed += 1
                except CandleConflictError as exc:
                    errors.append(
                        {"file": path.name, "reason": str(exc), "market": exc.market}
                    )
                except (BridgeError, OSError) as exc:
                    errors.append({"file": path.name, "reason": str(exc)})
            self._errors = errors
            return {"processed": processed, "errors": errors}

    def get(self, symbol: str, timeframe: str) -> dict:
        """Return a cache snapshot and conservative process-observed feed health."""
        key = _key(symbol, timeframe)
        with self._lock:
            self._verify_persisted_revisions()
            market = self._state["markets"].get(key)
            observed = self._heartbeat.get(key)
            reasons: list[str] = []
            notices: list[str] = []
            heartbeat_age = None
            target_quote_age = None
            connection = "UNVERIFIED"
            quote = "UNVERIFIED"
            status = "UNVERIFIED"
            if self._revision_fault:
                reasons.append(self._revision_fault)
            if self.handoff_dir is None or not self.handoff_dir.is_dir():
                reasons.append(
                    "MT5 handoff directory is not configured or unavailable."
                )
            if observed:
                heartbeat_age = max(0, int(time.monotonic() - observed["received_at"]))
                fields = observed["fields"]
                if observed["producer_progressed"]:
                    connection = (
                        "CONNECTED"
                        if fields["terminal_connected"] == "1"
                        else "DISCONNECTED"
                    )
                else:
                    reasons.append(
                        "Exporter heartbeat progression has not been observed since startup."
                    )
                if heartbeat_age > HEARTBEAT_MAX_SECONDS:
                    status = "STALE"
                    reasons.append("Exporter heartbeat has not advanced recently.")
                elif connection == "DISCONNECTED":
                    status = "OFFLINE"
                    reasons.append("Exporter reports that MT5 is disconnected.")
                if fields["account_mode"] != "demo":
                    reasons.append("Terminal has not attested an Exness demo account.")
                if fields["series_synchronized"] != "1":
                    reasons.append("MT5 history synchronization is not verified.")
                advanced = observed["tick_advanced_at"]
                quote_age = (
                    int(fields["quote_age_ms"]) / 1000
                    if fields["quote_age_ms"]
                    else None
                )
                if quote_age is not None:
                    target_quote_age = quote_age + heartbeat_age
                if (
                    advanced is not None
                    and time.monotonic() - advanced <= QUOTE_MAX_SECONDS
                    and quote_age is not None
                    and quote_age + heartbeat_age <= QUOTE_MAX_SECONDS
                    and fields["quote_seen_since_start"] == "1"
                ):
                    quote = "ADVANCING"
                else:
                    if (
                        advanced is not None
                        and connection == "CONNECTED"
                        and fields["account_mode"] == "demo"
                        and fields["series_synchronized"] == "1"
                        and status != "OFFLINE"
                    ):
                        status = "STALE"
                        reasons.append(
                            "Previously advancing target-symbol quotes have stalled or become too old."
                        )
                    else:
                        reasons.append(
                            "Target-symbol quote advancement has not been verified recently."
                        )
                if market and fields["broker_server"] != market["broker_server"]:
                    reasons.append(
                        "Heartbeat broker identity differs from cached candles."
                    )
            else:
                reasons.append(
                    "No valid advancing exporter heartbeat has been observed."
                )
            relevant_errors = [
                error
                for error in self._errors
                if "market" not in error or error["market"] == key
            ]
            if relevant_errors:
                reasons.append(
                    "One or more handoff files are missing, incomplete, or rejected."
                )
                reasons.extend(
                    error["reason"] for error in relevant_errors if "market" in error
                )
            unresolved_revisions = [
                revision
                for revision in self._revisions.values()
                if _key(revision["symbol"], revision["timeframe"]) == key
            ]
            if unresolved_revisions:
                reasons.append(
                    f"{len(unresolved_revisions)} candle revision(s) remain unresolved in the persistent ledger."
                )
            rows = (market or {}).get("candles", [])
            gaps = (market or {}).get("gaps", [])
            if not rows:
                reasons.append("No validated completed candles are available.")
            step = timedelta(seconds=PERIODS[timeframe])
            segment_count = 1 if rows else 0
            for earlier, later in reversed(list(pairwise(rows))):
                if (
                    datetime.fromisoformat(later["timestamp"])
                    - datetime.fromisoformat(earlier["timestamp"])
                    != step
                ):
                    break
                segment_count += 1
            if rows and segment_count < 50:
                reasons.append(
                    "Insufficient current contiguous history: at least 50 completed candles are required."
                )
            if gaps:
                notices.append(
                    "Earlier unresolved timestamp gaps remain; no market calendar is verified."
                )
            if market and market["recovery_incomplete"]:
                notices.append(
                    "Bounded recovery returned fewer bars than requested; earlier coverage is unknown."
                )
            if market:
                try:
                    last_ingestion = datetime.fromisoformat(
                        market["last_ingestion_utc"]
                    )
                    ingestion_age = (datetime.now(UTC) - last_ingestion).total_seconds()
                    if not 0 <= ingestion_age <= PERIODS[timeframe] + QUOTE_MAX_SECONDS:
                        if (
                            ingestion_age > PERIODS[timeframe] + QUOTE_MAX_SECONDS
                            and status != "OFFLINE"
                        ):
                            status = "STALE"
                        reasons.append(
                            "Latest successful ingestion is not recent enough."
                        )
                except (TypeError, ValueError, KeyError):
                    reasons.append("Latest ingestion time cannot be validated.")
            if (
                observed
                and market
                and rows
                and connection == "CONNECTED"
                and quote == "ADVANCING"
            ):
                newest = datetime.fromisoformat(rows[-1]["timestamp"])
                current_tick = observed["tick"]
                if (
                    current_tick is not None
                    and current_tick
                    > newest + 2 * step + timedelta(seconds=QUOTE_MAX_SECONDS)
                ):
                    status = "STALE"
                    reasons.append(
                        "Latest completed bar is stale relative to the target quote in broker-clock time."
                    )
                elif current_tick is not None and current_tick < newest + step:
                    reasons.append(
                        "Latest bar closes after the last observed target quote; completeness is unverified."
                    )
            # A continuously advancing target quote establishes current observed
            # market activity, not a verified schedule or historical publication.
            if (
                observed
                and market
                and rows
                and not reasons
                and connection == "CONNECTED"
                and quote == "ADVANCING"
            ):
                latest = datetime.fromisoformat(rows[-1]["timestamp"])
                tick = observed["tick"]
                step = timedelta(seconds=PERIODS[timeframe])
                if tick is not None and timedelta(0) <= tick - (
                    latest + step
                ) <= step + timedelta(seconds=QUOTE_MAX_SECONDS):
                    status = "LIVE"
                else:
                    if tick is not None and tick > latest + 2 * step + timedelta(
                        seconds=QUOTE_MAX_SECONDS
                    ):
                        status = "STALE"
                    reasons.append(
                        "Latest completed bar is not current relative to the target quote in broker-clock time."
                    )
            if not reasons:
                reasons.append(
                    "Target quote and validated completed candles are advancing; session calendar is unverified."
                )
            reasons.extend(notices)
            snapshot = (
                _hash(json_bytes({"source": SOURCE_ID, "market": market}))
                if market
                else None
            )
            return {
                "candles": [
                    {**row, "timestamp": datetime.fromisoformat(row["timestamp"])}
                    for row in rows
                ],
                "snapshot_sha256": snapshot,
                "health": {
                    "status": status,
                    "reasons": reasons,
                    "latest_completed_candle": rows[-1]["timestamp"] if rows else None,
                    "last_ingestion_utc": (market or {}).get("last_ingestion_utc"),
                    "heartbeat_age_seconds": heartbeat_age,
                    "target_quote_status": quote,
                    "target_quote_age_seconds": target_quote_age,
                    "connection_status": connection,
                    "unresolved_revision_count": len(unresolved_revisions),
                    "unresolved_gap_count": len(gaps),
                    "gaps": gaps,
                    "history_count": len(rows),
                    "current_segment_count": segment_count,
                    "historical_coverage_verified": False,
                    "broker_server": (market or {}).get("broker_server"),
                    "recovery_incomplete": bool(
                        (market or {}).get("recovery_incomplete")
                    ),
                    "timestamp_semantics": "broker_server_clock_unverified",
                    "source_attestation": "terminal_attested_not_authenticated",
                },
            }
