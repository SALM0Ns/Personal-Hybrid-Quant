"""Chronological coordination of explicitly invented in-memory fixtures only."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from quant.research import evaluation_protocol as p
from quant.research import evaluation_reporting as reporting
from quant.research import forecast_accounting as a
from quant.research import model_evaluation as runner
from quant.research import ridge_regression as ridge
from quant.research import statistical_baselines as baselines

H = timedelta(hours=1)
START = datetime(2025, 1, 1, tzinfo=UTC)
RECEIPT = datetime(2026, 10, 23, tzinfo=UTC)


def frozen_alpha(unavailable=False):
    origin = a.VALIDATION_START
    candidates = tuple(
        ridge.CandidateResult(
            alpha,
            None if unavailable else 0.1,
            ((origin, "ridge_numerical_failure"),) if unavailable else (),
        )
        for alpha in ridge.ALPHAS
    )
    return ridge.AlphaSelection(
        (origin,), candidates, None if unavailable else 0.01, START
    )


def metadata():
    # These are syntactically valid fictional identities, not file hashes.
    return reporting.Provenance(
        *(str(i) * 64 for i in range(1, 10)),
        (("python", "synthetic-fixture"),),
        "qnt-002b-v1",
        "synthetic-fixture",
    )


def fixture(history=721, hours=3, start=START, future=0):
    origins = tuple(start + i * H for i in range(-history, hours + future))
    features, outcomes = [], []
    for i, origin in enumerate(origins):
        features.append(
            runner.SyntheticFeatures(
                origin, tuple(((i % (j + 2)) - 1) / 100 for j in range(7))
            )
        )
        # Arbitrary returns invented here; no real observations or files.
        outcomes.append(a.Outcome(origin, ((i % 7) - 3) / 1000, True))
    return runner.SyntheticFixture(True, tuple(features), tuple(outcomes))


def run(data=None, *, hours=3, start=START, selection="frozen", period="test"):
    if data is None:
        data = fixture(hours=hours, start=start)
    selected = (
        frozen_alpha(selection == "unavailable") if selection is not None else None
    )
    return runner.run_synthetic(
        data,
        a.OriginUniverse(period, start, start + hours * H),
        provenance=metadata(),
        evidence=reporting.ValidationEvidence(True, True, True, True, True),
        evaluated_at_utc=RECEIPT,
        alpha_selection=selected,
    )


def forecasts(result, model, sample="a_primary"):
    return tuple(
        f for f in result.forecasts if (f.model_id, f.sample_policy) == (model, sample)
    )


def update(result, model, event=START, sample="a_primary"):
    return next(
        u
        for u in result.updates
        if (u.model_id, u.event, u.sample_policy) == (model, event, sample)
    )


def change_outcome(data, origin, **changes):
    return replace(
        data,
        outcomes=tuple(
            replace(o, **changes) if o.origin == origin else o for o in data.outcomes
        ),
    )


def test_successful_end_to_end_four_models_both_samples_and_determinism():
    data = fixture()
    result, repeated = run(data), run(data)
    assert result.canonical_report == repeated.canonical_report
    assert result.canonical_report == reporting.canonical_json(result.report)
    assert len(result.forecasts) == 3 * 4 * 2
    assert all(f.status == "emitted" for f in result.forecasts)
    assert all(f.prediction == 0.0 for f in forecasts(result, "zero_return"))
    assert len(result.comparisons) == 14
    assert len(result.report["results"]) == 36
    assert all(
        row["evaluation_status"] == "complete" for row in result.report["results"]
    )
    assert all(
        row["point_in_time_verified"] is False for row in result.report["results"]
    )
    assert all(row["decision_eligible"] is False for row in result.report["results"])
    expected_mean = math.fsum(o.target for o in data.outcomes if o.origin < START) / 721
    assert forecasts(result, "expanding_mean")[0].prediction == expected_mean


def test_exact_label_admission_same_clock_and_no_current_outcome_admission():
    result = run()
    assert len(result.admissions[0].label_origins) == 721
    assert result.admissions[0].label_origins[-1] == START - H
    assert result.admissions[1].label_origins == (START,)
    assert result.admissions[-1].event == START + 3 * H
    assert result.admissions[-1].label_origins == (START + 2 * H,)
    for admitted in result.admissions:
        assert all(h + H <= admitted.event for h in admitted.label_origins)
    for u in result.updates:
        assert all(h + H <= u.event for h in u.label_origins)
        assert u.max_outcome_close is None or u.max_outcome_close <= u.event
    assert len(update(result, "ar_1").label_origins) == 720
    assert len(update(result, "ridge_7").label_origins) == 721


@pytest.mark.parametrize("offset", [0, 1, 2])
def test_own_or_future_target_cannot_change_forecasts_through_its_origin(offset):
    data = fixture(hours=4)
    changed = change_outcome(data, START + offset * H, target=0.5)
    original, altered = run(data, hours=4), run(changed, hours=4)
    assert tuple(
        f for f in original.forecasts if f.origin <= START + offset * H
    ) == tuple(f for f in altered.forecasts if f.origin <= START + offset * H)
    # The newly completed label really is admitted, not permanently ignored.
    assert forecasts(original, "expanding_mean")[offset + 1].prediction != (
        forecasts(altered, "expanding_mean")[offset + 1].prediction
    )


def test_future_anomaly_changes_only_post_closure_sensitivity_history():
    data = fixture(hours=4)
    changed = change_outcome(
        data, START + H, target_manifest_anomaly=True, anomaly_evidence_status="partial"
    )
    original, altered = run(data, hours=4), run(changed, hours=4)
    assert original.forecasts[:16] == altered.forecasts[:16]
    assert forecasts(original, "ar_1", "a_sensitivity")[2].status == "emitted"
    assert (
        forecasts(altered, "ar_1", "a_sensitivity")[2].reasons[0]
        == "ar_lag_manifest_anomaly"
    )
    assert forecasts(original, "expanding_mean") == forecasts(altered, "expanding_mean")
    assert (
        START + H
        not in update(
            altered, "expanding_mean", START + 2 * H, "a_sensitivity"
        ).label_origins
    )


def test_forecast_calls_receive_no_outcome_fields_or_unclosed_history(monkeypatch):
    original_mean = baselines.prepare_mean_history
    original_ridge = ridge.prepare_history
    original_ar_predict = baselines.predict_ar
    calls = []

    def mean(labels, *, origin, sample):
        assert all(label.label_origin + H <= origin for label in labels)
        calls.append(("mean", origin, tuple(label.label_origin for label in labels)))
        return original_mean(labels, origin=origin, sample=sample)

    def ridge_history(rows, *, origin, sample):
        assert all(row.label_origin + H <= origin for row in rows)
        calls.append(("ridge", origin, tuple(row.label_origin for row in rows)))
        return original_ridge(rows, origin=origin, sample=sample)

    def ar_predict(fields, fit, lag):
        assert set(fields) == {"feature_open_t", "forecast_origin_utc"}
        assert lag.origin == fields["forecast_origin_utc"]
        return original_ar_predict(fields, fit, lag)

    monkeypatch.setattr(baselines, "prepare_mean_history", mean)
    monkeypatch.setattr(ridge, "prepare_history", ridge_history)
    monkeypatch.setattr(baselines, "predict_ar", ar_predict)
    run()
    assert calls and {c[0] for c in calls} == {"mean", "ridge"}


def test_actual_outcome_attributes_are_not_read_until_closure(monkeypatch):
    class GuardedOutcome(a.Outcome):
        active = False
        clock = None
        reads = []

        def __getattribute__(self, name):
            if GuardedOutcome.active and name in {
                "target",
                "target_valid",
                "target_manifest_anomaly",
                "quality",
                "invalid_reasons",
                "anomaly_evidence_status",
            }:
                origin = object.__getattribute__(self, "origin")
                assert origin + H <= GuardedOutcome.clock
                GuardedOutcome.reads.append((origin, name, GuardedOutcome.clock))
            return object.__getattribute__(self, name)

    data = fixture(history=2, future=2)
    guarded = tuple(GuardedOutcome(**vars(o)) for o in data.outcomes)
    data = replace(data, outcomes=guarded)
    real_completed = p.label_completed

    def completed(h, origin):
        GuardedOutcome.clock = origin
        return real_completed(h, origin)

    monkeypatch.setattr(p, "label_completed", completed)
    GuardedOutcome.active = True
    result = run(data)
    assert GuardedOutcome.reads
    assert all(h < START + 3 * H for h, _, _ in GuardedOutcome.reads)
    assert len(result.forecasts) == 24


def test_missing_and_invalid_labels_never_make_cross_gap_ar_pairs():
    data = fixture()
    missing = START - 4 * H
    invalid = START - 8 * H
    data = replace(
        data, outcomes=tuple(o for o in data.outcomes if o.origin != missing)
    )
    data = change_outcome(
        data,
        invalid,
        target=None,
        target_valid=False,
        invalid_reasons=("next_missing",),
    )
    result = run(data)
    pair_origins = update(result, "ar_1").label_origins
    assert len(pair_origins) == 716
    assert not {missing, missing + H, invalid, invalid + H} & set(pair_origins)
    assert missing not in result.admissions[0].label_origins
    assert forecasts(result, "ar_1")[0].reasons == ("insufficient_training_history",)


def test_ridge_complete_rows_and_sample_masks_are_applied_before_scaling():
    data = fixture()
    bad_feature, feature_anomaly, target_anomaly = (START - i * H for i in (5, 9, 13))
    data = replace(
        data,
        features=tuple(
            replace(f, values=(None, *f.values[1:]))
            if f.origin == bad_feature
            else replace(f, anomaly_involved_features=("momentum_24h",))
            if f.origin == feature_anomaly
            else f
            for f in data.features
        ),
    )
    data = change_outcome(data, target_anomaly, target_manifest_anomaly=True)
    result = run(data)
    primary = update(result, "ridge_7")
    sensitive = update(result, "ridge_7", sample="a_sensitivity")
    assert (
        len(primary.label_origins) == 720 and bad_feature not in primary.label_origins
    )
    assert {feature_anomaly, target_anomaly} <= set(primary.label_origins)
    assert len(sensitive.label_origins) == 718
    assert not {bad_feature, feature_anomaly, target_anomaly} & set(
        sensitive.label_origins
    )
    assert primary.fit.history_count == 720
    by_origin = {f.origin: f for f in data.features}
    expected_mean = (
        math.fsum(by_origin[h].values[0] for h in primary.label_origins) / 720
    )
    assert primary.fit.scaler.means[0] == expected_mean
    assert sensitive.fit.reason == "insufficient_training_history"


def test_missing_current_features_abstain_ridge_without_fabricating_rows():
    data = fixture()
    data = replace(data, features=tuple(f for f in data.features if f.origin != START))
    result = run(data)
    assert START not in {f.origin for f in data.features}
    assert forecasts(result, "ridge_7")[0].reasons[0] == "feature_null__log_return_1h"
    assert forecasts(result, "zero_return")[0].status == "emitted"
    b = next(
        b
        for b in result.accountings
        if b.model_id == "ridge_7" and b.sample_policy == "a_primary"
    )
    assert b.scores[0].outcome.quality.feature_complete is False


def test_unscorable_target_never_retracts_an_emitted_forecast():
    data = change_outcome(
        fixture(),
        START,
        target=None,
        target_valid=False,
        invalid_reasons=("next_missing",),
    )
    result = run(data)
    assert all(f.status == "emitted" for f in result.forecasts[:8])
    for b in result.accountings:
        assert b.scores[0].status == "emitted_but_not_scored"
        assert b.scores[0].forecast.prediction is not None
        assert b.counts["emitted_but_not_scored"] >= 1


def test_cold_start_threshold_reached_midday_waits_for_midnight_refit():
    result = run(fixture(history=719, hours=25), hours=25)
    assert forecasts(result, "expanding_mean")[0].status == "abstained"
    assert forecasts(result, "expanding_mean")[1].status == "emitted"
    assert len(update(result, "expanding_mean", START + H).label_origins) == 720
    for model in ("ar_1", "ridge_7"):
        path = forecasts(result, model)
        assert all(f.status == "abstained" for f in path[:24])
        assert path[24].status == "emitted"
        assert tuple(
            u.event
            for u in result.updates
            if u.model_id == model and u.sample_policy == "a_primary"
        ) == (START, START + 24 * H)


def test_nonmidnight_start_never_invents_an_unscheduled_fit():
    start = START + H
    result = run(fixture(hours=24, start=start), start=start, hours=24)
    for model in ("ar_1", "ridge_7"):
        assert all(f.status == "abstained" for f in forecasts(result, model)[:23])
        assert forecasts(result, model)[23].status == "emitted"
        assert tuple(
            u.event
            for u in result.updates
            if u.model_id == model and u.sample_policy == "a_primary"
        ) == (START + 24 * H,)


@pytest.mark.parametrize("model", ["ar_1", "ridge_7"])
def test_failed_midnight_refit_replaces_success_and_never_uses_stale_state(
    monkeypatch, model
):
    module, name = (baselines, "fit_ar") if model == "ar_1" else (ridge, "fit_ridge")
    real_fit = getattr(module, name)

    def fit(history, **kwargs):
        fitted = real_fit(history, **kwargs)
        if history.cutoff == START + 24 * H:
            changes = {
                "reason": "ar_numerical_failure"
                if model == "ar_1"
                else "ridge_numerical_failure",
                "intercept": None,
            }
            changes |= (
                {"slope": None}
                if model == "ar_1"
                else {"scaler": None, "coefficients": None}
            )
            return replace(fitted, **changes)
        return fitted

    monkeypatch.setattr(module, name, fit)
    result = run(fixture(hours=26), hours=26)
    path = forecasts(result, model)
    assert all(f.status == "emitted" for f in path[:24])
    expected = "ar_numerical_failure" if model == "ar_1" else "ridge_numerical_failure"
    assert all(f.reasons == (expected,) for f in path[24:])
    assert update(result, model).fit.reason is None
    assert update(result, model, START + 24 * H).fit.reason == expected


def test_degenerate_ar_fit_failure_is_actual_model_behavior():
    data = replace(
        fixture(), outcomes=tuple(replace(o, target=0.001) for o in fixture().outcomes)
    )
    result = run(data)
    assert update(result, "ar_1").fit.reason == "ar_ill_conditioned_lag"
    assert all(
        f.reasons == ("ar_ill_conditioned_lag",) for f in forecasts(result, "ar_1")
    )


@pytest.mark.parametrize("selected", [None, "unavailable", "frozen"])
def test_frozen_alpha_and_blocked_comparison_contract(selected, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("runner must not tune alpha")

    monkeypatch.setattr(ridge, "select_alpha", forbidden)
    result = run(selection=selected)
    for u in result.updates:
        if u.model_id == "ridge_7":
            assert u.selected_alpha == (0.01 if selected == "frozen" else None)
    comparisons = [
        c
        for c in result.report["comparison_sets"]
        if c["comparison_scope"] == "feature_common"
    ]
    expected = "complete" if selected == "frozen" else "blocked"
    assert all(c["evaluation_status"] == expected for c in comparisons)
    for row in result.report["results"]:
        if row["comparison_scope"] == "feature_common":
            assert row["evaluation_status"] == expected
            assert (row["rmse"] is None) == (expected == "blocked")


def test_frozen_alpha_is_unchanged_across_multiple_test_refits():
    result = run(fixture(hours=25), hours=25)
    fits = [u for u in result.updates if u.model_id == "ridge_7"]
    assert len(fits) == 4
    assert all(u.selected_alpha == u.fit.alpha == 0.01 for u in fits)
    assert result.report["alpha_selection"]["selected_alpha"] == 0.01


def test_all_comparison_intersections_and_conservation_are_exact():
    data = change_outcome(fixture(), START + H, target_manifest_anomaly=True)
    result = run(data)
    index = {(b.model_id, b.sample_policy): b for b in result.accountings}
    for b in result.accountings:
        p.validate_counts(**b.counts)
    for c in result.comparisons:
        expected = set.intersection(
            *(set(index[k].scored_origins) for k in c.participants)
        )
        assert c.origins == tuple(sorted(expected))
        assert c.sha256 == reporting.timestamp_digest(c.origins)
    # The target at START+1h is sensitivity-excluded; at START+2h that
    # completed label is also the unavailable sensitivity AR lag.
    assert all(
        c.origins == (START,)
        for c in result.comparisons
        if c.scope == "paired_sensitivity_common"
    )


def test_empty_fixture_and_cold_start_empty_intersections():
    empty = run(fixture(history=0, hours=0), hours=0, selection=None)
    assert empty.forecasts == empty.admissions == empty.updates == ()
    assert all(b.coverage is None for b in empty.accountings)
    cold = run(fixture(history=0), selection=None)
    assert all(f.status == "emitted" for f in forecasts(cold, "zero_return"))
    assert all(f.status == "abstained" for f in forecasts(cold, "ridge_7"))
    assert all(not c.origins for c in cold.comparisons if c.scope == "feature_common")


@pytest.mark.parametrize(
    "period,start",
    [
        ("training_history", datetime(2022, 1, 1, tzinfo=UTC)),
        ("validation", datetime(2024, 6, 1, tzinfo=UTC)),
    ],
)
def test_training_accounting_and_validation_diagnostics_only(
    period, start, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("no selected-alpha Ridge fit/prediction outside Test")

    monkeypatch.setattr(ridge, "fit_ridge", forbidden)
    monkeypatch.setattr(ridge, "predict", forbidden)
    # Sufficient finite seed rows and a supplied valid frozen selection must
    # never cause training/validation replay. Its true availability is future
    # under the approved contract; the independent period gate is tested below.
    data = fixture(history=721, start=start)
    assert start.hour == 0  # Exercise a real scheduled refit boundary.
    result = run(data, period=period, start=start)
    assert len(result.accountings) == 8
    assert not result.comparisons and not result.report["results"]
    assert all(f.status == "abstained" for f in forecasts(result, "ridge_7"))
    assert (
        result.report["alpha_selection"]["interpretation"]
        == "a_primary_2024_candidate_tuning_only"
    )
    ridge_updates = tuple(u for u in result.updates if u.model_id == "ridge_7")
    assert len(ridge_updates) == 2  # Both samples explicitly skipped at midnight.
    assert all(
        u.fit is None and u.reason == "ridge_replay_not_authorized"
        for u in ridge_updates
    )


@pytest.mark.parametrize("period", ["training_history", "validation"])
def test_non_test_period_gate_rejects_even_apparently_available_selection(period):
    # Probe the gate independently: the selection is valid and clock-available,
    # but those facts cannot authorize a non-Test replay. This is not an
    # out-of-split evaluation or a change to approved chronological boundaries.
    selection = frozen_alpha()
    assert selection.analysis_as_of <= START
    assert selection.selected_alpha == 0.01
    assert runner._ridge_selection_available("test", START, selection)
    assert not runner._ridge_selection_available(period, START, selection)


@pytest.mark.parametrize(
    "period,start",
    [
        ("training_history", datetime(2022, 1, 1, tzinfo=UTC)),
        ("validation", datetime(2024, 6, 1, tzinfo=UTC)),
        ("test", START),
    ],
)
def test_empty_universe_with_seed_history_has_no_execution_events(
    period, start, monkeypatch
):
    data = fixture(history=721, hours=0, start=start)
    assert len(data.outcomes) == len(data.features) == 721

    def forbidden(*args, **kwargs):
        raise AssertionError("empty universe must not admit, fit, emit or score")

    monkeypatch.setattr(p, "label_completed", forbidden)
    monkeypatch.setattr(baselines, "zero_return", forbidden)
    monkeypatch.setattr(baselines, "predict_mean", forbidden)
    monkeypatch.setattr(baselines, "fit_ar", forbidden)
    monkeypatch.setattr(baselines, "predict_ar", forbidden)
    monkeypatch.setattr(ridge, "fit_ridge", forbidden)
    monkeypatch.setattr(ridge, "predict", forbidden)
    monkeypatch.setattr(a.Score, "__post_init__", forbidden)
    result = run(data, hours=0, period=period, start=start)
    assert result.admissions == result.updates == result.forecasts == ()
    assert len(result.accountings) == 8
    assert all(b.scores == () and b.coverage is None for b in result.accountings)
    assert all(all(n == 0 for n in b.counts.values()) for b in result.accountings)
    assert all(c.origins == () for c in result.comparisons)
    assert all(row["rmse"] is None for row in result.report["results"])
    reporting.validate_report(result.report, inputs=result.report_inputs)


def test_no_dataset_file_or_network_io_and_no_mutation(monkeypatch):
    import pathlib
    import socket

    data = fixture(history=0)
    before = repr(data)

    def forbidden(*args, **kwargs):
        raise AssertionError("I/O forbidden")

    monkeypatch.setattr(pathlib.Path, "open", forbidden)
    monkeypatch.setattr(pathlib.Path, "read_bytes", forbidden)
    monkeypatch.setattr(pathlib.Path, "write_bytes", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    import polars as pl

    monkeypatch.setattr(pl, "read_parquet", forbidden)
    monkeypatch.setattr(pl, "scan_parquet", forbidden)
    result = run(data)
    assert repr(data) == before
    assert len(result.forecasts) == 24
    assert result.report["provenance"]["artifact_bytes_verified"] is False


def test_invalid_fixture_and_boundary_inputs_fail_closed():
    data = fixture()
    with pytest.raises(ValueError, match="synthetic=True"):
        replace(data, synthetic=False)
    with pytest.raises(ValueError, match="sorted and unique"):
        replace(data, outcomes=(*data.outcomes, data.outcomes[-1]))
    with pytest.raises(ValueError, match="explicit outcome"):
        run(
            replace(data, outcomes=tuple(o for o in data.outcomes if o.origin != START))
        )
    with pytest.raises(ValueError, match="boundary"):
        runner.run_synthetic(
            data,
            a.OriginUniverse("test", START, START + H),
            provenance=metadata(),
            evidence=reporting.ValidationEvidence(True, True, True, True, True),
            evaluated_at_utc=RECEIPT,
            alpha_selection=replace(frozen_alpha(), analysis_as_of=START + H),
        )
    with pytest.raises(ValueError, match="seven-feature"):
        runner.SyntheticFeatures(START, (1.0,))
    with pytest.raises(ValueError, match="UTC"):
        runner.SyntheticFeatures(START.replace(tzinfo=None), (1.0,) * 7)


@pytest.mark.parametrize("selection", [None, "frozen"])
def test_ridge_null_feature_priority_before_anomaly_and_cold_start(selection):
    data = fixture(history=0)
    data = replace(
        data,
        features=tuple(
            replace(
                f,
                values=(None, *f.values[1:]),
                anomaly_involved_features=("momentum_24h",),
            )
            if f.origin == START
            else f
            for f in data.features
        ),
    )
    result = run(data, selection=selection)
    prediction = forecasts(result, "ridge_7", "a_sensitivity")[0]
    assert prediction.reasons == (
        "feature_null__log_return_1h",
        "feature_manifest_anomaly__momentum_24h",
        "insufficient_training_history",
    )
    assert forecasts(result, "ridge_7")[0].reasons == (
        "feature_null__log_return_1h",
        "insufficient_training_history",
    )


def test_no_missing_lag_fill_and_priority_over_failed_fit():
    data = fixture(history=0)
    result = run(data)
    first = forecasts(result, "ar_1")[0]
    assert first.reasons == (
        "ar_lag_missing_or_invalid",
        "insufficient_training_history",
    )
    assert forecasts(result, "ar_1")[1].reasons == ("insufficient_training_history",)


def test_appended_future_fixture_rows_leave_entire_existing_report_unchanged():
    short = fixture()
    extra = fixture(future=3)
    assert run(short).canonical_report == run(extra).canonical_report


def test_ar_pair_mapping_is_exact_and_uses_existing_solver(monkeypatch):
    received = []
    real_fit = baselines.fit_ar

    def fit(history):
        received.append(history)
        return real_fit(history)

    monkeypatch.setattr(baselines, "fit_ar", fit)
    data = fixture()
    result = run(data)
    by_origin = {o.origin: o for o in data.outcomes}
    assert len(received) == 2
    for h in received:
        assert h.cutoff == START and len(h.pairs) == 720
        assert h.pairs[0].feature_open == START - 721 * H
        assert h.pairs[-1].feature_open == START - 2 * H
        for pair in h.pairs:
            label_origin = pair.feature_open + H
            assert pair.lag == by_origin[label_origin - H].target
            assert pair.target == by_origin[label_origin].target
            assert label_origin + H <= h.cutoff
    fitted = update(result, "ar_1").fit
    expected = fitted.intercept + fitted.slope * by_origin[START - H].target
    assert forecasts(result, "ar_1")[0].prediction == expected


def test_future_feature_values_do_not_enter_earlier_scaler_or_forecasts():
    data = fixture()
    altered = replace(
        data,
        features=tuple(
            replace(f, values=(1e6,) * 7) if f.origin == START + 2 * H else f
            for f in data.features
        ),
    )
    before, after = run(data), run(altered)
    assert update(before, "ridge_7").fit == update(after, "ridge_7").fit
    assert tuple(f for f in before.forecasts if f.origin < START + 2 * H) == tuple(
        f for f in after.forecasts if f.origin < START + 2 * H
    )


def test_current_forecast_feature_time_alignment_is_candle_open_not_outcome():
    row = runner.SyntheticFeatures(START, (1.0,) * 7)
    fields = row.forecast_fields()
    assert fields["feature_open_t"] == START - H
    assert fields["forecast_origin_utc"] == START
    assert not any(k.startswith("target") or k.startswith("next_") for k in fields)


def test_unexpected_fit_error_aborts_instead_of_reusing_or_publishing(monkeypatch):
    def failed(history):
        raise RuntimeError("synthetic interrupted fit")

    monkeypatch.setattr(baselines, "fit_ar", failed)
    with pytest.raises(RuntimeError, match="interrupted fit"):
        run()


@pytest.mark.parametrize("value", [True, "target", {}, 10**1000])
def test_structurally_invalid_feature_scalar_fails_closed(value):
    with pytest.raises(ValueError, match="feature"):
        runner.SyntheticFeatures(START, (value,) * 7)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_incomplete_nonfinite_vector_abstains_without_imputation(value):
    data = fixture()
    data = replace(
        data,
        features=tuple(
            replace(f, values=(value, *f.values[1:])) if f.origin == START else f
            for f in data.features
        ),
    )
    result = run(data)
    for sample in a.SAMPLES:
        first = forecasts(result, "ridge_7", sample)[0]
        assert first.status == "abstained"
        assert first.reasons[0] == "feature_null__log_return_1h"
