# PQTA-003D-5F — Historical Scoring and Accounting Interface Design

**Status: Approved Design — Not Implemented**

Design baseline: `ba61c21429bc5400b7b2f29d5e00da37e8efd7a4`, branch `main`.
Architect Design Review: **APPROVED WITH BOUNDED DEFERRALS** as recorded in §15.
Authority for this task: documentation finalization only. Design approval does
not authorize implementation or historical execution. Production code, tests,
scoring, accounting execution, reporting, publication and trading remain
unauthorized. The architecture is approved within its stated bounds; executable
interfaces remain **PROPOSED — NOT IMPLEMENTED**, not approved for use. Existing
4A/4B/5A–5E contracts remain unchanged constraints, not migration targets. Design
approval, implementation authorization and historical execution authorization
remain separate gates.

## 1. Executive Summary

**APPROVED — Alternative B: historical-native scoring envelopes with shared pure
accounting validators** (ADR-5F-01). Retain source-bound native anomaly records rather than
widening 4A `Quality`/`Outcome`/`Score`, fabricating a lossless 4A projection, or
relabeling historical data as synthetic. Separate forecast issuance, closed
outcome access, final score classification and full-scope reconciliation.

Reuse existing public validators, reason constants and timestamp digests only
where their input contracts are exact. The existing typed accounting/comparison
and metrics interfaces do not already accept native historical records. Their
integration requires a separately reviewed bridge; do not duplicate metric
mathematics or bypass type/evidence guards to make reuse appear implemented.

The proposed scorer classifies an **already existing** forecast against an
authenticated, theoretically closed outcome. It never fits a model, emits a
forecast, changes a sample mask or retracts an emission. Blocks and unexecuted
origins stay outside model abstention accounting. Native representation does
not establish source evidence, execution provenance, PIT or trading readiness.
Every proposed scope/result retains:

```json
{
  "execution_ready": false,
  "point_in_time_verified": false,
  "decision_eligible": false
}
```

This document contains no historical performance results or execution receipts.

## 2. Verified Existing Contracts

The following source, documentation and relevant tests were inspected. Claims
in this table describe existing code, not proposed 5F functionality.

| Existing component | Verified behavior and constraint |
| --- | --- |
| [Evaluation protocol](../src/quant/research/evaluation_protocol.py) | `validate_hour`, `evaluation_split`, `label_completed`, historical/input eligibility, `ForecastState`, final-score validation and `validate_counts` are pure helpers. UTC-equivalent aware zero-offset hourly datetimes are accepted; no timezone-name identity rule. |
| [4A accounting](../src/quant/research/forecast_accounting.py) | Forecast statuses are `emitted`/`abstained`; final score statuses are `scored`, `emitted_but_not_scored`, `not_scored_no_forecast`. `Quality` only accepts OHLCV field names. `Score` reads an outcome and requires closure even for abstentions. `Accounting` requires typed 4A scores covering the exact universe. |
| [4A reporting](../src/quant/research/evaluation_reporting.py) | `metrics` is pure but its public input is `Accounting`; `comparison_set` rejects non-4A accounting objects. `Provenance` cannot claim verified artifact bytes; `ValidationEvidence` requires synthetic mode and no historical authorization. `build_report` is not a historical reporting API. |
| [4B coordinator](../src/quant/research/model_evaluation.py) | `run_synthetic` requires explicit typed synthetic fixtures. Current/future target access is separated from emission. Selected-alpha Ridge replay is Test-only; training is accounting-only and validation is candidate-tuning-only. No historical execution bridge exists. |
| [5A adapter](../src/quant/research/historical_adapter.py) | `audit_pinned_history` verifies approved bytes/identities before semantic inspection. `HistoricalRecord` preserves source row/key and raw values; `HistoricalOutcome` preserves separate endpoint/window/unresolved anomalies and original reasons. `audit_frames` alone does not authenticate files. |
| [5C projection](../src/quant/research/historical_projection.py) | `verify_pinned_source` mints a privately registered binding; `source_ref` returns identity only. Forecast plans do not expose outcomes. Strict Fail-Closed v1 still blocks unsupported native fields, including feature-only occurrences. Closed projection is not a native scorer. |
| [5E representation](../src/quant/research/historical_representation.py) | `verify_pinned_representation_source` reuses 5A/5C verification and binds observed raw manifest bytes. `represent_closed`/`audit_native` preserve native occurrences with independent dimensions. An envelope can exist for a blocked/failed native result; envelope presence is not admission. No scorer, historical forecast API or writer exists. |

Normative documents remain [QNT-003B](QNT-003B_EVALUATION_PROTOCOL.md),
[QNT-003D](QNT-003D_FINAL_RESEARCH_DESIGN.md),
[5A](PQTA-003D-5A_HISTORICAL_ADAPTER.md),
[5B](PQTA-003D-5B_HISTORICAL_PROJECTION_POLICY.md),
[5D](PQTA-003D-5D_UNSUPPORTED_ANOMALY_REPRESENTATION.md),
[5E](PQTA-003D-5E_IMPLEMENTATION_CONTRACT.md) and
[MODEL_EVALUATION](MODEL_EVALUATION.md). Protocol `qnt-003d-design-v1`, dataset
contract `pqta-003b-origin-ledger-v1`, policy `pqta-003d-5b-projection-v1`,
serializer `pqta-003d-5c-canonical-v1` and native 5E identities are unchanged.

Relevant existing evidence includes:

- [Protocol tests](../tests/test_evaluation_protocol.py): completed-history
  short-circuiting, input masks, UTC equivalence and final score timing.
- [Accounting tests](../tests/test_forecast_accounting.py):
  `test_target_change_cannot_modify_emission`,
  `test_overlapping_reasons_keep_score_priority_distinct_from_abstention`,
  closure for abstentions and exact conservation.
- [Reporting tests](../tests/test_evaluation_reporting.py): exact intersections,
  frozen-Ridge prerequisite matrix, blocked four-model comparison, independent
  method-own scopes and digest-syntax versus verified-byte distinctions.
- [Coordinator tests](../tests/test_model_evaluation.py): instrumented forbidden
  outcome reads, no cross-gap AR pairs, non-Test Ridge replay rejection and empty
  universes with no fabricated events.
- [Projection tests](../tests/test_historical_projection.py) and
  [representation tests](../tests/test_historical_representation.py): forged
  bindings, exact-close gates, literal tokens, independent dimensions, audit-only
  origins and unchanged synthetic/reporting guards.

These are prior software contracts/evidence; no regression or historical audit
rerun is claimed by this document.

## 3. Problem Definition

5A/5E retain information that 4A's OHLCV-only quality summaries cannot encode
exactly. This is a representation/type-boundary problem, not permission to
change the approved target, anomaly masks, statuses or model mathematics.

The source audit timeline contains 50,845 origins, including one audit-only
origin; the unchanged split union contains 50,844. These are carried-forward
source-contract facts, not new 5F results. Legacy 5C blocks remain valid under
their named target schema. A future native path must neither discard those
origins nor pretend they became legacy-compatible.

The design must distinguish numeric target validity, native representability,
legacy compatibility, source authentication, evidence completeness, association
resolution, mathematical closure and model/sample eligibility. None is an alias
for another. Retrospective Lane A masks remain retrospective; Gold
`available_at=null` and `decision_eligible=false` are not overridden.

## 4. Architecture Alternatives

| Alternative | Benefits | Risks, compatibility and migration cost | Architect disposition |
| --- | --- | --- | --- |
| A — Widen 4A accounting objects | Existing typed book/metric consumers could remain superficially similar. | Changes approved validators and negative tests; field strings alone still lose occurrence roles/order/raw evidence. Requires versioned 4A migration and historical authentication/reporting changes. High synthetic-regression exposure. | Do not select: unnecessary contract change for this scope. Not an approved rejection or amendment to 4A. |
| B — Native envelopes plus exact shared pure helpers | Retains all native metadata and source links; isolates historical authentication and temporal gates. Reuses status/count/reason policy without changing 4A/4B. | Needs explicit native record validation, capability issuance and a reviewed metrics type bridge. Thin container/identity reconciliation is new; avoid cloning policy. | APPROVED — ADR-5F-01; design only, not implementation authority. |
| C — Independent historical engine | Full control over native types and trust boundary. | Duplicates status/reason/metric logic and increases semantic drift, maintenance and equivalence-test cost. A parallel engine still needs the same temporal/authentication gates. | Do not select absent a demonstrated reuse impossibility. |

Alternative B is the approved architecture. No alternative is implemented; A/C
are not selected, and this does not amend or migrate any existing contract.

## 5. Approved Architecture — Design Only

```text
EXISTING: 5A pinned bytes -> 5C registered source -> 5E native audit context
                                                     |
DESIGN ONLY: audit-side session + full scope + deferred execution authority
             |                              |
             | forecast-only reference      | separate closed-outcome reader
             v                              v
       narrow allowed input plan       closure gate -> native outcome capability
             |                              |
       future authorized producer      existing immutable forecast + closed outcome
             |                              |
       immutable forecast record ------> native final score classification
                                                |
                                      full-universe reconciliation
                                                |
                                 STOP: historical reporting remains deferred
```

All edges below the existing context describe design, not executable connections.
Capability separation is approved in principle; actual authority/producer
receipts remain deferred under ADR-5F-07. The scorer/accountant has no model
dependency. A future model coordinator is a
separate authorization and implementation milestone; 4B is not repurposed.
Forecast consumers receive neither `SourceBinding` nor `NativeSource`: both
retain outcome-bearing history. An opaque origin reference carries identity,
not an outcome resolver or proof of model execution.

Proposed native scope assessment checks required identity/schema/linkage and
association meaning without changing the legacy 5C result. Known native
`candle`/`unknown` tokens do not by themselves block this separately named target
schema. Unrecognized vocabulary, contradictory linkage or required unresolved
meaning cannot be interpreted by guessing. They block scope completion or fail
integrity explicitly, never shrink the requested universe. Unverified referenced
evidence remains a disclosed limitation, not a new blanket Lane A exclusion.

### Exact reuse boundary

| Existing helper/type | Proposed reuse without modifying it |
| --- | --- |
| Public protocol time/version/origin/status/count validators | Call unchanged on the native record's validated scalar fields. `validate_score_state` validates final states, not pending execution. |
| `finite`, `forecast_reason_order`, `ordered_reasons`, `SCORE_PRIORITY`, existing model/sample/period constants | Reuse unchanged for finite values, accepted reasons, deterministic precedence and identities. Never call private reporting status functions as a new public API. |
| `forecast_accounting.Forecast` | May serve as an internal value-only validation object: it contains no target/quality metadata or historical authentication claim. It is not a historical execution receipt. The public product remains the separately source-bound native forecast. |
| `timestamp_digest` | Reuse unchanged for sorted unique in-split scored origins; never feed audit-only origins or substitute a JSON digest. |
| `Quality`, `Outcome`, `Score`, `Accounting`, `account`, `comparison_set`, `build_report`, `ValidationEvidence` | Not native containers/entry points. No lossy translation, forged synthetic evidence, container subclass trick or guard bypass. |
| `metrics(book: Accounting, ...)` | Numerical semantics are reusable, but native input is not currently supported by its public signature. Defer an exact metric-only bridge for separate type-boundary review; no duck-typing claim, fabricated 4A book, duplicated RMSE/MAE implementation or historical call here. |

Native container validation and origin-set reconciliation are necessary because
the existing containers require typed 4A scores. This justifies new identity and
collection checks, not copying numerical estimators, reason-priority tables or
selection rules. Scoring emits validated value pairs/statuses; aggregate metric
integration remains outside the executable 5F boundary.

## 6. Proposed Interfaces and Schemas

Executable signatures and types in this section are **PROPOSED — NOT IMPLEMENTED**.
Native schema/policy/identity architecture is approved in principle under
ADR-5F-02, and capability separation under ADR-5F-03. That is not approval of
an executable API, implemented serializer, registered schema or usable authority.
Exact implementation and verification require separate review and authorization.

| Proposed identity | Meaning |
| --- | --- |
| `pqta-historical-scoring-accounting-v1` | Native forecast/outcome/score/accounting record schema, not `pqta-model-evaluation-v1`. |
| `pqta-003d-5f-scoring-accounting-v1` | Interface-policy identity preserving existing evaluation semantics. |
| `pqta-003d-5f-canonical-v1` | Proposed deterministic in-memory encoding; exact implementation needs review. Does not change 5C/5E encodings. |

### Record fields and validation

The design requires frozen/deeply read-only records; none is implemented here.
Fields are required unless explicitly optional:

| Proposed record | Required fields and rules |
| --- | --- |
| `HistoricalProvenanceRef` | Source `dataset_spec_id`, source `artifact_build_id`, approved Silver/Gold/ledger/four-file hashes, canonical manifest digest and version, observed raw manifest hash, feature version/order, protocol/dataset versions, registered source receipt reference and source mode. Separate proposed scoring spec/build identities. Hash syntax alone proves none of these. No absolute workstation paths. |
| `HistoricalOriginRef` | Opaque binding reference plus exact `exchange=binance`, `symbol=BTC/USDT`, `timeframe=1h`, source identifier, source row index, origin UTC, period and versions. Identity only; no target value, validity, endpoint flags, raw record, row-content accessor or resolver. |
| `HistoricalScopeSpec` | Source identity, exact period bounds, intended use, complete ordered origin universe/digest, declared methods/samples and fixed analysis boundary. No target-valid or representable-subset filter. Audit-only identities retained separately. |
| `HistoricalForecast` | Origin reference, period, method, sample (`a_primary`/`a_sensitivity`), forecast origin, feature open `origin-1h`, status, nullable prediction, ordered abstention reasons, provenance and input/producer trace reference. Optional model/refit reference only where applicable. No target/score fields or closed-outcome capability. |
| `ClosedHistoricalOutcomeRef` | Opaque privately issued capability binding exact source/origin/row to an authenticated closed native view, explicit checked-at and theoretical close. Not constructible authority from JSON. Held only by the outcome/scoring coordinator. |
| `HistoricalOutcomeView` | Origin reference, original target/value-valid flag, original lexical null-reason tuple and primary reason, separately priority-ordered reason view, endpoint anomaly flag and occurrences, separate window/unresolved occurrences, native tokens/raw values, linkage/evidence limitations, source-authentication reference, theoretical close, checked-at and `closure=closed`. Preserve optional source `target_value_sensitive` when present; do not derive a missing claim. Retain the complete lossless native envelope audit-side. |
| `HistoricalScore` | Exact immutable forecast reference/digest, closed-outcome reference, matching source/origin, checked-at, model/sample/period, one final score status, primary score reason, ordered exclusive/overlapping reason views and provenance. Prediction/outcome values are referenced unchanged, not repaired or recomputed. |
| `HistoricalAccountingResult` | Declared scope/provenance, exact ordered forecast/score keys, counts, exclusive abstention counts, primary and overlapping score reasons, own scored-origin set/digest, full-universe coverage and separate audit-only identities. `accounting_complete` is a validated accounting fact, not evaluation/report completion. |
| `HistoricalScopeBlock` | Scope identity, classification `blocked` or `failed`, deterministic diagnostic codes and audit-only affected-source references; no invented forecast/score records, abstention totals or performance metrics. Execution progress, if any, is retained separately. |

`method` uses only `zero_return`, `expanding_mean`, `ar_1`, `ridge_7`.
Forecast identity is `(source identity, period, origin, model, sample)` within
one declared execution/build context. Score identity additionally binds the
immutable forecast and exact closed outcome. Different source builds, receipt
bindings, rows, periods or samples are not interchangeable even at the same UTC
hour. One source outcome is shared identically across methods/samples; only the
sample-specific score classification varies.

An emitted forecast requires a finite non-Boolean numeric prediction and no
abstention reasons; Zero Return must be exactly `0.0`. An abstention requires
null prediction and one or more approved method/sample reasons in existing
priority order. Do not invent `projection_blocked`, `not_run` or a Ridge
selection code as a model abstention reason. Source/authorization failures are
not model numerical failures.

Producer trace: Zero needs no fit; Mean links completed-history count/cutoff;
AR/Ridge emissions link the successfully scheduled current-day fit and maximum
admitted outcome closure. Ridge also links the frozen selection and alpha.
Failed/skipped required refits cannot masquerade as successful fit references.
The native scorer never fits a model or generates a forecast. Its design requires
validation of these references, not a refit. Actual execution receipt
issuance/verification and producer authority remain deferred under ADR-5F-07.
No caller-provided prediction is accepted as authenticated model output merely
because its source is verified. A prediction, fit-shaped object or hash cannot
prove model execution; the signature below does not authenticate that claim.

### Proposed signatures

Signatures only; all session/authority/capability types are proposed. No bodies,
runner, CLI, writer or implementation module are created in this milestone.

```python
def open_verified_history(root: Path) -> HistoricalAuditSession: ...
def assess_scope(session: HistoricalAuditSession,
                 spec: HistoricalScopeSpec) -> ScopeAssessment: ...
def bind_execution_scope(session: HistoricalAuditSession,
                         spec: HistoricalScopeSpec,
                         authority: ReviewedExecutionAuthority
                         ) -> HistoricalExecutionScope | HistoricalScopeBlock: ...
def forecast_origin(scope: HistoricalExecutionScope,
                    origin: datetime) -> HistoricalOriginRef: ...
def forecast_inputs(scope: HistoricalExecutionScope,
                    ref: HistoricalOriginRef) -> NativeForecastInputView: ...
def record_forecast(scope: HistoricalExecutionScope, ref: HistoricalOriginRef,
                    *, model_id: str, sample_policy: str,
                    prediction: float | None, reasons: tuple[str, ...],
                    producer_trace: ProducerTraceRef) -> HistoricalForecast: ...
def closed_outcome(reader: HistoricalOutcomeReader, ref: HistoricalOriginRef,
                   *, checked_at: datetime
                   ) -> ClosedHistoricalOutcomeRef | OutcomeBoundaryResult: ...
def score_historical(scorer: HistoricalScorer, forecast: HistoricalForecast,
                     outcome: ClosedHistoricalOutcomeRef,
                     *, checked_at: datetime) -> HistoricalScore: ...
def reconcile_historical(scope: HistoricalExecutionScope, *, model_id: str,
                         sample_policy: str,
                         forecasts: tuple[HistoricalForecast, ...],
                         scores: tuple[HistoricalScore, ...]
                         ) -> HistoricalAccountingResult: ...
```

`HistoricalAuditSession` is trusted audit-side only and reuses the existing
pinned verification factories. It is never a predictor argument. The proposed
execution-scope factory must validate a separately reviewed authority/scope
record; there is **no current authority** and no `authorized=True` shortcut.
The exact authority/producer receipt mechanism is an open implementation-review
decision, not a claimed security control. Scope assessment is not permission.

The narrow `NativeForecastInputView` contains only current time/feature/lag
allowlisted fields, their existing current-input masks and identity. It must
be validated without current-target traversal. A new separately versioned
native input adapter needs review: existing 5C `plan_forecast_fields` cannot
silently accept its currently unsupported feature-window tokens. No whole-row
hash/endpoint annotation is used as a predictor or returned as input diagnostics.
`HistoricalExecutionScope`, `forecast_origin` and `forecast_inputs` are held or
called only by the trusted coordinator, not the predictor. A predictor receives
the already-issued view for its current origin and separately admitted completed
history; it cannot request another/future origin or mint a new view/capability.

`OutcomeBoundaryResult` has identity/clocks and `not_closed` or `audit_only`
without an outcome attachment. Closed semantic uncertainty may return `blocked`;
integrity failure returns `failed` or a typed validation error. These are
boundary/scope classifications, never additional forecast/score statuses.
Before closure, even error diagnostics must not traverse target values, flags,
raw annotations or full-row digests. Unknown versions, malformed fields,
duplicates and identity mismatch fail explicitly; no partial trusted result.

### Serialization expectations

Future validation must reject unknown fields/versions, duplicate JSON keys,
duplicate record keys, nonfinite numbers and ambiguous identifiers. Use sorted
object keys, compact UTF-8 JSON, one final LF and UTC-equivalent timestamps
encoded `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Preserve raw timestamp strings, null versus
absent keys, signed zero, source occurrence order and duplicates; derived
forecast/score reasons follow existing priority. Forecast/score rows sort by
declared period, origin and canonical method/sample order. Original source
indices remain unchanged.

Serialization emits data-only identity references, never an outcome resolver,
process registry token or reconstituted authority. A deserialized record is
untrusted until its bytes, source binding, execution context and links are
revalidated. A prospective scoring spec pins logical source/scope/policy;
its build additionally pins code/dependencies/serializer; payload SHA-256 hashes
actual canonical payload bytes excluding its own digest field. Processing time
must be explicitly injected and excluded from deterministic logical payloads;
theoretical checked-at is a semantic cutoff, not processing time. Persisted
artifact-byte verification and conflict handling are deferred, not supplied by
5E's process-local map. No serialization or artifact is generated here.

## 7. Forecast / Outcome / Score Lifecycle

| Stage | Proposed behavior | Not permitted |
| --- | --- | --- |
| Source/scope preflight | Authenticate exact snapshot, versions/keys and full declared universe; identify native limitations and separate audit-only rows. | Treat a source receipt as model-execution proof; choose only legacy-compatible/target-valid origins. |
| Scope blocked or unexecuted | Retain a scope block or `not_run` lifecycle record, with no model-status rows inferred. | Convert a skipped origin into `abstained`, create scores or fabricate zero metrics. |
| Forecast event `o` | Future authorized producer uses only allowed current inputs plus history closed by `o`; record immutable emitted/abstained result. | Current target value/validity/endpoint flag, ex-post scoreability or outcome capability in prediction arguments. |
| Waiting for outcome | Forecast remains unchanged; no final score exists yet. | Add a `pending` forecast/score status or call a pre-close emission unscorable. |
| Outcome close `o+1h` | Separate reader checks source/key/clocks, then validates closed native metadata and issues outcome capability. | Fabricate publication evidence or pass that reader/capability to a forecaster. |
| Final scoring | Match exact immutable identities; apply approved sample/target policy and existing reason order. | Fit, predict, tune, replace values, alter emission or abstention reasons. |
| Reconciliation | Require every scheduled method/sample/origin exactly once, plus distinct audit-only conservation. | Hide missing/duplicate records or label partial execution complete. |

The proposed scorer requires closed outcome access **even for an abstained
forecast**, matching 4A `Score`'s outcome-audit boundary. The pure protocol helper
can validate `not_scored_no_forecast` at the origin without an outcome; that is
not permission for this interface to read one early. No new pending state is
needed: unfinished execution has no final score record.

Final status rules are unchanged:

- Abstained forecast -> `not_scored_no_forecast`, regardless of later validity.
- Emitted forecast with any applicable score exclusion ->
  `emitted_but_not_scored`; retain the finite prediction.
- Emitted forecast with valid eligible target and no exclusions -> `scored`.

A malformed source claiming `target_valid=True` with null/NaN/infinity is an
integrity error, not a target to silently drop, impute, reflag or score. A
legitimately invalid target has null value plus original nonempty reasons; no
synthetic zero is substituted. Target arithmetic and source values are copied
from authenticated history, never recalculated by this interface.

## 8. Accounting and Conservation

The declared opportunity universe is every hourly origin in the **entire
authorized approved period**, independent of input/target validity, warm-up,
anomaly, fit success or legacy compatibility. Full historical split boundaries
remain:

| Period | Half-open origin interval UTC | Permitted interpretation, not execution approval |
| --- | --- | --- |
| `training_history` | `[2021-01-01 01:00, 2024-01-01 00:00)` | Completed-history/cold-start accounting only; no held-out result claim. |
| `validation` | `[2024-01-01 00:00, 2025-01-01 00:00)` | Fixed A-primary Ridge candidate tuning diagnostics only. No selected-alpha replay. |
| `test` | `[2025-01-01 00:00, 2026-10-20 13:00)` | Frozen-alpha comparison, only after separate authorization. |

The proposed final forecast/score accounting path does not authorize replay in
any period. Training/validation accounting must not fabricate method records
for operations that were not authorized/executed. Candidate validation has its
own frozen tuning set under the existing Ridge contract, not a four-model test
comparison. The concrete historical execution/candidate-ledger interface is
deferred; this does not change the implemented synthetic coordinator's behavior.

### Declared scope versus actual execution

These concepts must remain distinct for each period/method/sample:

| Concept | Accounting meaning |
| --- | --- |
| Declared evaluation origins | The immutable full scheduled universe, defined before execution. Declaration creates no forecast or score rows and proves no model ran. |
| Actually executed forecast origins | Origins at which an authorized method invocation completed and an actual emitted or legitimately abstained forecast decision was recorded. A started call that aborts without a valid decision is incomplete execution, not an invented abstention. |
| Model abstentions | Actual completed method decisions with null prediction and approved reasons. Count only these recorded decisions, not origins skipped by a scope block or missing authority. |
| Scope blocks | Prerequisite/identity/representation/authority limitations of the requested scope. Preserve diagnostics separately; do not convert the declared universe or skipped origins into model abstentions. |
| Not-run execution | No method decisions were executed. Retain the declaration and `not_run` lifecycle information, with no fabricated forecast/score rows or evaluation coverage. |
| Interrupted/failed execution | Retain only actual immutable decisions, emissions and any legitimately finalized scores, plus explicit progress/missing-origin diagnostics. Refuse completed accounting; do not fill unexecuted or unfinished origins with statuses. |

Actual execution progress never replaces the declared denominator with a smaller
observed subset. Completion requires actual forecast-decision keys and final
score keys to equal the entire declared universe exactly. Before completion,
partial progress counts are explicitly partial, not a reconciled full-scope
result or permission to manufacture records. These lifecycle distinctions add
no forecast/score status or model abstention reason.

For each completed, authorized, fully accounted execution scope/period/method/sample:

```text
N_origins = N_emitted + N_abstained
N_emitted = N_scored + N_emitted_but_not_scored
N_abstained = N_not_scored_no_forecast
N_origins = N_scored + sum(exclusive_primary_score_exclusion_counts)
sum(exclusive_abstention_reason_counts) = N_abstained
forecast_coverage = N_emitted / N_origins  # null if N_origins = 0
```

Require exact sorted key equality between declared origins, forecasts and final
scores; equal counts alone are insufficient. Reject missing, duplicate, extra,
wrong-period, wrong-model/sample and mismatched-source entries. Reject a request
to run only the representable or scorable subset. Synthetic empty-universe
fixtures can reconcile zero counts with null coverage, but establish no executed
evaluation or complete nonempty evidence.

If preflight blocks, return no accounting pretending that execution occurred.
If execution is interrupted or a later integrity error occurs, preserve actual
emissions and progress audit, classify execution incomplete/failed and refuse a
complete accounting result. Never invent missing forecasts/scores or retroactively
reclassify valid emissions. Scope-wide faults are not abstention reasons.

### Reasons, denominators and future metrics

Derive reasons from the immutable forecast reasons and closed target reasons,
plus `target_manifest_anomaly` for A-sensitivity only. Use existing
`ordered_reasons` and `SCORE_PRIORITY`; preserve original source reason order
separately. Primary score-exclusion precedence remains target missing/incomplete/
nonconsecutive; source/close/nonfinite invalidity; sensitivity endpoint anomaly;
Ridge feature reasons; AR lag reasons; history/fit/prediction reasons. Feature
ties retain the existing seven-feature order. No private rewritten reason table.

Primary score reason can differ from the original forecast abstention reason;
retain both. Overlapping reasons can exceed the origin count.
`unknown_historical_availability` remains visible on every affected row as an
overlapping diagnostic, not an exclusive score exclusion that erases Lane A.

Method-own coverage always uses full scheduled origins. Future direct
comparisons use **scored forecasts only**, exact timestamp-set equality and all
declared participants: one method/sample for `method_own`; three baselines for
`baseline_common`; all four methods for `feature_common`; both samples for
`paired_sensitivity_common` with explicit baseline/feature parent. Do not drop
an unavailable Ridge to complete a four-model comparison. Keep separately
authorized independent scopes distinct; never silently downgrade the requested
scope. Intersections do not change own forecast/abstention totals.

Preserve these mathematical definitions; no metric is computed here:

```text
E = exact declared scored timestamp set; n = len(E)
e_o = prediction_o - target_o
RMSE = sqrt(sum(e_o**2) / n)
MAE = sum(abs(e_o)) / n
directional_accuracy = sum(sign(prediction_o) == sign(target_o)) / n
```

`sign` has three exact classes -1/0/+1; signed zero is zero, no tolerance or
neutral-row exclusion. Empty scored sets yield null metrics, not zero. Preserve
the existing stable `hypot`/`fsum` reduction semantics and finite-intermediate
failure, never drop an error row. A native metric-only type bridge is deferred
for explicit review; existing reporting functions are not called with fake
4A containers. Scored-set SHA-256 reuses sorted unique
`YYYY-MM-DDTHH:MM:SSZ\n` UTF-8 origins (empty set = empty bytes), distinct from
microsecond JSON encoding. No metrics or comparison artifact is created here.

## 9. Native Anomaly Semantics

| Condition | Native retention and approved scoring effect |
| --- | --- |
| Valid target with any endpoint anomaly | Preserve every occurrence/type/field/raw value. A-primary can score it; A-sensitivity excludes via `target_manifest_anomaly`, independent of numeric sensitivity. |
| Feature-window-only anomaly | Preserve separate window occurrences and masks. It is not an all-method target exclusion; Ridge/AR current-input/history rules still apply independently. |
| Literal `candle` | Preserve exactly; never expand into OHLCV. Numeric target invalidity comes from source validity/reasons, not a newly inferred token-based rule. |
| Literal `unknown` with known endpoint/window role | Preserve unspecified field attribution. It is not null, missingness, all-fields sensitivity or unresolved association. The known endpoint role still triggers sensitivity target exclusion. |
| Unresolved association or required missing linkage | Retain the original record, source column and raw values. Do not guess its role, produce an incomplete outcome, drop its origin or turn uncertainty into model abstention. Block scope completion where interpretation is required. |
| Contradictory source/manifest identity or metadata | Explicit integrity failure; preserve audit evidence, stop completion and do not repair the source. |
| Recorded references with unverified external evidence | Disclose separately; source-byte/link verification does not verify referenced archive/REST evidence, severity, root cause or publication time. No invented verified status or new all-row exclusion. |

Endpoint/window/unresolved collections preserve original order, multiplicity,
field names, timestamps, nulls and raw records, including shared manifest events
in multiple roles. Do not narrow endpoint masks to `close` or
`target_value_sensitive`. Unknown future semantic vocabulary remains opaque
audit evidence, not automatically accepted native schema.

Preserve both retrospective samples **through training and current inputs**:

- A-primary: valid completed targets, valid exact AR pairs/current lag and
  complete finite Ridge rows/vectors remain usable despite anomaly flags.
- A-sensitivity: Mean removes endpoint-anomalous completed labels; AR also
  removes anomaly-involved exact pairs/current lags; Ridge also removes involved
  feature windows from training/current inputs. Target-side scoring exclusions
  occur only after closure. Do not reduce sensitivity to a scoring-only mask.
- Zero has no training mask and emits zero at every authorized in-split forecast
  event; later target anomalies may prevent a score but never retract emission.

Minima stay 720 eligible targets/pairs/rows. Mean updates hourly; AR/Ridge refit
at UTC midnight only. Failed/skipped required refits invalidate old parameters;
no stale fallback. Ridge scaling is training-only; its alpha is selected on the
fixed A-primary 2024 folds/set and frozen for Test and both samples. No selected
alpha replay outside Test, retuning or feature recalculation is introduced.
These rules constrain a future producer; the proposed scorer does not fit or
enforce eligibility by inspecting future targets.

## 10. Source Authentication and Provenance

Trust chain: 5A checks approved file bytes/schema/provenance -> 5C registers exact
records/receipt -> 5E binds native manifest representation -> proposed 5F
session binds exact origin/forecast/outcome/score references -> separately
reviewed historical reporting. Each arrow is distinct from anomaly-evidence or
PIT verification. The last two interfaces are not currently implemented.

Only the future trusted audit-side session, after invoking existing pinned
verification, may issue a registered forecast-origin reference for a bound
in-split key. `OpaqueSourceRef` data alone is not authority. The forecaster gets
the identity-only result/current-input view, never the session, outcome reader,
full manifest, source attachment or a method that can mint a closed capability.

Before outcome inspection: validate process registration/source mode, unchanged
receipt/manifest binding, exact dataset/build/file/index/origin, known versions,
approved split and `origin+1h <= checked_at`. Only then traverse full-row digests,
target validity/value/reasons or endpoint/native diagnostics. After closure,
require validated native representability and required association/linkage
consistency, not merely a non-null envelope. Exact source identity and outcome
content are shared across methods/samples; match every forecast/score reference.

Reject unregistered/copied contexts, forged receipts/Booleans, swapped source
rows, wrong index/key, changed receipt or raw manifest identity, contradictory
record links, unknown policy/schema, duplicate origins and unauthorized subset
requests. Known native token support does not change 5B/5C compatibility. No
authentication or mapping fault is downgraded to model abstention.

Existing authentication covers the snapshot actually read, not future filesystem
state. After process restart, reread/reverify approved bytes and mint fresh
registered bindings; a stored receipt/digest cannot authenticate itself. Any
future stored forecast/score would also need actual byte verification, source
reauthentication and independently validated execution/record links. Source
authentication does not prove model execution. Deferred producer authority and
receipt verification cannot be substituted with caller-provided predictions,
even when the source snapshot is authenticated.

The current registries and 5E build/payload conflict check are **process-local
only**. They are not signatures, a hostile-Python sandbox, a persistent registry
or cross-process protection. A future persistent publisher/reader must be
separately designed; no current mechanism supplies those guarantees.

## 11. Temporal Isolation

For origin `o`, the feature candle opens at `o-1h`; target uses the closes of
candles opening `o-1h` and `o` and closes theoretically at `o+1h`. Historical
label origin `h` can enter completed history only when `h+1h <= o`. Check clocks
before reading its value/validity/anomaly flags. Exact adjacent opens are
required: current AR lag uses `o-2h,o-1h`; a training pair at `h` uses
`h-2h,h-1h,h`. No missing-hour removal may compress adjacency.

Example: forecast origin `2025-01-02T00:00:00Z` uses the feature candle opening
`2025-01-01T23:00:00Z`. Label origin `2025-01-01T23:00:00Z` closes at 00:00 and
may enter completed history before the scheduled refit. The current 00:00 target
closes at 01:00; its value, validity and endpoint flags cannot affect that
midnight forecast. The final out-of-split origin `2026-10-20T13:00:00Z` closes
at 14:00 but remains audit-only even after closure. Test still ends exclusively
at 13:00; the last in-split origin is 12:00 and closes at the fixed boundary.

Changing `checked_at` must never change the frozen historical forecast-only
record, its prediction/status/reasons or the fields it exposes. It can permit a
separate outcome capability or alter temporal audit diagnostics only. Outcome
readers are not attached to forecasts when the clock advances. Instrumented
objects must raise on any forbidden value, validity, anomaly, attachment or
full-row-digest access before closure. Source authentication is an offline
audit step which may read the complete historical artifact; that does not make
outcome data available to a forecast consumer.

Theoretical closure is not verified publication/observation latency. Preserve
Gold null availability, false eligibility, fixed analysis boundary and separate
processing time. Both Lane A samples are retrospective; neither is PIT evidence.
Lane B and trading/backtesting remain blocked.

## 12. Reporting Boundary

The proposed accountant returns validated native in-memory records/value pairs,
not `pqta-model-evaluation-v1` reports or synthetic `ValidationEvidence`.
Historical reporting, metric integration/publication and dashboard consumption
remain separately reviewed interfaces. No historical report is constructed here.

A future read-only reporting boundary would consume authenticated source and
execution receipts plus complete native accounting and approved scored-set
descriptors. It must independently validate source bytes, actual model execution
provenance, frozen selection/refit cutoffs, score reconciliation, exact comparison
participants/sets, metric eligibility and processing completion. A caller's
`complete=True` or `authenticated=True` cannot substitute for those checks.

Preserve reporting precedence `blocked`, `no_forecasts`, `no_scored_forecasts`,
`complete` for applicable valid final results. `failed` is invalid/interrupted
execution; `not_run` is unexecuted. These are not forecast/score statuses. No
forecast is not the same as no common scored timestamps; full-period emission
coverage remains independent. Missing/unavailable frozen Ridge selection blocks
its requested comparison, never makes a four-model comparison complete.
Historical native acceptance or reconciled arithmetic alone cannot set an
evaluation status to complete. Empty scopes/sets establish no performance.

Source authentication, model execution, score accounting, metric eligibility and
human review are separate future completion evidence. Training is accounting
only; validation is candidate tuning only; Test is frozen-alpha comparison.
No test-selected trading model, confidence score, performance claim, synthetic
mode relabeling or existing reporting-guard bypass is allowed.

## 13. Synthetic Verification Plan

Specifications only for a later separately authorized implementation. No tests,
targets, forecasts, scores or metrics are created/executed in this milestone.
Fixtures use invented values/temporary bytes and remain explicitly synthetic;
they cannot claim authentication of approved historical sources.

| ID | Synthetic specification and expected result |
| --- | --- |
| F01 | Emitted finite forecast + valid closed target -> `scored`; immutable prediction and matching source refs preserved. Independently check exact-zero positive/negative/zero conventions for the future metric bridge. |
| F02 | Emitted + invalid/null target with missing/source/close reasons -> `emitted_but_not_scored`; no zero substitution or denominator shrinkage. Contradictory valid-null/NaN/infinity target is an explicit integrity error. |
| F03 | Approved model abstention + closed outcome -> `not_scored_no_forecast`; unchanged forecast reason even when target reasons outrank it for score audit. |
| F04 | Valid anomalous endpoint target in A-primary remains scorable; raw type/fields/evidence retained. |
| F05 | Same endpoint record in A-sensitivity excludes scoring only after closure; no forecast retraction. Repeat for volume-only and literal `unknown` endpoint fields. |
| F06 | Feature-window-only anomaly does not exclude target globally. Preserve separate Ridge/AR retrospective input/history masks and all method-specific reasons. |
| F07 | Literal `candle`/`unknown`, absent/null keys, signed zero, duplicate occurrences and raw order survive native encoding. Never expand tokens or infer invalid numeric data. |
| F08 | Wrong dataset/build/receipt/file/index/origin/period/sample or swapped outcome fails; equal UTC hour alone is insufficient. Shared outcome remains identical across methods/samples. |
| F09 | Caller hash/Boolean, copied binding/capability and deserialized receipt cannot mint authority. Synthetic mode cannot become authenticated history; restart requires fresh source verification. |
| F10 | Pre-close outcome call returns clock/identity-only `not_closed`; instrument target/value-valid/anomaly/attachment/full-row-digest access to raise. Exact-close boundary is inclusive; custom zero-offset UTC-equivalent timezone accepted. |
| F11 | Change current/future target values, validity and endpoint flags under access traps: no change to current forecast-only record/status/input. Advance checked-at without giving forecaster an outcome capability. The predictor cannot obtain an execution scope or request another/future origin's view. |
| F12 | Missing/duplicate/extra forecast or score origin, unauthorized subset or equal-count wrong-key set fails reconciliation; no silent deduplication. |
| F13 | Scope block/not-run produces no fabricated forecasts, scores, model abstentions or metrics. Mid-run integrity failure preserves actual immutable emissions but refuses complete accounting. |
| F14 | Final out-of-split origin remains separately audit-only at both 13:00 and 14:00; never scheduled/scored or included in scored-set digest. |
| F15 | All conservation equations, exclusive reason totals and overlapping reason retention hold per period/method/sample. Coverage denominator is full universe, not valid-target/common set. |
| F16 | Permuted inputs canonicalize deterministically while original source indices/occurrence arrays remain unchanged. Tampered keys/bytes/digests and conflicting payload fail; do not claim persistent protection. |
| F17 | Existing synthetic coordinator rejects historical/native objects; no `synthetic=True` relabeling or widening of 4A containers. Existing tests unchanged. |
| F18 | Trap baseline/Ridge fitting, alpha selection, prediction, ingestion, feature recalculation, network and dataset writes during scorer/accountant calls; none may occur. |
| F19 | Trap historical use of `build_report`/synthetic evidence guards. Future metric-only bridge must prove exact finite pairs/sets without constructing lossy 4A outcomes; until reviewed, no native aggregate metric API exists. |
| F20 | Trap dashboard routes, signal/order APIs and artifact publication. Source and immutable origin bytes remain unchanged. |
| F21 | Empty synthetic universe/empty scored set: zero accounting counts, null coverage/metrics where applicable, no fabricated events or complete-evaluation claim. |
| F22 | Required unresolved association/linkage blocks completion while raw evidence is retained; known endpoint `unknown` is distinct and uses approved sample rule. Unverified recorded references are not falsely upgraded or made a new blanket exclusion. |
| F23 | Reuse existing reason priority for overlapping missing target, sensitivity anomaly and failed fit. No new status, abstention code or stale-fit fallback. Full valid-candidate alpha set and frozen selection remain unchanged. |
| F24 | Exact scored intersections and participant membership for own/baseline/feature/paired sets; no alpha-specific dropped timestamp, blocked-Ridge omission or redefinition of own coverage. |

## 14. Risks and Open Decisions

1. **Approved architecture, unapproved executable interfaces:** Alternative B,
   native scoring semantics and full-universe accounting design are approved.
   Native identity and capability architecture are approved in principle.
   5E metadata representability is implemented; no native 5F forecast/outcome/
   scoring/accounting interface is implemented or authorized for execution.
   Separate implementation review and Project Owner authorization remain required.
2. **Forecast-source/producer authority:** existing 5C/5E factories are audit-side.
   The narrow native input factory, execution-scope authority and producer/refit
   receipts need separate implementation design/review. Do not extend legacy
   OHLCV compatibility implicitly or claim source authentication verifies a fit.
3. **Typed metric bridge:** direct public 4A metrics/comparison reuse is not a
   supported native API. Review an exact read-only metric-only bridge or another
   separately approved shared-kernel boundary before implementation; do not
   solve this by changing 4A contracts or cloning mathematics now. Scoring/status
   and accounting design can be reviewed independently of this deferred adapter.
4. **Required unresolved semantics:** retain raw associations/linkage; any required
   interpretation unresolved by source blocks scope completion. Resolving or
   enriching it requires a reviewed policy, not a new evaluation exclusion.
5. **Evidence/PIT:** anomaly evidence/root causes and historical availability
   remain unresolved. No new evidence threshold or publication time is invented;
   source-byte authentication does not unblock Lane B or trading.
6. **Historical execution/reporting:** training/candidate/test orchestration,
   persisted receipt/build validation, actual model execution provenance,
   reporting, publication and dashboard integration remain deferred and need
   separate authorization. Do not map an unexecuted scope into model ledgers.

No change to approved evaluation semantics was required to prepare this design.
If implementation would require such a change, stop for explicit protocol
review rather than selecting a new rule. Proposed module/test filenames and
exact executable schema/serializer/capability implementations still require
separate review under the bounded approvals. No executable file, dependency,
historical artifact or other document is changed here.

## 15. Architecture Decision Record

Architect Design Review is **APPROVED WITH BOUNDED DEFERRALS**. The final
dispositions below replace the proposal-stage 5F recommendations, not inherited
contract history. Approval of architecture or design in principle does not
approve executable interfaces, implementation, producer authority or historical
execution. Deferred decisions remain unresolved and unauthorized.

| ADR | Disposition | Decision / remaining gate |
| --- | --- | --- |
| Inherited ADR-5B-01/02 | **APPROVED DESIGN** | Endpoint-only legacy Quality scope and Strict Fail-Closed v1 remain unchanged. No unsupported-token conversion or scope shrinkage. |
| Inherited ADR-5D-01/02/03/05 | **APPROVED DESIGN** | Separate native vocabulary, independent legacy compatibility, no execution unblock and unresolved-record preservation constrain 5F. |
| Inherited ADR-5D-04 | **APPROVED IN PRINCIPLE** | Native identity design; implemented 5E canonical/binding guarantees and their process-local limits remain separate evidence, not 5F authority. |
| Inherited ADR-5D-06 / ADR-5B-04 | **DEFERRED — inherited record** | Earlier deferral remains recorded in unchanged parent contracts. This 5F review approves only native scoring/accounting architecture within the bounds below; historical reporting and execution remain deferred. |
| ADR-5F-01 | **APPROVED — Alternative B** | Native envelopes with shared pure helpers; no changes to 4A/4B/5A–5E contracts or executable implementation approval. |
| ADR-5F-02 | **APPROVED IN PRINCIPLE — Native schema/policy/identity** | Source-bound immutable record and identity architecture; exact schema, serializer and canonicalization implementation/verification require separate review. |
| ADR-5F-03 | **APPROVED IN PRINCIPLE — Forecast/outcome capability separation** | Separate forecast-only identity/input and closure-gated outcome capability; executable issuance/resolution is unapproved, and authority/producer receipts remain deferred under ADR-5F-07. |
| ADR-5F-04 | **APPROVED DESIGN — Native scoring semantics** | Immutable forecasts; unchanged statuses, sample masks, reason precedence and strict closure. Native scoring never fits or forecasts; no new pending state or token-derived exclusion. |
| ADR-5F-05 | **APPROVED DESIGN — Full-universe accounting** | Preserve declared versus actually executed origins, genuine abstentions, scope blocks and not-run/interrupted execution. Reconcile completed authorized scopes only; never fabricate forecast/score rows. |
| ADR-5F-06 | **DEFERRED — Typed metric bridge** | Exact metric-only type bridge/native comparison adapter; no current native metrics API or guard bypass. |
| ADR-5F-07 | **DEFERRED — Execution authority, producer receipts and persistence** | Exact authority/receipt and restart/persistent artifact validation interfaces require separate review; source authentication is not model-execution proof and process-local checks are not persistent protection. |
| ADR-5F-08 | **DEFERRED — Historical reporting, execution and trading** | Historical reporting/publication/dashboard integration, execution and trading remain outside this approval. Separate review and Project Owner authority required. |

Alternatives A/C are not selected under approved Alternative B; no separate
**REJECTED** disposition or contract amendment is invented. ADR-5F-06–08 remain
deferred, and the in-principle approvals require separate executable-interface
review. Documentation finalization grants no implementation, historical
fitting/forecasting/scoring/accounting/evaluation, reporting, trading or Git
staging/commit/push authorization. **PQTA-003D-5F — DESIGN APPROVED,
IMPLEMENTATION NOT AUTHORIZED.** Stop after documentation finalization.
