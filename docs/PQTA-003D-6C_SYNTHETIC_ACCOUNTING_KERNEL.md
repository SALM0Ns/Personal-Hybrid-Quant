# PQTA-003D-6C — Synthetic Native Accounting Kernel

**Status: PQTA-003D-6C — IMPLEMENTED, AWAITING ARCHITECT REVIEW**

Baseline: `b4eb3157e992ac1d60f1e0605c531cda42798fd9`.
Stage C implements the approved [5G accounting contract](PQTA-003D-5G_NATIVE_SCORING_ACCOUNTING_IMPLEMENTATION_CONTRACT.md)
using [Stage A records and validators](PQTA-003D-6A_NATIVE_TYPES_VALIDATION.md)
and supplied [Stage B classifications](PQTA-003D-6B_SYNTHETIC_SCORING_KERNEL.md).
Protocol `qnt-003d-design-v1`, dataset contract
`pqta-003b-origin-ledger-v1`, model/sample rules and all reason priorities remain
unchanged.

## Public API and output

[`native_accounting.py`](../src/quant/research/native_accounting.py) exports:

```python
def reconcile_native_accounting(
    scope: HistoricalScopeSpec,
    *,
    model_id: str,
    sample_policy: str,
    scoring_build_id: str,
    forecasts: tuple[HistoricalForecast, ...],
    score_classifications: tuple[ScoreClassification, ...],
    policy_version: str = POLICY_VERSION,
) -> AccountingReconciliation: ...
```

The result is the existing immutable `AccountingReconciliation` schema:
scoring specification/build identities, declared scope, model/sample, exact
ordered forecast IDs/classification keys, immutable counts/reasons mapping,
sorted scored origins and their digest, fixed-false historical verification,
and deterministic `reconciliation_id`. No output schema field or canonical
serialization contract changes.

The only Stage A addition is fixed-false read-only authority properties on
`AccountingReconciliation`, matching Stage C's explicit restrictions. Existing
Stage A validation and Stage B classification behavior are unchanged.

## Exact universe and identities

The scope must be an already validated `HistoricalScopeSpec` in
`synthetic_fixture` mode with populated, recomputable logical identities.
Model/sample must belong to that scope, and the expected scoring-build identity
must match every forecast. Inputs are immutable tuples; their ordering is not
significant. Each forecast must retain its exact recomputable ID, full
source/origin identity, specification, selected model/sample and null execution
instance. Historical-mode labels are rejected.

The kernel rejects duplicates before indexing records. Forecast-origin
identities must equal the complete declared `scope.origins` set. Classification
parent identities must equal the complete supplied forecast-ID set, with exact
Stage A parent binding. Equal counts, generated hourly timestamps or partial
subsets cannot replace these identity checks. Extra records are never filtered.
Audit-only identities remain in the scope's separate collection and cannot
enter forecasts, classifications, denominators or scored digests.

Only after those checks does the kernel normalize forecasts/classifications to
the declared canonical scope order. It creates no forecasts, classifications,
abstentions or outcomes. Invalid, anomalous and unscorable origins remain in
the declared universe whenever supplied records are valid and complete.

## Counts, reasons and conservation

All summaries derive from the supplied validated records:

| Summary | Derivation |
| --- | --- |
| Origin count | Number of declared evaluation origins |
| Emitted/abstained counts | Immutable forecast statuses |
| Three score-status counts | Supplied final classification statuses |
| Exclusive abstention reasons | First ordered forecast abstention reason for each abstained record |
| Exclusive primary score reasons | Primary reason for each unscored classification |
| Overlapping diagnostics | Every classification diagnostic occurrence |
| Forecast coverage | Emitted count / full origin count |
| Scored-origin set | Exactly the origins classified `scored`, in chronological order |
| Scored-set digest | Existing canonical UTC timestamp-set helper |

Reason-count tuples follow `forecast_reason_order`, `SCORE_PRIORITY` and the
existing overlapping `unknown_historical_availability` diagnostic. Overlaps
never enter the exclusive primary funnel merely because they were observed.
No outcome or native anomaly token is inspected or reinterpreted; the kernel
counts already supplied classifications without changing Stage B decisions.

The returned record is verified with the existing complete-record
`validate_reconciliation` interface, including exact summary comparison and:

```text
N_origins = N_emitted + N_abstained
N_emitted = N_scored + N_emitted_but_not_scored
N_abstained = N_not_scored_no_forecast
N_origins = N_scored + sum(exclusive_primary_score_reason_counts)
N_abstained = sum(exclusive_abstention_reason_counts)
```

An empty synthetic scope accepts only empty forecast/classification tuples.
It produces zero counts, empty reason/scored sets, the canonical empty-set
digest and null coverage. A nonempty scope with absent or partial records
raises `ValueError`; no synthetic abstentions fill the missing origins.

## Determinism and authority boundary

Reordering either input tuple leaves canonical output bytes and
`reconciliation_id` unchanged. The existing canonical serializer preserves
immutable identity fields and uses no runtime clocks, randomness, environment
lookup or source paths.

All properties below are fixed false, with no constructor switches:

```text
historical_execution_verified = false
historical_completion_authenticated = false
authenticated_historical_score = false
historical_execution_completed = false
point_in_time_verified = false
decision_eligible = false
```

Synthetic source labels and digest agreement validate supplied data only. They
do not authenticate historical ledger bytes, prove that Stage B or a model ran,
verify historical publication, or authorize a historical completion wrapper.
The kernel produces no `HistoricalAccountingResult`, performance metric,
comparison/report, artifact or historical execution authority. Stages D–F,
dashboards, signals and trading remain subject to separate authorization.

## Validation commands

The [tests](../tests/test_native_accounting.py) use invented synthetic records.
Run in the existing Conda `pqta` environment:

```bash
python -m pytest -q tests/test_native_accounting.py
python -m pytest -q tests/test_historical_scoring_contract.py tests/test_native_scoring.py
python -m pytest -q
ruff check .
ruff format --check src tests web
python -m pip check
git diff --check
```
