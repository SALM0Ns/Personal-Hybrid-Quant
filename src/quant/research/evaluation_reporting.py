"""Synthetic-only comparison sets, metrics and strict evidence-linked reports.

No filesystem, model fitting, historical runner, publication or UI integration.
Validation recomputes summaries from supplied typed in-memory evidence; digest
syntax alone does not verify source-file bytes or historical availability.
"""

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from quant.research import evaluation_protocol as p
from quant.research.forecast_accounting import (
    MODELS,
    PERIODS,
    SAMPLES,
    UNKNOWN_AVAILABILITY,
    Accounting,
    OriginUniverse,
    finite,
)
from quant.research.forecast_dataset import ANALYSIS_AS_OF
from quant.research.ridge_regression import AlphaSelection

SCHEMA_VERSION = "pqta-model-evaluation-v1"
SCOPES = (
    "method_own",
    "baseline_common",
    "feature_common",
    "paired_sensitivity_common",
)
STATUSES = (
    "not_run",
    "complete",
    "no_forecasts",
    "no_scored_forecasts",
    "blocked",
    "failed",
)
# Applicable to final, validly constructed synthetic reports only. Invalid
# or interrupted execution remains failed; unexecuted evaluation is not_run.
STATUS_PRECEDENCE = ("blocked", "no_forecasts", "no_scored_forecasts", "complete")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def utc_text(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(None)
    ):
        raise ValueError("aware UTC processing timestamp required")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sorted_origins(origins) -> tuple[datetime, ...]:
    items = tuple(origins)
    for origin in items:
        p.require_evaluation_origin(origin)
    if len(set(items)) != len(items):
        raise ValueError("duplicate timestamp")
    return tuple(sorted(items))


def timestamp_digest(origins) -> str:
    payload = "".join(
        origin.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ\n")
        for origin in sorted_origins(origins)
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Metrics:
    metric_count: int
    rmse: float | None
    mae: float | None
    directional_accuracy: float | None


def metrics(book: Accounting, origins=None) -> Metrics:
    """Score exactly the requested unique set; never silently drop a row."""
    requested = sorted_origins(book.scored_origins if origins is None else origins)
    by_origin = {s.forecast.origin: s for s in book.scores if s.status == "scored"}
    if not set(requested) <= by_origin.keys():
        raise ValueError("metric set contains an unscored origin")
    if not requested:
        return Metrics(0, None, None, None)
    errors, matches = [], 0
    for origin in requested:
        s = by_origin[origin]
        prediction, target = finite(s.forecast.prediction), finite(s.outcome.target)
        errors.append(finite(prediction - target))
        matches += ((prediction > 0) - (prediction < 0)) == (
            (target > 0) - (target < 0)
        )
    n = len(requested)
    try:
        rmse = finite(math.hypot(*errors) / math.sqrt(n))
        mae = finite(math.fsum(abs(e) for e in errors) / n)
    except (ArithmeticError, ValueError) as exc:
        raise ValueError("metric numerical failure; no origins may be dropped") from exc
    return Metrics(n, rmse, mae, matches / n)


def _book_index(books) -> dict:
    index = {}
    for book in books:
        if not isinstance(book, Accounting) or book.key in index:
            raise ValueError("duplicate or malformed accounting key")
        index[book.key] = book
    return index


@dataclass(frozen=True)
class ComparisonSet:
    scope: str
    universe: OriginUniverse
    participants: tuple[tuple[str, str], ...]  # (model, sample)
    origins: tuple[datetime, ...]
    parent_scope: str | None = None

    @property
    def comparison_id(self) -> str:
        suffix = ";".join(f"{m}:{s}" for m, s in self.participants)
        return f"{self.scope}:{self.parent_scope or '-'}:{suffix}"

    @property
    def sha256(self) -> str:
        return timestamp_digest(self.origins)


def comparison_set(books, scope: str, *, parent_scope=None) -> ComparisonSet:
    """Construct the exact intersection; callers cannot supply a reduced mask."""
    index = _book_index(books)
    if not index or scope not in SCOPES:
        raise ValueError("known scope and nonempty participant list required")
    values = tuple(index.values())
    universe = values[0].universe
    if any(b.universe != universe for b in values):
        raise ValueError("comparison periods/universes differ")
    participants = tuple(
        (m, s) for s in SAMPLES for m in MODELS if (universe.period_id, m, s) in index
    )
    samples = {s for _, s in participants}
    if scope == "method_own":
        expected = participants if len(participants) == 1 else ()
    elif scope in {"baseline_common", "feature_common"}:
        methods = MODELS[:3] if scope == "baseline_common" else MODELS
        expected = tuple((m, s) for s in SAMPLES if s in samples for m in methods)
        if len(samples) != 1:
            raise ValueError("common comparison requires one sample")
    else:
        if parent_scope not in {"baseline_common", "feature_common"}:
            raise ValueError("paired sensitivity requires explicit parent group")
        methods = MODELS[:3] if parent_scope == "baseline_common" else MODELS
        expected = tuple((m, s) for s in SAMPLES for m in methods)
    if participants != expected or not expected:
        raise ValueError("incorrect comparison participant membership")
    if scope != "paired_sensitivity_common" and parent_scope is not None:
        raise ValueError("parent scope applies only to paired sensitivity")
    common = set(values[0].scored_origins)
    for book in values[1:]:
        common.intersection_update(book.scored_origins)
    return ComparisonSet(
        scope, universe, participants, tuple(sorted(common)), parent_scope
    )


def _digest(value: str) -> None:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("lowercase SHA-256 required")


@dataclass(frozen=True)
class Provenance:
    """Expected identity/digest syntax, never authenticated artifact bytes."""

    dataset_spec_id: str
    artifact_build_id: str  # Source origin build, never the evaluation build.
    evaluation_spec_id: str
    evaluation_build_id: str
    silver_sha256: str
    gold_sha256: str
    manifest_sha256: str
    origin_ledger_sha256: str
    code_sha256: str
    dependency_versions: tuple[tuple[str, str], ...]
    feature_version: str
    manifest_version: str
    protocol_version: str = p.PROTOCOL_VERSION
    dataset_contract_version: str = p.DATASET_CONTRACT_VERSION
    artifact_bytes_verified: bool = False

    def __post_init__(self):
        if self.artifact_bytes_verified is not False:
            raise ValueError("synthetic reporting cannot claim verified artifact bytes")
        for name in (
            "dataset_spec_id",
            "artifact_build_id",
            "evaluation_spec_id",
            "evaluation_build_id",
            "silver_sha256",
            "gold_sha256",
            "manifest_sha256",
            "origin_ledger_sha256",
            "code_sha256",
        ):
            _digest(getattr(self, name))
        ids = (
            self.dataset_spec_id,
            self.artifact_build_id,
            self.evaluation_spec_id,
            self.evaluation_build_id,
        )
        if len(set(ids)) != 4:
            raise ValueError("source and evaluation identities must be separate")
        p.validate_versions(self.protocol_version, self.dataset_contract_version)
        if (
            type(self.dependency_versions) is not tuple
            or not self.dependency_versions
            or any(
                type(item) is not tuple
                or len(item) != 2
                or any(type(v) is not str or not v for v in item)
                for item in self.dependency_versions
            )
            or tuple(sorted(self.dependency_versions)) != self.dependency_versions
            or len(dict(self.dependency_versions)) != len(self.dependency_versions)
            or any(
                type(v) is not str or not v
                for v in (self.feature_version, self.manifest_version)
            )
        ):
            raise ValueError("canonical dependency/contract versions required")


@dataclass(frozen=True)
class ValidationEvidence:
    """Explicit synthetic assertions, not cryptographic or historical proof."""

    accounting_complete: bool
    temporal_checks_passed: bool
    identity_checks_passed: bool
    deterministic_rerun_passed: bool
    human_reviewed: bool
    mode: str = "synthetic"
    historical_execution_authorized: bool = False

    def __post_init__(self):
        if (
            self.mode != "synthetic"
            or self.historical_execution_authorized is not False
        ):
            raise ValueError("this reporting implementation is synthetic only")
        if any(type(v) is not bool for k, v in vars(self).items() if k != "mode"):
            raise ValueError("evidence gates must be Boolean")

    @property
    def complete(self) -> bool:
        return all(
            v
            for k, v in vars(self).items()
            if k not in {"mode", "historical_execution_authorized"}
        )


@dataclass(frozen=True)
class ReportInputs:
    accountings: tuple[Accounting, ...]
    comparisons: tuple[ComparisonSet, ...]
    provenance: Provenance
    evidence: ValidationEvidence
    evaluated_at_utc: datetime
    alpha_selection: AlphaSelection | None = None


def _period(universe: OriginUniverse) -> dict:
    return {
        "period_id": universe.period_id,
        "start_utc": utc_text(universe.start),
        "end_exclusive_utc": utc_text(universe.end),
        "interpretation": {
            "training_history": "accounting_only",
            "validation": "candidate_tuning_diagnostics_only",
            "test": "synthetic_frozen_alpha_model_comparison",
        }[universe.period_id],
    }


def _accounting_summary(book: Accounting) -> dict:
    counts = book.counts
    quality = Counter()
    for score in book.scores:
        q = score.outcome.quality
        quality["target_valid"] += score.outcome.target_valid
        quality["feature_complete"] += q.feature_complete
        quality["ar_lag_valid"] += q.ar_lag_valid
        quality["target_manifest_anomaly"] += score.outcome.target_manifest_anomaly
        quality[UNKNOWN_AVAILABILITY] += 1
        quality["gold_decision_ineligible"] += 1
        quality[
            f"anomaly_evidence_status__{score.outcome.anomaly_evidence_status}"
        ] += 1
        quality.update(f"anomaly_type__{t}" for t in q.anomaly_types)
        quality.update(f"affected_field__{f}" for f in q.affected_fields)
    return {
        "model_id": book.model_id,
        "sample_policy": book.sample_policy,
        "evaluation_period": _period(book.universe),
        "origin_count": counts["origins"],
        "forecast_count": counts["emitted"],
        "abstention_count": counts["abstained"],
        "own_scored_count": counts["scored"],
        "emitted_but_not_scored_count": counts["emitted_but_not_scored"],
        "not_scored_no_forecast_count": counts["not_scored_no_forecast"],
        "forecast_coverage": book.coverage,
        **book.reason_counts(),
        "quality_counts": dict(sorted(quality.items())),
    }


def _selection_summary(selection: AlphaSelection | None) -> dict | None:
    if selection is None:
        return None
    if not isinstance(selection, AlphaSelection):
        raise ValueError("typed frozen alpha selection required")
    # Reconstruct to recheck manual or corrupted instances as well.
    AlphaSelection(**vars(selection))
    payload = {
        "analysis_as_of": utc_text(selection.analysis_as_of),
        "selected_alpha": selection.selected_alpha,
        "candidate_origins": [utc_text(o) for o in selection.candidate_origins],
        "candidate_timestamp_set_sha256": timestamp_digest(selection.candidate_origins),
        "candidates": [
            {
                "alpha": c.alpha,
                "rmse": c.rmse,
                "failures": [[utc_text(o), r] for o, r in c.failures],
                "fit_failures": [[utc_text(o), r] for o, r in c.fit_failures],
            }
            for c in selection.candidates
        ],
        "interpretation": "a_primary_2024_candidate_tuning_only",
    }
    return {**payload, "sha256": hashlib.sha256(canonical_json(payload)).hexdigest()}


def _status(book, comparison, evidence, selection):
    """Blocked prerequisites, then full-period emission, then scored-set size.

    An empty comparison never turns a method that emitted into no_forecasts.
    Missing Ridge selection wins even when the whole period has no emissions.
    """
    if not book.scores:
        return "blocked", ["empty_origin_universe"]
    if not evidence.complete:
        return "blocked", ["synthetic_evidence_incomplete"]
    if book.model_id == "ridge_7" and (
        selection is None or selection.selected_alpha is None
    ):
        return "blocked", ["frozen_alpha_unavailable"]
    if book.counts["emitted"] == 0:
        return "no_forecasts", ["no_emitted_forecasts"]
    if not comparison.origins:
        return "no_scored_forecasts", [
            "no_own_scorable_outcomes"
            if not book.scored_origins
            else "no_common_timestamps"
        ]
    return "complete", []


def _comparison_status(books, comparison, evidence, selection):
    participants = []
    for book in books:
        status, reasons = _status(book, comparison, evidence, selection)
        participants.append(
            {
                "model_id": book.model_id,
                "sample_policy": book.sample_policy,
                "evaluation_status": status,
                "status_reasons": reasons,
            }
        )
    overall = min(
        (row["evaluation_status"] for row in participants),
        key=STATUS_PRECEDENCE.index,
    )
    return overall, participants


def build_report(inputs: ReportInputs) -> dict:
    """Build a synthetic report in memory; no historical execution is wired.

    Training-history has accounting only. Validation has accounting plus
    candidate tuning diagnostics only. Model-comparison metrics are test
    fixtures only, never selected-alpha validation replays.
    """
    if (
        not isinstance(inputs, ReportInputs)
        or type(inputs.accountings) is not tuple
        or type(inputs.comparisons) is not tuple
        or not isinstance(inputs.provenance, Provenance)
        or not isinstance(inputs.evidence, ValidationEvidence)
    ):
        raise ValueError("typed immutable report inputs required")
    utc_text(inputs.evaluated_at_utc)
    index = _book_index(inputs.accountings)
    # Each period has exactly one scheduled universe and one shared outcome
    # audit per origin, regardless of method/sample or comparison scope.
    outcomes, universes = {}, {}
    for book in index.values():
        period = book.universe.period_id
        if period in universes and universes[period] != book.universe:
            raise ValueError("inconsistent period universe")
        universes[period] = book.universe
        for score in book.scores:
            if score.checked_at > inputs.evaluated_at_utc:
                raise ValueError("processing completion precedes outcome accounting")
            key = (period, score.forecast.origin)
            if key in outcomes and outcomes[key] != score.outcome:
                raise ValueError("methods/samples must share source outcome audit")
            outcomes[key] = score.outcome
    selection = _selection_summary(inputs.alpha_selection)
    if (
        inputs.alpha_selection is not None
        and inputs.alpha_selection.analysis_as_of > inputs.evaluated_at_utc
    ):
        raise ValueError("processing completion precedes alpha evidence boundary")
    comparison_summaries, results, seen = [], [], set()
    for comparison in inputs.comparisons:
        if not isinstance(comparison, ComparisonSet):
            raise ValueError("typed comparison set required")
        if comparison.universe.period_id != "test":
            raise ValueError(
                "training accounting/validation tuning only; no comparison replay"
            )
        books = []
        for m, s in comparison.participants:
            key = (comparison.universe.period_id, m, s)
            if key not in index:
                raise ValueError("missing comparison participant")
            books.append(index[key])
        expected = comparison_set(
            books, comparison.scope, parent_scope=comparison.parent_scope
        )
        if expected != comparison:
            raise ValueError(
                "comparison is not the exact scored timestamp intersection"
            )
        key = (comparison.universe.period_id, comparison.comparison_id)
        if key in seen:
            raise ValueError("duplicate comparison key")
        seen.add(key)
        comparison_status, participant_statuses = _comparison_status(
            books, comparison, inputs.evidence, inputs.alpha_selection
        )
        comparison_summaries.append(
            {
                "comparison_id": comparison.comparison_id,
                "comparison_scope": comparison.scope,
                "parent_scope": comparison.parent_scope,
                "evaluation_status": comparison_status,
                "participant_statuses": participant_statuses,
                "evaluation_period": _period(comparison.universe),
                "participants": [
                    {"model_id": m, "sample_policy": s}
                    for m, s in comparison.participants
                ],
                "metric_count": len(comparison.origins),
                "timestamp_set_sha256": comparison.sha256,
                "first_origin": utc_text(comparison.origins[0])
                if comparison.origins
                else None,
                "last_origin": utc_text(comparison.origins[-1])
                if comparison.origins
                else None,
            }
        )
        for book in books:
            if (
                book.model_id == "ridge_7"
                and inputs.alpha_selection is not None
                and inputs.alpha_selection.analysis_as_of > book.universe.start
            ):
                raise ValueError("selection boundary exceeds test window cutoff")
            status, reasons = _status(
                book, comparison, inputs.evidence, inputs.alpha_selection
            )
            if comparison_status == "blocked" and status != "blocked":
                status, reasons = "blocked", ["comparison_participant_blocked"]
            # A blocked report preserves supplied emission accounting and
            # the exact declared comparison denominator. It does not compute
            # performance or certify those forecasts as valid Ridge outputs.
            if status == "blocked":
                values = Metrics(len(comparison.origins), None, None, None)
            else:
                values = metrics(book, comparison.origins)
            result = {
                **_accounting_summary(book),
                **asdict(values),
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "target_name": "target_next_1h_log_return",
                "target_unit": "raw_hourly_log_return",
                "comparison_scope": comparison.scope,
                "comparison_id": comparison.comparison_id,
                "timestamp_set_sha256": comparison.sha256,
                "evaluation_status": status,
                "status_reasons": reasons,
                "evaluated_at_utc": None
                if status == "blocked"
                else utc_text(inputs.evaluated_at_utc),
                **{
                    k: getattr(inputs.provenance, k)
                    for k in (
                        "dataset_spec_id",
                        "artifact_build_id",
                        "evaluation_spec_id",
                        "evaluation_build_id",
                        "protocol_version",
                        "dataset_contract_version",
                    )
                },
                "research_mode": "retrospective",
                "point_in_time_verified": False,
                "decision_eligible": False,
                "selected_alpha": selection["selected_alpha"]
                if book.model_id == "ridge_7" and selection
                else None,
                "alpha_selection_sha256": selection["sha256"]
                if book.model_id == "ridge_7" and selection
                else None,
            }
            results.append(result)
    comparison_summaries.sort(
        key=lambda r: (
            list(PERIODS).index(r["evaluation_period"]["period_id"]),
            r["comparison_id"],
        )
    )
    results.sort(
        key=lambda r: (
            list(PERIODS).index(r["evaluation_period"]["period_id"]),
            SAMPLES.index(r["sample_policy"]),
            r["comparison_id"],
            MODELS.index(r["model_id"]),
        )
    )
    provenance = asdict(inputs.provenance)
    provenance["dependency_versions"] = dict(inputs.provenance.dependency_versions)
    provenance["analysis_as_of"] = utc_text(ANALYSIS_AS_OF)
    report = {
        "schema_version": SCHEMA_VERSION,
        "evaluation_spec_id": inputs.provenance.evaluation_spec_id,
        "evaluation_build_id": inputs.provenance.evaluation_build_id,
        "provenance": provenance,
        "validation": asdict(inputs.evidence),
        "alpha_selection": selection,
        "accounting": [
            _accounting_summary(index[k])
            for k in sorted(
                index,
                key=lambda k: (
                    list(PERIODS).index(k[0]),
                    SAMPLES.index(k[2]),
                    MODELS.index(k[1]),
                ),
            )
        ],
        "comparison_sets": comparison_summaries,
        "results": results,
    }
    canonical_json(report)  # Reject nonfinite/unsupported JSON values.
    return report


def _json_types(value: object) -> None:
    """Reject Python-only coercions (notably tuple-to-list) at the JSON boundary."""
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            _json_types(item)
    elif type(value) is list:
        for item in value:
            _json_types(item)
    elif type(value) is float:
        finite(value)
    elif value is not None and type(value) not in (str, bool, int):
        raise ValueError("strict JSON field types required")


def validate_report(report: dict, *, inputs: ReportInputs) -> None:
    """Strict schema AND evidence equality, including keys/types/counts/sets.

    Expected evidence is supplied independently, not inferred from the
    potentially tampered report. This does not read or authenticate files.
    """
    if type(report) is not dict or report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unknown or malformed reporting schema")
    try:
        _json_types(report)
        actual = canonical_json(report)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid JSON field type or nonfinite metric") from exc
    if actual != canonical_json(build_report(inputs)):
        raise ValueError(
            "report schema/content disagrees with validated in-memory evidence"
        )


def validate_report_json(text: str, *, inputs: ReportInputs) -> dict:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    def invalid(value):
        raise ValueError(f"nonfinite JSON literal: {value}")

    report = json.loads(text, object_pairs_hook=unique, parse_constant=invalid)
    validate_report(report, inputs=inputs)
    return report
