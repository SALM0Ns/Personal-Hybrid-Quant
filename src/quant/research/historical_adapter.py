"""Read-only BTC/USDT historical inspection, never an execution bridge.

Original ledger values and anomaly vocabularies are retained. This module
does not construct synthetic fixtures, 4A outcomes, forecasts or scores.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import MappingProxyType

import polars as pl

from quant.features import engine
from quant.features.manifest import AnomalyManifest
from quant.ingestion.storage import SILVER_SCHEMA
from quant.research import evaluation_protocol as protocol
from quant.research import forecast_dataset as fd
from quant.research.forecast_accounting import PERIODS, OriginUniverse

AUDIT_VERSION = "pqta-003d-5a-readiness-v1"
SPEC_ID = "6d2d21257a00a5d1d49456b579ed00925df00667501ae84d8417fe393170e2c3"
BUILD_ID = "693697c2dc1ea82297959c39b2b6ec8da472f8bc74070e4cd4043d106246cc96"
SILVER_PATH = "data/silver/binance/1h/BTC-USDT.parquet"
GOLD_PATH = "data/gold/qnt-002b/btc_usdt_1h/candidate_v1/features.parquet"
MANIFEST_PATH = "configs/qnt-002b-btc-anomalies.candidate.v1.json"
ORIGIN_DIRECTORY = f"data/research/pqta-003/{SPEC_ID}/{BUILD_ID}"
# Independent approved anchors: docs/PQTA-003C_DATASET_IMPLEMENTATION.md.
ARTIFACT_HASHES = {
    "origin_ledger.parquet": (
        "15d177583efe09b4721da2bcf25356935b9263687f38384a52dbece76d338616"
    ),
    "dataset_validation.json": (
        "5cebda24aa47525c2b900d954b0e31ad7f11186c26870441574e353e9e4e4520"
    ),
    "provenance.json": (
        "7ce34fac38e9ed94540b428d8fe72016e3b94f7a6ed7416433735b516cff0d4f"
    ),
    "provenance.sha256": (
        "91be3a024436a5b8dd247a0d6f026b7deb0dc68b66dcaf03b84a9fa0731af6cd"
    ),
}


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class SourceIdentity:
    silver_sha256: str
    gold_sha256: str
    manifest_sha256: str
    dataset_spec_id: str
    artifact_build_id: str
    analysis_as_of: datetime
    feature_version: str
    manifest_version: str


@dataclass(frozen=True)
class HistoricalAnomaly:
    association: str
    source_column: str
    source_row_index: int
    raw: Mapping


def associate_anomaly(raw, *, source_column, source_row_index):
    """Preserve the complete record; do not infer association from its type.

    Unknown source columns retain their record under unresolved association.
    This is source association only, not evidence verification or 4A projection.
    """
    association = {
        "target_endpoint_anomalies": "target_endpoint",
        "involved_anomalies": "feature_window",
    }.get(source_column, "unresolved")
    if not isinstance(raw, Mapping) or type(source_row_index) is not int:
        raise ValueError("anomaly source record/index required")
    if source_row_index < 0 or not isinstance(source_column, str):
        raise ValueError("invalid anomaly source identity")
    return HistoricalAnomaly(association, source_column, source_row_index, _freeze(raw))


@dataclass(frozen=True)
class HistoricalFeatures:
    origin: datetime
    feature_open_t: datetime
    values: tuple[float | None, ...]
    null_reasons: tuple[str | None, ...]
    anomaly_involved_features: tuple[str, ...]
    feature_manifest_anomaly: bool
    anomalies: tuple[HistoricalAnomaly, ...]
    ar_lag_valid: bool
    ar_lag_manifest_anomaly: bool
    available_at: datetime | None
    decision_eligible: bool

    def forecast_fields(self):
        """Historical inspection view, not a runnable synthetic input."""
        return {
            "feature_open_t": self.feature_open_t,
            "forecast_origin_utc": self.origin,
            **dict(zip(engine.FEATURES, self.values, strict=True)),
            "feature_manifest_anomaly": self.feature_manifest_anomaly,
            "anomaly_involved_features": self.anomaly_involved_features,
            "ar_lag_valid": self.ar_lag_valid,
            "ar_lag_manifest_anomaly": self.ar_lag_manifest_anomaly,
            "gold_available_at": self.available_at,
            "gold_decision_eligible": self.decision_eligible,
            "research_only": True,
        }


@dataclass(frozen=True)
class HistoricalOutcome:
    origin: datetime
    target: float | None
    target_valid: bool
    invalid_reasons: tuple[str, ...]
    target_primary_null_reason: str | None
    target_manifest_anomaly: bool
    target_endpoint_anomalies: tuple[HistoricalAnomaly, ...]
    feature_window_anomalies: tuple[HistoricalAnomaly, ...]
    unresolved_anomalies: tuple[HistoricalAnomaly, ...]


@dataclass(frozen=True)
class HistoricalRecord:
    source_row_index: int
    source_identifier: str
    origin: datetime
    period: str
    source_values: Mapping
    features: HistoricalFeatures
    outcome: HistoricalOutcome


@dataclass(frozen=True)
class HistoricalAdapter:
    identity: SourceIdentity
    records: tuple[HistoricalRecord, ...]
    universes: tuple[OriginUniverse, ...]
    manifest: AnomalyManifest
    research_only: bool = True
    point_in_time_verified: bool = False
    decision_eligible: bool = False


@dataclass(frozen=True)
class HistoricalAudit:
    adapter: HistoricalAdapter | None
    report: dict
    canonical_report: bytes


def _result(adapter, report):
    return HistoricalAudit(adapter, report, fd.canonical_json(report))


def _failed(detail):
    return _result(
        None,
        {
            "audit_version": AUDIT_VERSION,
            "status": "failed",
            "execution_ready": False,
            "point_in_time_verified": False,
            "decision_eligible": False,
            "blocking_findings": [str(detail)],
        },
    )


def _check_identity(identity, manifest):
    if not isinstance(identity, SourceIdentity):
        raise ValueError("typed historical source identity required")
    for value in (
        identity.silver_sha256,
        identity.gold_sha256,
        identity.manifest_sha256,
        identity.dataset_spec_id,
        identity.artifact_build_id,
    ):
        if not fd._valid_digest(value):
            raise ValueError("invalid source SHA-256 syntax")
    protocol.validate_hour(identity.analysis_as_of)
    if identity.feature_version != engine.FEATURE_VERSION:
        raise ValueError("feature contract version mismatch")
    if (
        identity.manifest_sha256 != manifest.sha256
        or identity.manifest_version != manifest.manifest_version
    ):
        raise ValueError("manifest identity mismatch")
    expected = fd.dataset_spec_id(
        silver_sha256=identity.silver_sha256,
        gold_sha256=identity.gold_sha256,
        manifest_sha256=identity.manifest_sha256,
        analysis_as_of=identity.analysis_as_of,
        feature_version=identity.feature_version,
        manifest_version=identity.manifest_version,
    )
    if identity.dataset_spec_id != expected:
        raise ValueError("logical dataset identity mismatch")


def _check_gold_quality(gold_rows, by_open, manifest):
    """Audit null/quality metadata only; no feature values are recalculated."""
    anomalies = manifest.ordered_records()
    first = gold_rows[0]["timestamp"]
    for row in gold_rows:
        t = row["timestamp"]
        involved = tuple(a for a in anomalies if t - 168 * fd.HOUR <= a.timestamp <= t)
        if row["involved_anomalies"] != [fd._anomaly_record(a) for a in involved]:
            raise ValueError("feature-window anomaly records differ from manifest")
        sensitive = []
        for feature in engine.FEATURES:
            start = t - engine.LOOKBACK[feature] * fd.HOUR
            if t not in by_open:
                reason = "missing_candle"
            elif any(
                first <= start + i * fd.HOUR <= t and start + i * fd.HOUR not in by_open
                for i in range(engine.LOOKBACK[feature] + 1)
            ):
                reason = "gap_in_window"
            elif start < first:
                reason = "insufficient_history"
            elif feature == "volume_change_1h" and by_open[start]["volume"] == 0:
                reason = "zero_denominator"
            else:
                reason = None
            if row[f"null_reason__{feature}"] != reason:
                raise ValueError("feature null state differs from continuity contract")
            if row[feature] is not None and any(
                start <= a.timestamp <= t
                and engine._value_sensitive(feature, a, start, t)
                for a in anomalies
            ):
                sensitive.append(feature)
        if row["value_sensitive_features"] != sensitive:
            raise ValueError("feature sensitivity mask differs from manifest")
        own = [a for a in involved if a.timestamp == t]
        discrepancies = [a for a in own if a.anomaly_type == "source_discrepancy"]
        shortened = [a for a in own if a.anomaly_type == "shortened_close"]
        if (
            row["source_discrepancy_at_t"] != bool(discrepancies)
            or row["shortened_close_at_t"] != bool(shortened)
            or row["source_discrepancy_fields"]
            != sorted({f for a in discrepancies for f in a.affected_fields})
            or row["recorded_source_close_at"]
            != (shortened[0].recorded_source_close_at if shortened else None)
        ):
            raise ValueError("source anomaly metadata mismatch")
        flags = set()
        if row["missing_hour"]:
            flags.add("missing_hour")
        for reason, flag in (
            ("gap_in_window", "missing_hour_in_window"),
            ("insufficient_history", "insufficient_history"),
            ("zero_denominator", "zero_denominator"),
        ):
            if any(row[f"null_reason__{f}"] == reason for f in engine.FEATURES):
                flags.add(flag)
        if involved:
            flags.add("anomaly_in_window")
        flags.update(
            a.anomaly_type
            for a in involved
            if a.anomaly_type in {"source_discrepancy", "shortened_close"}
        )
        if row["available_at"] is None:
            flags.add("unknown_availability")
        if row["quality_flags"] != sorted(flags):
            raise ValueError("Gold quality flags differ from source metadata")


def _inspect(silver, gold, ledger, manifest, identity, proof=None):
    if not all(isinstance(f, pl.DataFrame) for f in (silver, gold, ledger)):
        raise ValueError("typed source DataFrames required")
    if not isinstance(manifest, AnomalyManifest):
        raise ValueError("typed source anomaly manifest required")
    _check_identity(identity, manifest)
    for frame, schema in (
        (silver, SILVER_SCHEMA),
        (gold, engine.GOLD_SCHEMA),
        (ledger, fd.LEDGER_SCHEMA),
    ):
        if frame.schema != schema or frame.columns != list(schema):
            raise ValueError("source schema/column order drift")
    source = engine._audit_source(silver, identity.analysis_as_of)
    if any(r["ingested_at"] is None for r in source):
        raise ValueError("missing source observation metadata")
    gold_rows = fd._audit_gold(
        gold, source, manifest, identity.analysis_as_of, identity.silver_sha256
    )
    rows = fd.validate_ledger(ledger)
    if len(rows) != len(gold_rows):
        raise ValueError("ledger/Gold timeline row count mismatch")
    by_open = {r["timestamp"]: r for r in source}
    _check_gold_quality(gold_rows, by_open, manifest)
    opens = sorted(by_open)
    anomalies = manifest.ordered_records()
    records = []
    for index, (row, g) in enumerate(zip(rows, gold_rows, strict=True)):
        t, origin = row["feature_open_t"], row["forecast_origin_utc"]
        protocol.validate_hour(t)
        protocol.validate_hour(origin)
        if any(row[fd.GOLD_COPY_RENAMES.get(k, k)] != v for k, v in g.items()):
            raise ValueError("ledger values differ from original Gold")
        if (
            row["dataset_spec_id"] != identity.dataset_spec_id
            or row["dataset_contract_version"] != fd.DATASET_CONTRACT_VERSION
            or row["protocol_version"] != fd.PROTOCOL_VERSION
            or row["analysis_as_of"] != identity.analysis_as_of
            or row["feature_version"] != identity.feature_version
            or row["gold_available_at"] is not None
            or row["gold_decision_eligible"] is not False
        ):
            raise ValueError("historical version/identity/availability mismatch")
        current, following = by_open.get(t), by_open.get(origin)
        position = bisect_right(opens, t)
        target, reasons = fd.target_audit(
            current,
            following,
            current_open=t,
            next_observed_open=opens[position] if position < len(opens) else None,
            analysis_as_of=identity.analysis_as_of,
        )
        if (
            row["target_next_1h_log_return"] != target
            or row["target_null_reasons"] != reasons
        ):
            raise ValueError("target value/reasons differ from exact Silver endpoints")
        endpoints = [a for a in anomalies if a.timestamp in (t, origin)]
        if row["target_endpoint_anomalies"] != [
            fd._anomaly_record(a) for a in endpoints
        ]:
            raise ValueError("target-endpoint anomaly records differ from manifest")
        sensitive = target is not None and any(
            a.anomaly_type == "shortened_close"
            or a.anomaly_type == "source_discrepancy"
            and bool(set(a.affected_fields) & {"close", "unknown"})
            for a in endpoints
        )
        expected = {
            "current_candle_present": current is not None,
            "next_candle_present": following is not None,
            "current_candle_valid": current is not None,
            "next_candle_valid": following is not None,
            "current_candle_complete": current is not None
            and origin <= identity.analysis_as_of,
            "next_candle_complete": following is not None
            and origin + fd.HOUR <= identity.analysis_as_of,
            "ar_lag_valid": current is not None
            and t - fd.HOUR in by_open
            and origin <= identity.analysis_as_of,
            "ar_lag_manifest_anomaly": any(
                a.timestamp in (t - fd.HOUR, t) for a in anomalies
            ),
            "target_value_sensitive": sensitive,
        }
        if any(row[k] != v for k, v in expected.items()):
            raise ValueError("source validity/AR lag/anomaly mask mismatch")
        target_records = tuple(
            associate_anomaly(
                a, source_column="target_endpoint_anomalies", source_row_index=index
            )
            for a in row["target_endpoint_anomalies"]
        )
        feature_records = tuple(
            associate_anomaly(
                a, source_column="involved_anomalies", source_row_index=index
            )
            for a in row["involved_anomalies"]
        )
        features = HistoricalFeatures(
            origin,
            t,
            tuple(row[f] for f in engine.FEATURES),
            tuple(row[f"null_reason__{f}"] for f in engine.FEATURES),
            tuple(row["anomaly_involved_features"]),
            row["feature_manifest_anomaly"],
            feature_records,
            row["ar_lag_valid"],
            row["ar_lag_manifest_anomaly"],
            row["gold_available_at"],
            row["gold_decision_eligible"],
        )
        outcome = HistoricalOutcome(
            origin,
            row["target_next_1h_log_return"],
            row["target_valid"],
            tuple(row["target_null_reasons"]),
            row["target_primary_null_reason"],
            row["target_manifest_anomaly"],
            target_records,
            feature_records,
            (),
        )
        records.append(
            HistoricalRecord(
                index,
                ORIGIN_DIRECTORY + "/origin_ledger.parquet"
                if proof
                else "in_memory:origin_ledger",
                origin,
                row["split_id"],
                _freeze(row),
                features,
                outcome,
            )
        )
    universes = []
    first, end = (
        rows[0]["forecast_origin_utc"],
        rows[-1]["forecast_origin_utc"] + fd.HOUR,
    )
    for period, (lower, upper) in PERIODS.items():
        start, stop = max(lower, first), min(upper, end)
        if start > stop:
            start = stop = lower
        universes.append(OriginUniverse(period, start, stop))
    adapter = HistoricalAdapter(identity, tuple(records), tuple(universes), manifest)
    report = _report(adapter, silver.height, manifest, proof)
    return _result(adapter, report)


def _report(adapter, silver_rows, manifest, proof):
    records, identity = adapter.records, adapter.identity
    counts = Counter(r.period for r in records)
    endpoint = [a for r in records for a in r.outcome.target_endpoint_anomalies]
    feature = [a for r in records for a in r.outcome.feature_window_anomalies]
    fields = sorted(
        {f for a in (*endpoint, *feature) for f in a.raw["affected_fields"]}
    )
    unprojectable = sorted(set(fields) - {"open", "high", "low", "close", "volume"})
    blocks = [] if proof else ["source_file_bytes_not_verified_in_memory"]
    return {
        "audit_version": AUDIT_VERSION,
        "status": "ready_for_architect_review" if not blocks else "blocked",
        "readiness_scope": "read_only_historical_adapter",
        "dataset_spec_id": identity.dataset_spec_id,
        "artifact_build_id": identity.artifact_build_id,
        "dataset_contract_version": fd.DATASET_CONTRACT_VERSION,
        "protocol_version": fd.PROTOCOL_VERSION,
        "feature_version": identity.feature_version,
        "manifest_version": identity.manifest_version,
        "analysis_as_of": fd._utc_text(identity.analysis_as_of),
        "feature_order": list(engine.FEATURES),
        "timeline_bounds": {
            "first_feature_open": fd._utc_text(records[0].features.feature_open_t),
            "last_feature_open": fd._utc_text(records[-1].features.feature_open_t),
            "first_origin": fd._utc_text(records[0].origin),
            "last_origin": fd._utc_text(records[-1].origin),
        },
        "artifact_rows": {
            "silver": silver_rows,
            "gold": len(records),
            "origin_ledger": len(records),
        },
        "period_counts": dict(sorted(counts.items())),
        "periods": [
            {
                "period_id": u.period_id,
                "start": fd._utc_text(u.start),
                "end_exclusive": fd._utc_text(u.end),
                "origin_count": len(u.origins),
            }
            for u in adapter.universes
        ],
        "missing_hours": sum(r.source_values["missing_hour"] for r in records),
        "feature_complete": sum(r.source_values["feature_complete"] for r in records),
        "feature_null_counts": {
            f: sum(r.features.values[i] is None for r in records)
            for i, f in enumerate(engine.FEATURES)
        },
        "target_valid": sum(r.outcome.target_valid for r in records),
        "target_null": sum(not r.outcome.target_valid for r in records),
        "target_null_reason_counts": dict(
            sorted(
                Counter(
                    reason for r in records for reason in r.outcome.invalid_reasons
                ).items()
            )
        ),
        "target_primary_null_reason_counts": dict(
            sorted(
                Counter(
                    r.outcome.target_primary_null_reason
                    for r in records
                    if r.outcome.target_primary_null_reason is not None
                ).items()
            )
        ),
        "ar_lag_valid": sum(r.features.ar_lag_valid for r in records),
        "sample_target_eligible": {
            name: sum(r.source_values[column]["target_eligible"] for r in records)
            for name, column in (
                ("a_primary", "lane_a_primary"),
                ("a_sensitivity", "lane_a_sensitivity"),
            )
        },
        "anomalies": {
            "source_categories": dict(
                sorted(Counter(a.anomaly_type for a in manifest.records).items())
            ),
            "target_endpoint_associations": len(endpoint),
            "target_endpoint_rows": sum(
                bool(r.outcome.target_endpoint_anomalies) for r in records
            ),
            "feature_window_associations": len(feature),
            "feature_window_rows": sum(
                bool(r.outcome.feature_window_anomalies) for r in records
            ),
            "unresolved_associations": sum(
                len(r.outcome.unresolved_anomalies) for r in records
            ),
            "original_field_names": fields,
            "fields_not_projectable_to_4a": unprojectable,
            "evidence_completeness": "unverified",
            "evidence_references_checked": False,
        },
        "temporal_checks": {
            name: True
            for name in (
                "utc_hour_alignment",
                "unique_complete_audit_timeline",
                "feature_open_origin_alignment",
                "theoretical_target_closure",
                "exact_silver_endpoints",
                "no_gap_bridging",
                "exact_ar_lag",
                "approved_period_boundaries",
                "forecast_outcome_separation",
            )
        },
        "provenance": {
            "hash_syntax_validated": True,
            "file_bytes_verified": proof is not None,
            "source_identity_matched": proof is not None,
            "chain_complete": proof is not None,
            "sources": proof or {},
            "asserted_source_hashes": {
                "silver": identity.silver_sha256,
                "gold": identity.gold_sha256,
                "manifest_canonical": identity.manifest_sha256,
            },
        },
        "blocking_findings": blocks,
        "execution_ready": False,
        "execution_blockers": [
            "historical_execution_not_authorized",
            "4a_quality_projection_policy_deferred",
            "historical_point_in_time_availability_unverified",
        ],
        "limitations": [
            "anomaly_evidence_not_independently_verified",
            "feature_values_copied_not_recalculated",
            "theoretical_closure_is_not_publication",
            "no_execution_bridge",
        ],
        "research_only": True,
        "point_in_time_verified": False,
        "decision_eligible": False,
    }


def audit_frames(silver, gold, ledger, manifest, *, identity):
    """Inspect supplied frames; identities are asserted, not byte authenticated."""
    try:
        return _inspect(silver, gold, ledger, manifest, identity)
    except (ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as exc:
        return _failed(exc)


def _json_bytes(data):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate metadata key")
            result[k] = v
        return result

    value = json.loads(data, object_pairs_hook=unique)
    if fd.canonical_json(value) != data:
        raise ValueError("noncanonical artifact metadata")
    return value


def _verified_bytes(root, relative, expected, proof):
    path = root / relative
    if fd.file_sha256(path) != expected:
        raise ValueError(f"pinned source hash mismatch: {relative}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"source changed while inspected: {relative}")
    proof[relative] = {
        "expected_sha256": expected,
        "observed_sha256": expected,
        "file_bytes_verified": True,
    }
    return data


def audit_pinned_history(root: Path) -> HistoricalAudit:
    """Verify approved bytes first, then audit; never rebuild or write files."""
    try:
        proof = {}
        directory = root / ORIGIN_DIRECTORY
        if {p.name for p in directory.iterdir()} != set(ARTIFACT_HASHES):
            raise ValueError("immutable origin build has missing or unexpected files")
        payloads = {
            name: _verified_bytes(root, f"{ORIGIN_DIRECTORY}/{name}", digest, proof)
            for name, digest in ARTIFACT_HASHES.items()
        }
        silver_bytes = _verified_bytes(root, SILVER_PATH, fd.SILVER_SHA256, proof)
        gold_bytes = _verified_bytes(root, GOLD_PATH, fd.GOLD_SHA256, proof)
        manifest_bytes = (root / MANIFEST_PATH).read_bytes()
        manifest = AnomalyManifest.from_dict(json.loads(manifest_bytes))
        if manifest.sha256 != fd.MANIFEST_SHA256:
            raise ValueError("pinned canonical manifest hash mismatch")
        proof[MANIFEST_PATH] = {
            "expected_canonical_sha256": fd.MANIFEST_SHA256,
            "observed_canonical_sha256": manifest.sha256,
            "observed_file_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "file_bytes_verified": True,
        }
        provenance = _json_bytes(payloads["provenance.json"])
        quality = _json_bytes(payloads["dataset_validation.json"])
        if (
            payloads["provenance.sha256"]
            != (ARTIFACT_HASHES["provenance.json"] + "\n").encode()
        ):
            raise ValueError("provenance sidecar mismatch")
        schema = [[name, str(dtype)] for name, dtype in fd.LEDGER_SCHEMA.items()]
        if (
            provenance["dataset_spec_id"] != SPEC_ID
            or provenance["artifact_build_id"] != BUILD_ID
            or provenance["schema"] != schema
            or provenance["dataset_contract_version"] != fd.DATASET_CONTRACT_VERSION
            or provenance["protocol_version"] != fd.PROTOCOL_VERSION
            or provenance["serializer_version"] != fd.SERIALIZER_VERSION
            or provenance["parquet_writer"] != fd.PARQUET_WRITER
            or provenance["code_revision_sha256"] != fd._code_revision()
            or fd.artifact_build_id(
                SPEC_ID,
                code_revision=provenance["code_revision_sha256"],
                dependency_versions=provenance["dependency_versions"],
            )
            != BUILD_ID
            or provenance["artifact_sha256"]
            != {
                name: ARTIFACT_HASHES[name]
                for name in ("origin_ledger.parquet", "dataset_validation.json")
            }
            or provenance["input_sha256"]
            != {
                "silver": fd.SILVER_SHA256,
                "gold": fd.GOLD_SHA256,
                "manifest_canonical": fd.MANIFEST_SHA256,
            }
        ):
            raise ValueError("immutable provenance identity mismatch")
        identity = SourceIdentity(
            fd.SILVER_SHA256,
            fd.GOLD_SHA256,
            fd.MANIFEST_SHA256,
            SPEC_ID,
            BUILD_ID,
            fd.ANALYSIS_AS_OF,
            engine.FEATURE_VERSION,
            manifest.manifest_version,
        )
        silver, gold, ledger = (
            pl.read_parquet(BytesIO(b))
            for b in (silver_bytes, gold_bytes, payloads["origin_ledger.parquet"])
        )
        actual = fd.validation_report(
            ledger,
            silver_rows=silver.height,
            gold_sha256=fd.GOLD_SHA256,
            silver_sha256=fd.SILVER_SHA256,
            manifest_sha256=fd.MANIFEST_SHA256,
        )
        if actual != quality:
            raise ValueError("stored dataset validation report mismatch")
        return _inspect(silver, gold, ledger, manifest, identity, proof)
    except (OSError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as exc:
        return _failed(type(exc).__name__ if isinstance(exc, OSError) else exc)
