"""Synthetic-only chronological coordination; no historical or other I/O.

Fixtures supply validated return labels, not raw candles. AR adapters map
adjacent labels into public model input types without recomputing returns.
Every target and target-side annotation is accessed only after closure.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from quant.features.engine import FEATURES
from quant.research import evaluation_protocol as p
from quant.research import evaluation_reporting as reporting
from quant.research import forecast_accounting as accounting
from quant.research import ridge_regression as ridge
from quant.research import statistical_baselines as baselines


@dataclass(frozen=True)
class SyntheticFeatures:
    """Feature row known at origin; its source candle opens one hour earlier.

    Values are supplied fixtures, never recalculated or filled by this module.
    Missing/nonfinite values retain the existing Ridge abstention semantics.
    """

    origin: datetime
    values: tuple[float | None, ...]
    anomaly_involved_features: tuple[str, ...] = ()

    def __post_init__(self):
        p.require_evaluation_origin(self.origin)
        if type(self.values) is not tuple or len(self.values) != len(FEATURES):
            raise ValueError("exact seven-feature tuple required")
        for value in self.values:
            if value is not None and type(value) not in (int, float):
                raise ValueError("feature values must be nullable numeric scalars")
            if type(value) is int:
                try:
                    float(value)
                except OverflowError as exc:
                    raise ValueError(
                        "feature integer exceeds Float64 representation"
                    ) from exc
        involved = self.anomaly_involved_features
        if (
            type(involved) is not tuple
            or any(type(f) is not str or f not in FEATURES for f in involved)
            or tuple(f for f in FEATURES if f in involved) != involved
        ):
            raise ValueError("anomaly features must be unique in contract order")

    def forecast_fields(self) -> dict:
        return {
            **_time_fields(self.origin),
            **dict(zip(FEATURES, self.values, strict=True)),
            "feature_manifest_anomaly": bool(self.anomaly_involved_features),
            "anomaly_involved_features": self.anomaly_involved_features,
        }


@dataclass(frozen=True)
class SyntheticFixture:
    """Explicit caller attestation, not authentication of data origin.

    Outcome validity asserts consecutive valid source candles under the
    governing target contract. A missing scheduled outcome is an error, not
    permission to fabricate a target. Seed history may contain genuine holes.
    """

    synthetic: bool
    features: tuple[SyntheticFeatures, ...]
    outcomes: tuple[accounting.Outcome, ...]

    def __post_init__(self):
        if self.synthetic is not True:
            raise ValueError("explicit synthetic=True attestation required")
        for rows, expected in (
            (self.features, SyntheticFeatures),
            (self.outcomes, accounting.Outcome),
        ):
            if type(rows) is not tuple or any(
                not isinstance(r, expected) for r in rows
            ):
                raise ValueError("typed immutable fixture tuples required")
            # Index only clocks, never future values, validity or annotations.
            origins = tuple(row.origin for row in rows)
            if tuple(sorted(set(origins))) != origins:
                raise ValueError("fixture origins must be sorted and unique")


@dataclass(frozen=True)
class Admission:
    event: datetime
    label_origins: tuple[datetime, ...]


@dataclass(frozen=True)
class ModelUpdate:
    event: datetime
    model_id: str
    sample_policy: str
    label_origins: tuple[datetime, ...]
    max_outcome_close: datetime | None
    fit: baselines.ARFit | ridge.Fit | None
    reason: str | None
    selected_alpha: float | None = None


@dataclass(frozen=True)
class SyntheticRun:
    forecasts: tuple[accounting.Forecast, ...]
    admissions: tuple[Admission, ...]
    updates: tuple[ModelUpdate, ...]
    report_inputs: reporting.ReportInputs
    report: dict
    canonical_report: bytes

    @property
    def accountings(self) -> tuple[accounting.Accounting, ...]:
        return self.report_inputs.accountings

    @property
    def comparisons(self) -> tuple[reporting.ComparisonSet, ...]:
        return self.report_inputs.comparisons


def _time_fields(origin: datetime) -> dict:
    return {"feature_open_t": origin - p.HOUR, "forecast_origin_utc": origin}


def _finite(value: object) -> bool:
    try:
        accounting.finite(value)
        return True
    except ValueError:
        return False


def _features(origin, by_origin):
    row = by_origin.get(origin)
    # No synthetic observation is inserted into the fixture/history. This
    # forecast-side null view records that current features are unavailable.
    return (
        row.forecast_fields()
        if row is not None
        else {
            **_time_fields(origin),
            **dict.fromkeys(FEATURES),
            "feature_manifest_anomaly": False,
            "anomaly_involved_features": (),
        }
    )


def _ar_history(admitted, *, origin, sample):
    pairs = []
    for h, target in admitted.items():
        previous = admitted.get(h - p.HOUR)
        if previous is None:
            continue
        if p.historical_row_eligible(
            "ar_1",
            sample,
            label_origin=h,
            current_origin=origin,
            target_valid=target.target_valid,
            target_manifest_anomaly=target.target_manifest_anomaly,
            ar_lag_valid=previous.target_valid,
            ar_lag_manifest_anomaly=previous.target_manifest_anomaly,
        ):
            # Label h is y_s for candle open s=h-1h; label h-1h is r_s.
            pairs.append(baselines.ARPair(h - p.HOUR, previous.target, target.target))
    return baselines.ARHistory(origin, sample, tuple(pairs))


def _current_lag(admitted, *, origin, sample):
    previous = admitted.get(origin - p.HOUR)
    reason = None
    if previous is None or not previous.target_valid:
        reason = "ar_lag_missing_or_invalid"
    elif sample == "a_sensitivity" and previous.target_manifest_anomaly:
        reason = "ar_lag_manifest_anomaly"
    return baselines.CurrentLag(
        origin, sample, None if reason else previous.target, reason
    )


def _ridge_history(admitted, features, *, origin, sample):
    rows = []
    for h, outcome in admitted.items():
        fields = _features(h, features)
        rows.append(
            ridge.ResearchRow(
                h,
                tuple(fields[f] for f in FEATURES),
                outcome.target,
                outcome.target_valid,
                outcome.target_manifest_anomaly,
                fields["feature_manifest_anomaly"],
            )
        )
    return ridge.prepare_history(rows, origin=origin, sample=sample)


def _ridge_reasons(fields, sample, fit):
    reasons = [f"feature_null__{f}" for f in FEATURES if not _finite(fields[f])]
    if sample == "a_sensitivity":
        reasons.extend(
            f"feature_manifest_anomaly__{f}"
            for f in fields["anomaly_involved_features"]
        )
    if fit is None:
        reasons.append("insufficient_training_history")
    elif fit.reason is not None:
        reasons.append(fit.reason)
    return reasons


def _ridge_selection_available(period, origin, selection):
    """A frozen selection permits replay only in Test, never diagnostics."""
    return (
        period == "test"
        and selection is not None
        and selection.analysis_as_of <= origin
        and selection.selected_alpha is not None
    )


def _forecast(origin, model, sample, prediction, reasons):
    if prediction.reason is not None:
        reasons.append(prediction.reason)
    ordered = tuple(
        r for r in accounting.forecast_reason_order(model, sample) if r in reasons
    )
    if prediction.reason != (ordered[0] if ordered else None):
        raise ValueError("adapter disagrees with model abstention priority")
    return accounting.Forecast(origin, model, sample, prediction.value, ordered)


def _audit_update(event, model, sample, labels, fit=None, reason=None, alpha=None):
    labels = tuple(labels)
    maximum = max((h + p.HOUR for h in labels), default=None)
    if maximum is not None and maximum > event:
        raise ValueError("update admits an incomplete label")
    return ModelUpdate(event, model, sample, labels, maximum, fit, reason, alpha)


def _comparisons(books, universe):
    if universe.period_id != "test":
        return ()  # Training accounting and validation tuning diagnostics only.
    sets = []
    for sample in accounting.SAMPLES:
        group = tuple(b for b in books if b.sample_policy == sample)
        sets.extend(reporting.comparison_set((b,), "method_own") for b in group)
        sets.append(reporting.comparison_set(group[:3], "baseline_common"))
        sets.append(reporting.comparison_set(group, "feature_common"))
    for parent in ("baseline_common", "feature_common"):
        group = (
            books
            if parent == "feature_common"
            else tuple(b for b in books if b.model_id != "ridge_7")
        )
        sets.append(
            reporting.comparison_set(
                group, "paired_sensitivity_common", parent_scope=parent
            )
        )
    return tuple(sets)


def run_synthetic(
    fixture: SyntheticFixture,
    universe: accounting.OriginUniverse,
    *,
    provenance: reporting.Provenance,
    evidence: reporting.ValidationEvidence,
    evaluated_at_utc: datetime,
    alpha_selection: ridge.AlphaSelection | None = None,
) -> SyntheticRun:
    """Coordinate supplied fixtures only; no loading, tuning or publication.

    A new UTC clock event closes targets before admission/refit/forecast.
    Current and future outcomes never enter model prediction arguments.
    Frozen validation diagnostics may be supplied, never selected here.
    """
    if not isinstance(fixture, SyntheticFixture) or not isinstance(
        universe, accounting.OriginUniverse
    ):
        raise ValueError("typed synthetic fixture and universe required")
    if fixture.synthetic is not True or not isinstance(
        evidence, reporting.ValidationEvidence
    ):
        raise ValueError("synthetic fixture/evidence required")
    if not isinstance(provenance, reporting.Provenance):
        raise ValueError("typed synthetic provenance required")
    reporting.utc_text(evaluated_at_utc)
    if evaluated_at_utc < universe.end:
        raise ValueError("processing completion precedes final target closure")
    if alpha_selection is not None:
        if not isinstance(alpha_selection, ridge.AlphaSelection):
            raise ValueError("frozen AlphaSelection required")
        ridge.AlphaSelection(**vars(alpha_selection))
        if (
            universe.period_id == "test"
            and alpha_selection.analysis_as_of > universe.start
        ):
            raise ValueError("selection boundary exceeds test window cutoff")
    features = {r.origin: r for r in fixture.features}
    outcomes = {r.origin: r for r in fixture.outcomes}
    if not set(universe.origins) <= outcomes.keys():
        raise ValueError("every scheduled origin requires an explicit outcome audit")
    pending, admitted, forecasts, admissions, updates = {}, {}, [], [], []
    scores = {(m, s): [] for s in accounting.SAMPLES for m in accounting.MODELS}
    ar_fits = dict.fromkeys(accounting.SAMPLES)
    ridge_fits = dict.fromkeys(accounting.SAMPLES)
    outcome_iterator = iter(outcomes)
    next_label = next(outcome_iterator, None)

    def advance(clock):
        nonlocal next_label
        newly_admitted = []
        while next_label is not None and p.label_completed(next_label, clock):
            h = next_label
            observed = outcomes[h]  # Values/flags are read only after closure.
            admitted[h] = observed
            newly_admitted.append(h)
            if h in pending:
                fields = _features(h, features)
                lag = admitted.get(h - p.HOUR)
                quality = replace(
                    observed.quality,
                    feature_complete=all(_finite(fields[f]) for f in FEATURES),
                    ar_lag_valid=lag is not None and lag.target_valid,
                )
                audit = replace(observed, quality=quality)
                for f in pending.pop(h):
                    scores[(f.model_id, f.sample_policy)].append(
                        accounting.Score(f, audit, clock)
                    )
            next_label = next(outcome_iterator, None)
        admissions.append(Admission(clock, tuple(newly_admitted)))

    for origin in universe.origins:
        advance(origin)
        fields = _features(origin, features)
        current = []
        for sample in accounting.SAMPLES:
            time_fields = _time_fields(origin)
            prediction = baselines.zero_return(time_fields, sample=sample)
            current.append(_forecast(origin, "zero_return", sample, prediction, []))

            labels = tuple(
                baselines.HistoricalTarget(
                    h, row.target, row.target_valid, row.target_manifest_anomaly
                )
                for h, row in admitted.items()
            )
            mean_history = baselines.prepare_mean_history(
                labels, origin=origin, sample=sample
            )
            prediction = baselines.predict_mean(time_fields, mean_history)
            updates.append(
                _audit_update(
                    origin,
                    "expanding_mean",
                    sample,
                    (r.label_origin for r in mean_history.labels),
                    reason=prediction.reason,
                )
            )
            current.append(_forecast(origin, "expanding_mean", sample, prediction, []))

            if p.refit_scheduled("ar_1", origin):
                ar_fits[sample] = None  # Invalidate before attempting this day's fit.
                history = _ar_history(admitted, origin=origin, sample=sample)
                ar_fits[sample] = baselines.fit_ar(history)
                updates.append(
                    _audit_update(
                        origin,
                        "ar_1",
                        sample,
                        (r.feature_open + p.HOUR for r in history.pairs),
                        ar_fits[sample],
                        ar_fits[sample].reason,
                    )
                )
            lag = _current_lag(admitted, origin=origin, sample=sample)
            fit = ar_fits[sample]
            reasons = [lag.reason] if lag.reason else []
            if fit is None:
                reasons.append("insufficient_training_history")
                prediction = baselines.Prediction(None, reasons[0])
            else:
                if fit.reason:
                    reasons.append(fit.reason)
                prediction = baselines.predict_ar(time_fields, fit, lag)
            current.append(_forecast(origin, "ar_1", sample, prediction, reasons))

            if p.refit_scheduled("ridge_7", origin):
                ridge_fits[sample] = None
                available = _ridge_selection_available(
                    universe.period_id, origin, alpha_selection
                )
                if available:
                    history = _ridge_history(
                        admitted, features, origin=origin, sample=sample
                    )
                    ridge_fits[sample] = ridge.fit_ridge(
                        history,
                        alpha=alpha_selection.selected_alpha,
                        selection=alpha_selection,
                    )
                    updates.append(
                        _audit_update(
                            origin,
                            "ridge_7",
                            sample,
                            (r.label_origin for r in history.rows),
                            ridge_fits[sample],
                            ridge_fits[sample].reason,
                            alpha_selection.selected_alpha,
                        )
                    )
                else:
                    updates.append(
                        _audit_update(
                            origin,
                            "ridge_7",
                            sample,
                            (),
                            reason=(
                                "frozen_alpha_unavailable"
                                if universe.period_id == "test"
                                else "ridge_replay_not_authorized"
                            ),
                        )
                    )
            fit = ridge_fits[sample]
            reasons = _ridge_reasons(fields, sample, fit)
            prediction = (
                ridge.predict(fields, fit)
                if fit is not None
                else baselines.Prediction(None, reasons[0])
            )
            current.append(_forecast(origin, "ridge_7", sample, prediction, reasons))
        forecasts.extend(current)
        pending[origin] = tuple(current)
    if universe.origins:
        advance(universe.end)  # Close final outcome; empty windows have no events.
    if pending:
        raise ValueError("incomplete final outcome accounting")
    books = tuple(
        accounting.account(universe, m, s, scores[(m, s)])
        for s in accounting.SAMPLES
        for m in accounting.MODELS
    )
    comparisons = _comparisons(books, universe)
    inputs = reporting.ReportInputs(
        books, comparisons, provenance, evidence, evaluated_at_utc, alpha_selection
    )
    report = reporting.build_report(inputs)
    reporting.validate_report(report, inputs=inputs)
    return SyntheticRun(
        tuple(forecasts),
        tuple(admissions),
        tuple(updates),
        inputs,
        report,
        reporting.canonical_json(report),
    )
