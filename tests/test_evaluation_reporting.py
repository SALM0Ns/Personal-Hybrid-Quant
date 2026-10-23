"""In-memory synthetic evidence only; no market dataset or model execution."""

import copy
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from quant.research import evaluation_reporting as r
from quant.research import forecast_accounting as a
from quant.research.ridge_regression import ALPHAS, AlphaSelection, CandidateResult

H = timedelta(hours=1)
ORIGIN = datetime(2025, 1, 1, tzinfo=UTC)


def book(
    model="zero_return",
    sample="a_primary",
    n=3,
    abstain=(),
    invalid=(),
    anomalies=(),
    period="test",
    origin=ORIGIN,
):
    universe = a.OriginUniverse(period, origin, origin + n * H)
    scores = []
    for i, o in enumerate(universe.origins):
        f = a.Forecast(
            o,
            model,
            sample,
            None if i in abstain else 0.0,
            ("insufficient_training_history",) if i in abstain else (),
        )
        out = a.Outcome(
            o,
            None if i in invalid else 0.1,
            i not in invalid,
            ("next_missing",) if i in invalid else (),
            i in anomalies,
        )
        scores.append(a.Score(f, out, o + H))
    return a.account(universe, model, sample, scores)


def selection():
    return AlphaSelection(
        (datetime(2024, 1, 1, tzinfo=UTC),),
        tuple(CandidateResult(alpha, 0.1, ()) for alpha in ALPHAS),
        0.01,
        ORIGIN,
    )


def provenance(**kwargs):
    values = dict(
        dataset_spec_id="1" * 64,
        artifact_build_id="2" * 64,
        evaluation_spec_id="3" * 64,
        evaluation_build_id="4" * 64,
        silver_sha256="5" * 64,
        gold_sha256="6" * 64,
        manifest_sha256="7" * 64,
        origin_ledger_sha256="8" * 64,
        code_sha256="9" * 64,
        dependency_versions=(("python", "synthetic-fixture"),),
        feature_version="qnt-002b-v1",
        manifest_version="synthetic-fixture",
    )
    return r.Provenance(**(values | kwargs))


def inputs(books=None, scope="feature_common", **kwargs):
    books = tuple(books if books is not None else (book(m) for m in a.MODELS))
    comparisons = (r.comparison_set(books, scope),) if scope else ()
    values = dict(
        accountings=books,
        comparisons=comparisons,
        provenance=provenance(),
        evidence=r.ValidationEvidence(True, True, True, True, True),
        evaluated_at_utc=datetime(2026, 10, 23, tzinfo=UTC),
        alpha_selection=selection(),
    )
    return r.ReportInputs(**(values | kwargs))


def test_digest_exact_encoding_empty_and_order():
    expected = b"2025-01-01T00:00:00Z\n2025-01-01T01:00:00Z\n"
    assert (
        r.timestamp_digest((ORIGIN + H, ORIGIN)) == hashlib.sha256(expected).hexdigest()
    )
    assert r.timestamp_digest(()) == hashlib.sha256(b"").hexdigest()
    with pytest.raises(ValueError, match="duplicate"):
        r.timestamp_digest((ORIGIN, ORIGIN))
    with pytest.raises(ValueError):
        r.timestamp_digest((ORIGIN.replace(tzinfo=None),))


@pytest.mark.parametrize(
    "prediction,target,accuracy",
    [
        (0.0, 0.0, 1.0),
        (-0.0, 0.0, 1.0),
        (0.0, 0.1, 0.0),
        (0.0, -0.1, 0.0),
        (0.1, 0.0, 0.0),
        (-0.1, 0.0, 0.0),
        (0.1, 0.2, 1.0),
        (-0.1, -0.2, 1.0),
        (0.1, -0.1, 0.0),
    ],
)
def test_exact_zero_sign_convention(prediction, target, accuracy):
    f = a.Forecast(ORIGIN, "expanding_mean", "a_primary", prediction)
    s = a.Score(f, a.Outcome(ORIGIN, target, True), ORIGIN + H)
    b = a.account(
        a.OriginUniverse("test", ORIGIN, ORIGIN + H),
        "expanding_mean",
        "a_primary",
        (s,),
    )
    m = r.metrics(b)
    assert m.directional_accuracy == accuracy
    assert m.rmse == pytest.approx(abs(prediction - target))


def test_known_metrics_and_empty_set():
    b = book()
    scores = tuple(
        replace(s, outcome=replace(s.outcome, target=y))
        for s, y in zip(b.scores, (0.0, 3.0, 4.0), strict=True)
    )
    b = replace(b, scores=scores)
    result = r.metrics(b)
    assert result.rmse == pytest.approx((25 / 3) ** 0.5)
    assert result.mae == 7 / 3 and result.directional_accuracy == 1 / 3
    assert r.metrics(b, ()) == r.Metrics(0, None, None, None)
    assert r.metrics(b, reversed(b.scored_origins)) == result


def test_metric_set_cannot_silently_drop_or_duplicate():
    b = book(invalid=(1,))
    for origins in ((ORIGIN + H,), (ORIGIN, ORIGIN), (ORIGIN + 10 * H,)):
        with pytest.raises(ValueError):
            r.metrics(b, origins)


def test_metric_numerical_failure_is_explicit():
    f = a.Forecast(ORIGIN, "expanding_mean", "a_primary", 1.7e308)
    s = a.Score(f, a.Outcome(ORIGIN, -1.7e308, True), ORIGIN + H)
    b = a.account(
        a.OriginUniverse("test", ORIGIN, ORIGIN + H),
        "expanding_mean",
        "a_primary",
        (s,),
    )
    with pytest.raises(ValueError):
        r.metrics(b)


@pytest.mark.parametrize(
    "scope,models",
    [
        ("method_own", ("zero_return",)),
        ("baseline_common", a.MODELS[:3]),
        ("feature_common", a.MODELS),
    ],
)
def test_common_sets_exact_intersection_and_coverage_not_redefined(scope, models):
    books = tuple(book(m, abstain=(1,) if m != "zero_return" else ()) for m in models)
    c = r.comparison_set(books, scope)
    assert c.origins == (
        (ORIGIN, ORIGIN + H, ORIGIN + 2 * H)
        if scope == "method_own"
        else (ORIGIN, ORIGIN + 2 * H)
    )
    report = r.build_report(inputs(books, scope))
    r.validate_report(report, inputs=inputs(books, scope))
    assert report["results"][0]["forecast_coverage"] == 1.0
    assert all(row["metric_count"] == len(c.origins) for row in report["results"])


@pytest.mark.parametrize(
    "parent,models",
    [
        ("baseline_common", a.MODELS[:3]),
        ("feature_common", a.MODELS),
    ],
)
def test_paired_sensitivity_intersection(parent, models):
    books = tuple(book(m, s, anomalies=(1,)) for s in a.SAMPLES for m in models)
    c = r.comparison_set(books, "paired_sensitivity_common", parent_scope=parent)
    assert c.origins == (ORIGIN, ORIGIN + 2 * H)
    i = inputs(books, scope=None, comparisons=(c,))
    report = r.build_report(i)
    assert len(report["results"]) == 2 * len(models)
    assert len({row["timestamp_set_sha256"] for row in report["results"]}) == 1


@pytest.mark.parametrize(
    "scope,models,parent",
    [
        ("unknown", a.MODELS, None),
        ("feature_common", a.MODELS[:3], None),
        ("baseline_common", a.MODELS, None),
        ("method_own", a.MODELS, None),
        ("paired_sensitivity_common", a.MODELS, None),
        ("paired_sensitivity_common", a.MODELS, "feature_common"),
        ("method_own", ("zero_return",), "baseline_common"),
    ],
)
def test_wrong_participants_scopes_parent_rejected(scope, models, parent):
    with pytest.raises(ValueError):
        r.comparison_set(tuple(book(m) for m in models), scope, parent_scope=parent)


def test_duplicate_books_mixed_windows_and_manual_set_tampering_rejected():
    b = book()
    with pytest.raises(ValueError):
        r.comparison_set((b, b), "method_own")
    with pytest.raises(ValueError):
        r.comparison_set((b, book("ar_1", n=2)), "baseline_common")
    i = inputs()
    c = replace(i.comparisons[0], origins=(ORIGIN,))
    with pytest.raises(ValueError, match="exact scored"):
        r.build_report(replace(i, comparisons=(c,)))


def test_determinism_and_future_prefix_invariance():
    i = inputs()
    assert r.canonical_json(r.build_report(i)) == r.canonical_json(r.build_report(i))
    short, longer = book(), book(n=4)
    assert r.metrics(short) == r.metrics(longer, short.scored_origins)
    assert short.scores == longer.scores[:3]


@pytest.mark.parametrize(
    "kind,status",
    [
        ("empty", "blocked"),
        ("abstained", "no_forecasts"),
        ("invalid", "no_scored_forecasts"),
        ("normal", "complete"),
    ],
)
def test_result_status_and_nullability(kind, status):
    options = {
        "empty": {"n": 0},
        "abstained": {"abstain": (0, 1, 2)},
        "invalid": {"invalid": (0, 1, 2)},
        "normal": {},
    }[kind]
    i = inputs((book("expanding_mean", **options),), "method_own")
    report = r.build_report(i)
    r.validate_report(report, inputs=i)
    row = report["results"][0]
    assert row["evaluation_status"] == status
    assert (row["rmse"] is None) == (kind != "normal")
    assert row["forecast_coverage"] == (
        None if kind == "empty" else 0.0 if kind == "abstained" else 1.0
    )


def test_empty_common_set_retains_own_emission_coverage():
    books = tuple(
        book(m, abstain=(0, 1, 2) if m == "ar_1" else ()) for m in a.MODELS[:3]
    )
    report = r.build_report(inputs(books, "baseline_common"))
    zero = report["results"][0]
    assert zero["metric_count"] == 0 and zero["own_scored_count"] == 3
    assert zero["forecast_coverage"] == 1.0
    assert zero["status_reasons"] == ["no_common_timestamps"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"dataset_spec_id": "X" * 64},
        {"artifact_build_id": "4" * 64},
        {"protocol_version": "wrong"},
        {"dataset_contract_version": "wrong"},
        {"dependency_versions": (("python", "a"), ("python", "b"))},
        {"feature_version": ""},
    ],
)
def test_provenance_identity_and_version_validation(mutation):
    with pytest.raises(ValueError):
        provenance(**mutation)


@pytest.mark.parametrize(
    "field,value",
    [
        ("forecast_count", 0),
        ("forecast_count", True),
        ("origin_count", 500),
        ("metric_count", 1),
        ("rmse", None),
        ("rmse", float("nan")),
        ("directional_accuracy", 2),
        ("forecast_coverage", 0.1),
        ("model_id", "unknown"),
        ("sample_policy", "lane_b"),
        ("timestamp_set_sha256", "0" * 64),
        ("evaluation_status", "pending"),
        ("evaluation_status", "failed"),
        ("evaluation_status", "not_run"),
        ("point_in_time_verified", True),
        ("decision_eligible", True),
        ("artifact_build_id", "4" * 64),
        ("dataset_spec_id", "0" * 64),
        ("protocol_version", "wrong"),
        ("selected_alpha", 100),
        ("abstention_reasons", {"next_missing": 3}),
        ("status_reasons", ["invented"]),
        ("extra", "not allowed"),
    ],
)
def test_strict_schema_rejects_tampered_fields(field, value):
    i = inputs()
    report = r.build_report(i)
    report["results"][0][field] = value
    with pytest.raises(ValueError):
        r.validate_report(report, inputs=i)


def test_envelope_descriptors_duplicates_and_json_validation():
    i = inputs()
    base = r.build_report(i)
    assert r.validate_report_json(r.canonical_json(base).decode(), inputs=i) == base
    mutations = []
    changed = copy.deepcopy(base)
    changed["schema_version"] = "unknown"
    mutations.append(changed)
    changed = copy.deepcopy(base)
    changed["results"].append(changed["results"][0])
    mutations.append(changed)
    changed = copy.deepcopy(base)
    changed["comparison_sets"][0]["participants"].pop()
    mutations.append(changed)
    changed = copy.deepcopy(base)
    changed["comparison_sets"][0]["timestamp_set_sha256"] = "a" * 64
    mutations.append(changed)
    changed = copy.deepcopy(base)
    changed["provenance"]["silver_sha256"] = "a" * 64
    mutations.append(changed)
    changed = copy.deepcopy(base)
    changed["results"].pop()
    mutations.append(changed)
    for report in mutations:
        with pytest.raises(ValueError):
            r.validate_report(report, inputs=i)
    with pytest.raises(ValueError, match="duplicate JSON"):
        r.validate_report_json('{"schema_version":"a","schema_version":"b"}', inputs=i)
    with pytest.raises(ValueError, match="nonfinite"):
        r.validate_report_json('{"rmse":NaN}', inputs=i)


def test_training_accounting_and_validation_tuning_only():
    books = (
        book(period="training_history", origin=a.TRAIN_START),
        book(period="validation", origin=a.VALIDATION_START),
    )
    i = inputs(books, scope=None)
    report = r.build_report(i)
    assert not report["results"] and not report["comparison_sets"]
    assert len(report["accounting"]) == 2
    assert "rmse" not in report["accounting"][0]
    assert (
        report["alpha_selection"]["interpretation"]
        == "a_primary_2024_candidate_tuning_only"
    )
    for b in books:
        with pytest.raises(ValueError, match="no comparison replay"):
            r.build_report(
                replace(i, comparisons=(r.comparison_set((b,), "method_own"),))
            )


def test_ridge_requires_frozen_selection_and_temporal_boundary():
    i = inputs((book("ridge_7"),), "method_own")
    blocked = r.build_report(replace(i, alpha_selection=None))
    assert blocked["results"][0]["evaluation_status"] == "blocked"
    assert blocked["results"][0]["status_reasons"] == ["frozen_alpha_unavailable"]
    with pytest.raises(ValueError, match="boundary"):
        r.build_report(
            replace(i, alpha_selection=replace(selection(), analysis_as_of=ORIGIN + H))
        )
    failed = replace(
        selection(),
        candidates=tuple(
            CandidateResult(
                alpha,
                None,
                ((datetime(2024, 1, 1, tzinfo=UTC), "ridge_numerical_failure"),),
            )
            for alpha in ALPHAS
        ),
        selected_alpha=None,
    )
    b = book("ridge_7", abstain=(0, 1, 2))
    report = r.build_report(inputs((b,), "method_own", alpha_selection=failed))
    assert report["results"][0]["status_reasons"] == ["frozen_alpha_unavailable"]


def test_evidence_gates_no_historical_mode_and_no_false_complete():
    for kwargs in (
        {"mode": "historical"},
        {"historical_execution_authorized": True},
        {"identity_checks_passed": 1},
    ):
        with pytest.raises(ValueError):
            r.ValidationEvidence(
                **(
                    dict(
                        accounting_complete=True,
                        temporal_checks_passed=True,
                        identity_checks_passed=True,
                        deterministic_rerun_passed=True,
                        human_reviewed=True,
                    )
                    | kwargs
                )
            )
    i = inputs()
    blocked_inputs = replace(
        i, evidence=replace(i.evidence, temporal_checks_passed=False)
    )
    report = r.build_report(blocked_inputs)
    r.validate_report(report, inputs=blocked_inputs)
    assert report["comparison_sets"][0]["evaluation_status"] == "blocked"
    assert all(row["evaluation_status"] == "blocked" for row in report["results"])
    assert all(row["rmse"] is None for row in report["results"])
    assert all(row["metric_count"] == 3 for row in report["results"])


def test_shared_outcome_and_missing_participant_requirements():
    i = inputs()
    changed = replace(
        i.accountings[0],
        scores=tuple(
            replace(s, outcome=replace(s.outcome, target=0.2))
            for s in i.accountings[0].scores
        ),
    )
    with pytest.raises(ValueError, match="share source outcome"):
        r.build_report(replace(i, accountings=(changed, *i.accountings[1:])))
    with pytest.raises(ValueError, match="missing comparison"):
        r.build_report(replace(i, accountings=i.accountings[:-1]))


def test_no_dataset_or_model_access(monkeypatch):
    import pathlib

    from quant.research import ridge_regression, statistical_baselines

    def forbidden(*args, **kwargs):
        raise AssertionError("historical/model execution forbidden")

    monkeypatch.setattr(pathlib.Path, "open", forbidden)
    monkeypatch.setattr(ridge_regression, "fit_ridge", forbidden)
    monkeypatch.setattr(ridge_regression, "select_alpha", forbidden)
    monkeypatch.setattr(statistical_baselines, "fit_ar", forbidden)
    i = inputs()
    r.validate_report(r.build_report(i), inputs=i)


@pytest.mark.parametrize("field", ["results", "accounting", "comparison_sets"])
def test_python_only_array_coercion_rejected(field):
    i = inputs()
    report = r.build_report(i)
    report[field] = tuple(report[field])
    with pytest.raises(ValueError, match="field type"):
        r.validate_report(report, inputs=i)


def test_processing_completion_cannot_precede_scoring_or_alpha_evidence():
    i = inputs()
    with pytest.raises(ValueError, match="outcome accounting"):
        r.build_report(replace(i, evaluated_at_utc=ORIGIN))
    empty = inputs((), scope=None)
    with pytest.raises(ValueError, match="alpha evidence"):
        r.build_report(replace(empty, evaluated_at_utc=ORIGIN - H))


def test_duplicate_comparison_and_accounting_keys_rejected():
    i = inputs()
    with pytest.raises(ValueError, match="duplicate comparison"):
        r.build_report(replace(i, comparisons=i.comparisons * 2))
    with pytest.raises(ValueError, match="duplicate.*accounting"):
        r.build_report(replace(i, accountings=i.accountings * 2))


def test_unknown_availability_visible_without_erasing_valid_research_scores():
    i = inputs()
    report = r.build_report(i)
    for result in report["results"]:
        assert result["metric_count"] == result["own_scored_count"] == 3
        assert result["all_score_exclusion_counts"][a.UNKNOWN_AVAILABILITY] == 3
        assert result["point_in_time_verified"] is False
        assert result["decision_eligible"] is False


@pytest.mark.parametrize("scope", ["baseline_common", "feature_common"])
def test_input_order_does_not_change_report_bytes(scope):
    models = a.MODELS[:3] if scope == "baseline_common" else a.MODELS
    books = tuple(book(m) for m in models)
    forward = inputs(books, scope)
    backward = inputs(tuple(reversed(books)), scope)
    assert r.canonical_json(r.build_report(forward)) == r.canonical_json(
        r.build_report(backward)
    )


def test_empty_envelope_no_metrics_or_fabricated_measurements():
    i = inputs((), scope=None, alpha_selection=None)
    report = r.build_report(i)
    r.validate_report(report, inputs=i)
    assert not report["results"] and not report["accounting"]
    assert report["alpha_selection"] is None


def unavailable_selection():
    return replace(
        selection(),
        candidates=tuple(
            CandidateResult(
                alpha, None, ((a.VALIDATION_START, "ridge_numerical_failure"),)
            )
            for alpha in ALPHAS
        ),
        selected_alpha=None,
    )


def test_explicit_status_precedence_and_reserved_execution_statuses():
    assert r.STATUS_PRECEDENCE == (
        "blocked",
        "no_forecasts",
        "no_scored_forecasts",
        "complete",
    )
    assert {"failed", "not_run"} <= set(r.STATUSES)
    assert not {"failed", "not_run", "blocked"} & a.p.FORECAST_STATUSES
    assert not {"failed", "not_run", "blocked"} & a.p.SCORE_STATUSES


@pytest.mark.parametrize("selection_kind", ["missing", "unavailable", "frozen"])
@pytest.mark.parametrize("emissions", [False, True])
@pytest.mark.parametrize("scope", ["method_own", "feature_common"])
def test_ridge_prerequisite_and_full_period_emission_status_matrix(
    selection_kind, emissions, scope
):
    chosen = {
        "missing": None,
        "unavailable": unavailable_selection(),
        "frozen": selection(),
    }[selection_kind]
    ridge = book("ridge_7", abstain=() if emissions else (0, 1, 2))
    books = (
        (ridge,) if scope == "method_own" else (*(book(m) for m in a.MODELS[:3]), ridge)
    )
    i = inputs(books, scope, alpha_selection=chosen)
    report = r.build_report(i)
    r.validate_report(report, inputs=i)
    row = next(row for row in report["results"] if row["model_id"] == "ridge_7")
    expected = (
        "blocked"
        if selection_kind != "frozen"
        else ("complete" if emissions else "no_forecasts")
    )
    assert row["evaluation_status"] == expected
    assert row["forecast_count"] == (3 if emissions else 0)
    assert row["forecast_coverage"] == (1.0 if emissions else 0.0)
    assert row["metric_count"] == (3 if emissions else 0)
    assert (row["rmse"] is not None) == (expected == "complete")
    assert report["comparison_sets"][0]["evaluation_status"] == expected
    if expected == "blocked":
        assert all(r["evaluation_status"] == "blocked" for r in report["results"])


def test_frozen_ridge_with_emissions_but_empty_common_set_is_not_no_forecasts():
    books = tuple(book(m, abstain=(0, 1, 2) if m == "ar_1" else ()) for m in a.MODELS)
    i = inputs(books)
    report = r.build_report(i)
    ridge = next(row for row in report["results"] if row["model_id"] == "ridge_7")
    assert ridge["evaluation_status"] == "no_scored_forecasts"
    assert ridge["forecast_count"] == ridge["own_scored_count"] == 3
    assert ridge["metric_count"] == 0 and ridge["rmse"] is None
    assert ridge["forecast_coverage"] == 1.0
    # The comparison as a whole includes AR's full-period no-forecast state.
    assert report["comparison_sets"][0]["evaluation_status"] == "no_forecasts"


def test_frozen_ridge_emitted_but_invalid_targets_is_no_scored_forecasts():
    i = inputs((book("ridge_7", invalid=(0, 1, 2)),), "method_own")
    row = r.build_report(i)["results"][0]
    assert row["evaluation_status"] == "no_scored_forecasts"
    assert row["forecast_count"] == row["emitted_but_not_scored_count"] == 3
    assert row["abstention_count"] == row["metric_count"] == 0
    assert row["forecast_coverage"] == 1.0 and row["rmse"] is None


def test_empty_intersection_with_each_method_emitting_is_no_scored_forecasts():
    books = (book(), book("expanding_mean", abstain=(1, 2)), book("ar_1", abstain=(0,)))
    report = r.build_report(inputs(books, "baseline_common"))
    assert report["comparison_sets"][0]["evaluation_status"] == "no_scored_forecasts"
    assert all(row["forecast_count"] > 0 for row in report["results"])
    assert all(row["metric_count"] == 0 for row in report["results"])
    assert all(
        row["evaluation_status"] == "no_scored_forecasts" for row in report["results"]
    )


def test_blocked_four_model_scope_does_not_block_independent_baseline_own_scope():
    i = inputs(alpha_selection=None)
    own = r.comparison_set((i.accountings[0],), "method_own")
    i = replace(i, comparisons=(*i.comparisons, own))
    report = r.build_report(i)
    for row in report["results"]:
        if row["comparison_scope"] == "method_own":
            assert row["evaluation_status"] == "complete"
            assert row["rmse"] == pytest.approx(0.1)
        else:
            assert row["evaluation_status"] == "blocked" and row["rmse"] is None
            assert row["forecast_count"] == row["metric_count"] == 3
    four = next(
        c
        for c in report["comparison_sets"]
        if c["comparison_scope"] == "feature_common"
    )
    assert four["evaluation_status"] == "blocked"
    assert next(p for p in four["participant_statuses"] if p["model_id"] == "ridge_7")[
        "status_reasons"
    ] == ["frozen_alpha_unavailable"]
    tampered = copy.deepcopy(report)
    next(
        c
        for c in tampered["comparison_sets"]
        if c["comparison_scope"] == "feature_common"
    )["evaluation_status"] = "complete"
    with pytest.raises(ValueError):
        r.validate_report(tampered, inputs=i)


def test_valid_digest_syntax_never_verifies_bytes_even_with_identity_gate_true():
    i = inputs(provenance=provenance(silver_sha256="f" * 64))
    report = r.build_report(i)
    assert report["validation"]["identity_checks_passed"] is True
    assert report["provenance"]["silver_sha256"] == "f" * 64
    assert report["provenance"]["artifact_bytes_verified"] is False
    with pytest.raises(ValueError, match="verified artifact bytes"):
        provenance(artifact_bytes_verified=True)
    report["provenance"]["artifact_bytes_verified"] = True
    with pytest.raises(ValueError):
        r.validate_report(report, inputs=i)


@pytest.mark.parametrize("label", ["unverified", "partial"])
def test_partial_anomaly_metadata_visible_without_inferred_details(label):
    b = book(anomalies=(0,))
    b = replace(
        b,
        scores=tuple(
            replace(s, outcome=replace(s.outcome, anomaly_evidence_status=label))
            for s in b.scores
        ),
    )
    i = inputs((b,), "method_own")
    row = r.build_report(i)["results"][0]
    assert row["quality_counts"][f"anomaly_evidence_status__{label}"] == 3
    assert row["quality_counts"]["target_manifest_anomaly"] == 1
    assert not any(k.startswith("anomaly_type__") for k in row["quality_counts"])
    assert not any(k.startswith("affected_field__") for k in row["quality_counts"])
    assert row["point_in_time_verified"] is False
