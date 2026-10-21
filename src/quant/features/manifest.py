"""Validated, versioned anomaly evidence without modifying canonical OHLCV."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

HOUR = timedelta(hours=1)
ANOMALY_TYPES = frozenset({"missing_hour", "source_discrepancy", "shortened_close"})
SOURCE_FIELDS = frozenset({"open", "high", "low", "close", "volume", "unknown"})


def require_utc(value: datetime | None, name: str) -> None:
    if value is not None and (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")


def _parse_time(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    require_utc(parsed, name)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="microseconds") if value else None


def _sha256(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class Evidence:
    reference: str
    sha256: str
    observed_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("evidence reference must be nonempty")
        _sha256(self.sha256, "evidence sha256")
        require_utc(self.observed_at, "evidence observed_at")


@dataclass(frozen=True, slots=True)
class Anomaly:
    timestamp: datetime
    anomaly_type: str
    affected_fields: tuple[str, ...]
    source_evidence: tuple[Evidence, ...]
    severity: str
    review_status: str
    manifest_version: str
    recorded_source_close_at: datetime | None = None
    source_close_precision: str | None = None
    coverage_basis: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("anomaly timestamp is required")
        require_utc(self.timestamp, "anomaly timestamp")
        if self.timestamp.minute or self.timestamp.second or self.timestamp.microsecond:
            raise ValueError("anomaly timestamp must be hour-aligned")
        if self.anomaly_type not in ANOMALY_TYPES:
            raise ValueError("unknown anomaly type")
        if (
            not self.affected_fields
            or not all(isinstance(field, str) for field in self.affected_fields)
            or len(set(self.affected_fields)) != len(self.affected_fields)
        ):
            raise ValueError("affected_fields must be nonempty and unique")
        allowed = {"candle"} if self.anomaly_type == "missing_hour" else SOURCE_FIELDS
        if not set(self.affected_fields) <= allowed:
            raise ValueError("affected_fields do not match anomaly type")
        if (
            not self.source_evidence
            or not all(isinstance(item, Evidence) for item in self.source_evidence)
            or len({item.reference for item in self.source_evidence})
            != len(self.source_evidence)
        ):
            raise ValueError("source_evidence must be nonempty and unique")
        if any(
            item.observed_at is not None and item.observed_at < self.timestamp + HOUR
            for item in self.source_evidence
        ):
            raise ValueError("anomaly evidence predates candle closure")
        for name in ("severity", "review_status", "manifest_version"):
            if (
                not isinstance(getattr(self, name), str)
                or not getattr(self, name).strip()
            ):
                raise ValueError(f"{name} must be nonempty")
        require_utc(self.recorded_source_close_at, "recorded_source_close_at")
        if self.anomaly_type == "shortened_close":
            close = self.recorded_source_close_at
            if close is None or not self.timestamp <= close < self.timestamp + HOUR:
                raise ValueError("shortened close must lie inside its candle")
            if not self.source_close_precision:
                raise ValueError("shortened close requires source precision")
        elif self.recorded_source_close_at is not None:
            raise ValueError("recorded close only belongs to shortened-close records")
        if self.anomaly_type == "missing_hour" and not self.coverage_basis:
            raise ValueError("missing hour requires verified coverage basis")


@dataclass(frozen=True, slots=True)
class AnomalyManifest:
    manifest_version: str
    version_available_at: datetime | None
    records: tuple[Anomaly, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest_version, str)
            or not self.manifest_version.strip()
        ):
            raise ValueError("manifest_version must be nonempty")
        require_utc(self.version_available_at, "version_available_at")
        if not all(isinstance(item, Anomaly) for item in self.records):
            raise ValueError("records must contain validated anomalies")
        keys = [(item.timestamp, item.anomaly_type) for item in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate anomaly timestamp and type")
        if any(item.manifest_version != self.manifest_version for item in self.records):
            raise ValueError("record manifest version differs from parent")

    def ordered_records(self) -> tuple[Anomaly, ...]:
        return tuple(
            sorted(
                self.records,
                key=lambda item: (
                    item.timestamp,
                    item.anomaly_type,
                    min(evidence.reference for evidence in item.source_evidence),
                ),
            )
        )

    def to_dict(self) -> dict:
        return {
            "manifest_version": self.manifest_version,
            "version_available_at": _iso(self.version_available_at),
            "records": [
                {
                    "timestamp": _iso(item.timestamp),
                    "anomaly_type": item.anomaly_type,
                    "affected_fields": sorted(item.affected_fields),
                    "source_evidence": [
                        {
                            "reference": evidence.reference,
                            "sha256": evidence.sha256,
                            "observed_at": _iso(evidence.observed_at),
                        }
                        for evidence in sorted(
                            item.source_evidence, key=lambda value: value.reference
                        )
                    ],
                    "severity": item.severity,
                    "review_status": item.review_status,
                    "manifest_version": item.manifest_version,
                    "recorded_source_close_at": _iso(item.recorded_source_close_at),
                    "source_close_precision": item.source_close_precision,
                    "coverage_basis": item.coverage_basis,
                }
                for item in self.ordered_records()
            ],
        }

    def to_bytes(self) -> bytes:
        return (
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, payload: dict) -> AnomalyManifest:
        if not isinstance(payload, dict) or set(payload) != {
            "manifest_version",
            "version_available_at",
            "records",
        }:
            raise ValueError("invalid manifest root schema")
        if not isinstance(payload["records"], list):
            raise ValueError("records must be a list")
        records = []
        record_keys = {
            "timestamp",
            "anomaly_type",
            "affected_fields",
            "source_evidence",
            "severity",
            "review_status",
            "manifest_version",
            "recorded_source_close_at",
            "source_close_precision",
            "coverage_basis",
        }
        for raw in payload["records"]:
            if not isinstance(raw, dict) or set(raw) != record_keys:
                raise ValueError("invalid anomaly record schema")
            if not isinstance(raw["affected_fields"], list) or not isinstance(
                raw["source_evidence"], list
            ):
                raise ValueError("invalid anomaly list field")
            evidence = []
            for source in raw["source_evidence"]:
                if not isinstance(source, dict) or set(source) != {
                    "reference",
                    "sha256",
                    "observed_at",
                }:
                    raise ValueError("invalid evidence schema")
                evidence.append(
                    Evidence(
                        source["reference"],
                        source["sha256"],
                        _parse_time(source["observed_at"], "evidence observed_at"),
                    )
                )
            records.append(
                Anomaly(
                    timestamp=_parse_time(raw["timestamp"], "anomaly timestamp"),
                    anomaly_type=raw["anomaly_type"],
                    affected_fields=tuple(raw["affected_fields"]),
                    source_evidence=tuple(evidence),
                    severity=raw["severity"],
                    review_status=raw["review_status"],
                    manifest_version=raw["manifest_version"],
                    recorded_source_close_at=_parse_time(
                        raw["recorded_source_close_at"], "recorded_source_close_at"
                    ),
                    source_close_precision=raw["source_close_precision"],
                    coverage_basis=raw["coverage_basis"],
                )
            )
        return cls(
            manifest_version=payload["manifest_version"],
            version_available_at=_parse_time(
                payload["version_available_at"], "version_available_at"
            ),
            records=tuple(records),
        )

    @classmethod
    def from_bytes(cls, value: bytes) -> AnomalyManifest:
        try:
            manifest = cls.from_dict(json.loads(value))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid manifest JSON") from exc
        if value != manifest.to_bytes():
            raise ValueError("manifest JSON must use canonical serialization")
        return manifest

    @classmethod
    def load(cls, path: Path) -> AnomalyManifest:
        return cls.from_bytes(path.read_bytes())
