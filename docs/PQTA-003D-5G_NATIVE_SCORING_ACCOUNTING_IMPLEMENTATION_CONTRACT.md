# PQTA-003D-5G — Native Scoring and Accounting Implementation Contract

**Status: Approved Design — Implementation Not Authorized**

Design baseline: `1c59a488bce98991e109cf89bebd39b519acabf7`, branch
`main`. Authority for this milestone is design only. Nothing here authorizes
production code, executable tests, historical fitting or prediction, scoring,
accounting execution, metrics, reporting, publication, backtesting, signals,
orders, Git staging, commit, or push.

All APIs, records, schemas, serializers, factories, and exceptions introduced
by this document are **PROPOSED — NOT IMPLEMENTED**. Existing 4A–5F code and
contracts remain unchanged. If implementing this contract would require a new
evaluation rule, reason precedence, sample rule, status, target definition, or
period boundary, implementation must stop for protocol review.

## 1. Executive Summary

This Architect-reviewed contract refines the approved 5F Alternative B into exact, reviewable
historical-native record and validation boundaries. It keeps the existing
authenticated historical source and lossless native anomaly representation on
the audit side, issues a narrow identity-only forecast reference, and permits
target-bearing outcome access only through a separate theoretical-closure gate.
An immutable forecast-shaped record and a closed outcome view can be classified
by a pure, data-only native scorer for synthetic verification. That classifier
does not authenticate either record and cannot issue an authenticated historical
score. A separate pure accountant reconciles exact identities and conservation
without asserting that historical execution completed. The future wrappers that
could issue authenticated historical scores or completed historical accounting
remain deferred.

The proposed scorer never fits, predicts, tunes, recalculates a target, mutates
a forecast, or reads a pre-closure outcome. The proposed accountant never
fabricates absent decisions. Source authentication does not prove model
execution, a digest does not authenticate a producer, and serialized bytes do
not recreate a live capability. Producer authority, persistent execution
receipts, execution-instance issuance, the typed metric bridge, historical
execution, reporting, dashboard
integration, and trading all remain deferred.

Every proposed final native record preserves:

```json
{
  "execution_ready": false,
  "point_in_time_verified": false,
  "decision_eligible": false
}
```

No performance result is created by this design.

## 2. Verified Existing Contracts

The source implementations, governing documents, and relevant tests were read
at the approved baseline. This table describes implemented behavior only.

| Existing boundary | Verified implementation | Constraint on 5G |
| --- | --- | --- |
| [Evaluation protocol](../src/quant/research/evaluation_protocol.py) | Zero-offset aware hourly datetimes are UTC-equivalent; period, method, sample, closure, forecast/score status, and count validators are pure. | Reuse public scalar validators unchanged. Do not create a pending status or move a period boundary. |
| [Forecast accounting](../src/quant/research/forecast_accounting.py) | `Forecast` has only `emitted`/`abstained`; `Score` has the three approved final statuses; reason order is centralized; `Accounting` requires exact typed 4A rows. | Reuse identity, finite-number, reason-order, and count rules. Do not widen 4A containers or call them historical authentication records. |
| [Evaluation reporting](../src/quant/research/evaluation_reporting.py) | Timestamp-set digests and metric mathematics are pure, but public metrics/comparison APIs require 4A types; reporting evidence is synthetic-only. | Reuse timestamp digest only on exact scored origins. Typed metrics/reporting remain deferred. |
| [Synthetic coordinator](../src/quant/research/model_evaluation.py) | `run_synthetic` accepts only typed synthetic fixtures, keeps outcome access after closure, and prohibits selected-alpha replay outside Test. | Do not add a historical bridge or relabel native records as synthetic. |
| [5A adapter](../src/quant/research/historical_adapter.py) | Pinned source bytes, schemas, identities, source rows, target reasons, and anomaly collections are audited read-only. | Use the verified source chain; an in-memory adapter alone is not authenticated history. |
| [5C projection](../src/quant/research/historical_projection.py) | Private process registration binds exact source records; opaque references are data-only; strict legacy projection remains fail-closed on unsupported fields. | Reuse source identity and binding concepts without changing legacy compatibility. |
| [5E representation](../src/quant/research/historical_representation.py) | Native occurrences preserve literal tokens, roles, order, multiplicity, raw values, linkage, and independent audit dimensions. Pre-closure and audit-only results expose no envelope. | A closed envelope is necessary but not sufficient for scoring; required semantic/linkage integrity must also pass. |
| [5F approved design](PQTA-003D-5F_HISTORICAL_SCORING_ACCOUNTING_DESIGN.md) | Alternative B, immutable forecasts, closure-gated outcomes, native score semantics, and exact full-universe reconciliation are approved as design. Authority, metrics, persistence, reporting, execution, and trading are deferred. | 5G specifies record and validation contracts only; it does not implement or authorize them. |

The governing research semantics remain
[QNT-003B](QNT-003B_EVALUATION_PROTOCOL.md) and
[QNT-003D](QNT-003D_FINAL_RESEARCH_DESIGN.md). The historical boundaries remain
[5A](PQTA-003D-5A_HISTORICAL_ADAPTER.md),
[5B](PQTA-003D-5B_HISTORICAL_PROJECTION_POLICY.md),
[5D](PQTA-003D-5D_UNSUPPORTED_ANOMALY_REPRESENTATION.md),
[5E](PQTA-003D-5E_IMPLEMENTATION_CONTRACT.md), and
[MODEL_EVALUATION](MODEL_EVALUATION.md).

Existing tests establish useful prior evidence, not 5G implementation:

- `test_evaluation_protocol.py` covers UTC equivalence, closure, final statuses,
  sample rules, and conservation.
- `test_forecast_accounting.py` covers forecast immutability, reason precedence,
  A-primary/A-sensitivity score differences, exact counts, and no silent drops.
- `test_evaluation_reporting.py` covers exact timestamp intersections, status
  precedence, blocked Ridge comparison behavior, and digest syntax versus byte
  verification.
- `test_model_evaluation.py` covers pre-closure isolation, gap-safe AR history,
  Test-only Ridge replay, failed-refit handling, and empty universes.
- `test_historical_projection.py` and `test_historical_representation.py` cover
  pinned binding, literal anomaly retention, exact closure, audit-only origins,
  process-local integrity limits, and unchanged synthetic/reporting guards.

## 3. Scope and Authorization

### 3.1 In scope

- Exact immutable native record schemas and validation rules.
- Data-only identity references versus live authority-bearing capabilities.
- Forecast, closed-outcome, scoring, and accounting invariants.
- Exact immutable-origin-ledger universe and parent/child identity invariants.
- Canonical serialization and identity requirements for future implementation.
- A threat model and synthetic future-test specifications.
- A staged implementation proposal with separate approval gates.

### 3.2 Out of scope

- Any Python implementation or executable test.
- A model coordinator, model execution authority, or producer receipt issuer.
- Historical fitting, alpha selection, forecasting, scoring, reconciliation,
  metric computation, report generation, artifact publication, or UI changes.
- Changes to source datasets, manifests, immutable artifacts, 4A/4B/5A–5F
  contracts, model mathematics, split boundaries, or reason priorities.
- Point-in-time claims, trading backtests, signals, confidence, or orders.

### 3.3 Authority layers

The design keeps four independent facts:

1. **Source authentication:** exact pinned source bytes were read and bound by
   the existing trusted audit-side factory.
2. **Execution authority:** a separately reviewed coordinator was permitted to
   invoke a named producer for an exact scope. This remains deferred.
3. **Execution evidence:** that producer actually completed a particular
   immutable forecast decision. This remains deferred.
4. **Outcome authority:** a registered audit-side reader passed the theoretical
   closure and native integrity gates for one exact source row. This is proposed
   but not implemented.
5. **Completion authority:** a separately validated execution instance proved
   that every declared decision and score in a scope completed. Its issuer and
   validator remain deferred.

No Boolean, hash, JSON field, source receipt, prediction, or fit-shaped object
may substitute for a missing authority layer.

## 4. Approved Architecture

The approved 5F Alternative B is retained:

```text
IMPLEMENTED AUDIT SIDE
5A authenticated source -> 5C bound records -> 5E native representation
                                                    |
PROPOSED, NOT IMPLEMENTED                            |
                     +------------------------------+
                     |
             native contract boundary
                     |
        +------------+-------------+
        |                          |
        v                          v
identity-only forecast ref    closed-outcome gate
        |                          |
future authorized producer         v
        |                   outcome capability
        +------------+-------------+
                     |
          pure data-only classifier
                     |
       pure accounting reconciliation
                     |
        data-only validation results
                     X
 historical scoring/completion wrappers deferred
                     X
       metrics/reporting/execution deferred
```

`NativeSource`, `SourceBinding`, complete historical rows, manifests, outcome
readers, and capabilities stay coordinator/audit-side. A predictor receives an
already issued allowlisted input view and separately admitted completed history;
it cannot request arbitrary origins, resolve outcomes, or mint capabilities.

Serialized records are data. A deserialized origin, forecast, outcome receipt,
or score is untrusted until a future reader reauthenticates source bytes and
validates every binding. Deserialization never registers an object in a private
capability registry.

### 4.1 Proposed module and API boundary

All signatures below are **PROPOSED — NOT IMPLEMENTED**. The pure data and
validation functions are candidates for Stages A–C. The audit-side factories
and historical wrappers are deferred to Stage D and cannot be made callable by
implementing only Stages A–C.

```python
# Proposed pure Stage A data/identity boundary.
def validate_provenance(value: HistoricalProvenanceRef) -> None: ...
def validate_origin(value: HistoricalOriginRef) -> None: ...
def validate_scope(value: HistoricalScopeSpec) -> None: ...
def validate_forecast(value: HistoricalForecast) -> None: ...
def validate_score(value: HistoricalScore,
                   *, parent: HistoricalForecast,
                   scope: HistoricalScopeSpec) -> None: ...
def validate_reconciliation(value: AccountingReconciliation) -> None: ...
def validate_accounting_result(value: HistoricalAccountingResult,
                               *, reconciliation: AccountingReconciliation
                               ) -> None: ...
def canonical_scoring_payload(value: object) -> bytes: ...
def scoring_spec_id(spec: Mapping[str, object]) -> str: ...
def scoring_build_id(spec_id: str, *, code_sha256: str,
                     dependency_versions: Mapping[str, str],
                     serializer_version: str,
                     deterministic_build_configuration: Mapping[str, object]
                     ) -> str: ...

# Proposed pure Stage B/C kernels; synthetic tests call these without
# manufacturing historical authentication.
def classify_native_score(forecast: HistoricalForecast,
                          outcome: HistoricalOutcomeView,
                          *, sample_policy: str) -> ScoreClassification: ...
def reconcile_native_accounting(scope: HistoricalScopeSpec, *, model_id: str,
                                sample_policy: str,
                                forecasts: tuple[HistoricalForecast, ...],
                                score_classifications: tuple[ScoreClassification, ...]
                                ) -> AccountingReconciliation: ...

# Deferred Stage D audit-side factories/wrappers. These require separately
# approved live authority and producer receipt contracts.
def open_verified_native_source(root: Path) -> HistoricalAuditSession: ...
def issue_origin_ref(session: HistoricalAuditSession,
                     scope: HistoricalExecutionScope,
                     origin: datetime) -> HistoricalOriginRef: ...
def issue_closed_outcome(reader: HistoricalOutcomeReader,
                         ref: HistoricalOriginRef, *, checked_at: datetime
                         ) -> ClosedHistoricalOutcomeRef | OutcomeBoundaryResult: ...
def score_historical(scorer: HistoricalScorer,
                     forecast: HistoricalForecast,
                     outcome: ClosedHistoricalOutcomeRef,
                     *, checked_at: datetime) -> HistoricalScore: ...
def complete_historical_accounting(
    completer: HistoricalAccountingCompleter,
    reconciliation: AccountingReconciliation,
    execution: ValidatedExecutionCompletion,
) -> HistoricalAccountingResult: ...
```

`ScoreClassification`, `HistoricalAuditSession`, `HistoricalExecutionScope`,
`HistoricalOutcomeReader`, `OutcomeBoundaryResult`, `HistoricalScorer`,
`HistoricalAccountingCompleter`, and `ValidatedExecutionCompletion` are
proposed support types, not importable interfaces. `ScoreClassification` and
`AccountingReconciliation` are pure data-only results and carry no source,
producer, execution, or completion authentication claim. Only the deferred
wrappers may combine them with live source, producer, execution-instance, and
completion authority to produce `HistoricalScore` or
`HistoricalAccountingResult`. The model
coordinator, execution-scope issuer, producer/refit receipt issuer, artifact
writer, metric bridge, and reporter are deliberately absent.

## 5. Native Record Schemas

All records below are **PROPOSED — NOT IMPLEMENTED**. The future Python forms
are frozen dataclasses. Tuple order is significant unless a field explicitly
requires canonical sorting. Booleans are exact `bool`, integers reject `bool`,
numeric values reject `bool`, NaN, and infinity. All clock fields are aware,
hour-aligned, zero-offset datetimes unless explicitly identified as processing
timestamps. Unknown fields and unknown enum values fail closed.

The proposed identities retain the names introduced by the approved 5F design:

```text
SCHEMA_VERSION = pqta-historical-scoring-accounting-v1
POLICY_VERSION = pqta-003d-5f-scoring-accounting-v1
SERIALIZER_VERSION = pqta-003d-5f-canonical-v1
```

They do not replace or revise the 5C/5E serializer identities. Their exact
implementation remains subject to Architect review.

### 5.0 Parent/child identity validation

Validation recomputes identities from canonical inputs; it never trusts copied
fields. For every future authenticated historical chain, all three identities
are non-null where applicable and satisfy:

```text
scope.scoring_spec_id
  == forecast.scoring_spec_id
  == score.scoring_spec_id
  == accounting.scoring_spec_id

forecast.scoring_build_id
  == score.scoring_build_id
  == accounting.scoring_build_id

forecast.execution_instance_id
  == score.execution_instance_id
  == accounting.execution_instance_id
```

The score's `forecast_id` must identify its exact parent forecast. Its outcome
digest and `origin_ref` must identify the exact closed view for the same source
row. Accounting must contain exactly one forecast and one final score for each
declared `(source identity, period, origin, model, sample)` key, and every child
key must be in the scope's immutable ledger-derived identity set. Any mismatch
fails closed even when counts or individual SHA-256 strings are syntactically
valid. These consistency checks establish data integrity only; they do not
authenticate producer execution or completion.

### 5.1 `HistoricalProvenanceRef`

Data-only source and contract identity; it grants no authority.

| Field | Python type | Requirement |
| --- | --- | --- |
| `dataset_spec_id` | `str` | Required lowercase SHA-256; exact origin-dataset logical identity. |
| `source_artifact_build_id` | `str` | Required lowercase SHA-256; immutable PQTA-003C build identity. |
| `silver_sha256` | `str` | Required lowercase SHA-256 of pinned Silver bytes. |
| `gold_sha256` | `str` | Required lowercase SHA-256 of pinned Gold bytes. |
| `origin_ledger_sha256` | `str` | Required lowercase SHA-256. |
| `dataset_validation_sha256` | `str` | Required lowercase SHA-256. |
| `provenance_json_sha256` | `str` | Required lowercase SHA-256. |
| `provenance_sidecar_sha256` | `str` | Required lowercase SHA-256. |
| `manifest_canonical_sha256` | `str` | Required lowercase SHA-256. |
| `manifest_raw_sha256` | `str` | Required lowercase SHA-256 of observed raw manifest bytes. |
| `manifest_version` | `str` | Required nonempty exact source value. |
| `feature_version` | `str` | Required nonempty exact source value. |
| `feature_order` | `tuple[str, ...]` | Required exact seven-feature contract order. |
| `protocol_version` | `str` | Exactly `qnt-003d-design-v1`. |
| `dataset_contract_version` | `str` | Exactly `pqta-003b-origin-ledger-v1`. |
| `projection_policy_version` | `str` | Exactly `pqta-003d-5b-projection-v1`. |
| `native_schema_version` | `str` | Exactly `pqta-historical-anomaly-representation-v1`. |
| `native_policy_version` | `str` | Exactly `pqta-003d-5d-representation-v1`. |
| `native_serializer_version` | `str` | Exactly `pqta-003d-5e-canonical-v1`. |
| `source_receipt_sha256` | `str` | Required lowercase SHA-256 of the registered 5C receipt. |
| `source_mode` | `Literal["authenticated_pinned_history", "synthetic_fixture"]` | Exact mode; synthetic never upgrades. |

Identity and equality use every field. Construction validates syntax and
cross-version consistency; only a private factory can associate it with a live
source registration. Canonical JSON uses these exact snake-case keys. Reject
missing/extra keys, changed feature order, an unapproved version, duplicate
hash roles, or a source receipt inconsistent with the registered source.

### 5.2 `HistoricalOriginRef`

Data-only identity for one source-bound forecast origin.

| Field | Python type | Requirement |
| --- | --- | --- |
| `provenance` | `HistoricalProvenanceRef` | Required exact source identity. |
| `exchange` | `Literal["binance"]` | Required. |
| `symbol` | `Literal["BTC/USDT"]` | Required. |
| `timeframe` | `Literal["1h"]` | Required. |
| `source_identifier` | `str` | Required nonempty original ledger identifier; no absolute workstation path in a published form. |
| `source_row_index` | `int` | Required nonnegative, non-Boolean original index. |
| `origin` | `datetime` | Required approved UTC forecast origin. |
| `feature_open_t` | `datetime` | Exactly `origin - 1h`. |
| `target_theoretical_close_at` | `datetime` | Exactly `origin + 1h`. |
| `period_id` | `Literal["training_history", "validation", "test", "outside_approved_evaluation_window"]` | Must equal the existing split helper. |

Identity and equality use every field. The canonical object contains no target,
validity flag, endpoint anomaly, row payload, row digest, resolver, registry
token, or capability. Reject a wrong row/index/key/split, non-hour timestamp,
unbound origin, or copied reference whose live source binding does not match.

### 5.3 `HistoricalScopeSpec`

Data-only declaration, not permission to execute.

| Field | Python type | Requirement |
| --- | --- | --- |
| `provenance` | `HistoricalProvenanceRef` | Required authenticated-source identity for historical scopes; explicit synthetic mode is allowed only for pure contract verification and cannot establish historical completion. |
| `scoring_spec_id` | `str` | Required recomputed logical scoring-spec SHA-256; binds this scope and every child record. |
| `period_id` | `Literal["training_history", "validation", "test"]` | One approved split only. |
| `start` | `datetime` | Required exact split start for a full historical scope. |
| `end_exclusive` | `datetime` | Required exact split end; `start <= end`. |
| `analysis_as_of` | `datetime` | Required fixed `2026-10-20T13:00:00Z`. |
| `intended_use` | `Literal["training_history_accounting", "validation_candidate_tuning_diagnostics", "test_frozen_alpha_comparison"]` | Must match period. |
| `origins` | `tuple[HistoricalOriginRef, ...]` | Required sorted unique evaluation identities taken verbatim from the approved immutable origin ledger for the split. |
| `origin_set_sha256` | `str` | Existing canonical UTC timestamp digest over `origins`; recomputed, never trusted. |
| `source_origin_identity_set_sha256` | `str` | Canonical digest over each exact `(dataset_spec_id, source_artifact_build_id, source_identifier, source_row_index, origin, period_id)` identity; recomputed from the approved ledger. |
| `model_ids` | `tuple[str, ...]` | Required canonical subset/order of the four approved methods; full requested comparison cannot silently shrink. |
| `sample_policies` | `tuple[Literal["a_primary", "a_sensitivity"], ...]` | Required canonical order, no duplicate. |
| `audit_only_origins` | `tuple[HistoricalOriginRef, ...]` | Separate sorted identities; never evaluation-scheduled. |

Equality uses every field. The approved immutable origin ledger is the sole
source of the historical evaluation universe. Calendar boundaries validate the
ledger's period assignments; generated hourly timestamps and count equality do
not replace the ledger identity set. A full historical scope requires exact
source-ledger identity-set equality, including explicit missing-hour,
target-invalid, feature-invalid, anomalous, unrepresentable, and unscorable
origins. Audit-only ledger identities remain only in `audit_only_origins` and
must be disjoint from `origins`. A scope assessment may reject or block a scope,
but cannot filter either set. Empty scopes are allowed only for synthetic
contract tests and cannot prove completed historical evaluation.

### 5.4 `HistoricalForecast`

Immutable data record declaring one completed model decision. In pure synthetic
or data-only use it is untrusted input; it is not model-execution proof unless a
future separately approved producer receipt and execution instance validate it.

| Field | Python type | Requirement |
| --- | --- | --- |
| `schema_version` | `Literal["pqta-historical-scoring-accounting-v1"]` | Required. |
| `scoring_spec_id` | `str` | Required recomputed SHA-256; exactly equals the parent scope. |
| `scoring_build_id` | `str` | Required recomputed implementation/build SHA-256. Multiple forecast payloads may share it. |
| `execution_instance_id` | `str \| None` | Null for pure synthetic/data-only use; required future immutable identity for authenticated historical issuance. Syntax alone grants no authority. |
| `origin_ref` | `HistoricalOriginRef` | Required in-split identity. |
| `model_id` | `Literal["zero_return", "expanding_mean", "ar_1", "ridge_7"]` | Required. |
| `sample_policy` | `Literal["a_primary", "a_sensitivity"]` | Required. |
| `forecast_status` | `Literal["emitted", "abstained"]` | No other value. |
| `prediction` | `float \| None` | Finite non-Boolean float when emitted; null when abstained. |
| `abstention_reasons` | `tuple[str, ...]` | Empty when emitted; nonempty approved method/sample reasons in existing deterministic order when abstained. |
| `producer_trace_ref` | `str` | Required nonempty data-only identifier; future validation must resolve it through deferred producer authority. |
| `model_version` | `str` | Required nonempty implementing model-contract identifier. |
| `history_count` | `int` | Required nonnegative, non-Boolean; zero for Zero Return. |
| `history_cutoff` | `datetime \| None` | Maximum admitted theoretical outcome close; null only when no history applies. Must be `<= origin`. |
| `scheduled_refit_at` | `datetime \| None` | Required for AR/Ridge forecast decisions; UTC midnight and not after origin. Null for Zero/Mean. |
| `fit_ref` | `str \| None` | Required for successful AR/Ridge emissions; absent for Zero/Mean and failed/cold-start abstentions. |
| `alpha_selection_ref` | `str \| None` | Required for Ridge Test emissions; null for all other methods. |
| `selected_alpha` | `float \| None` | Required approved finite alpha for Ridge Test emissions and must match frozen selection; otherwise null. |
| `forecast_id` | `str` | SHA-256 of the canonical forecast payload with `forecast_id` omitted. |

`emitted` requires a finite prediction and no abstention reason. `abstained`
requires null prediction and approved ordered reasons. Zero Return must emit
exactly `0.0`. A source, authority, representation, or lifecycle block is not a
model abstention. Target value, validity, endpoint anomalies, and scoreability
are forbidden fields and cannot influence issuance. Equality uses the complete
validated record including `forecast_id`; the ID is recomputed. After issuance
no field can change. A deterministic digest is not proof that the model ran.

### 5.5 `ClosedHistoricalOutcomeRef`

Live authority-bearing capability, issued only by a future private audit-side
factory after exact closure and binding validation.

| Field | Python type | Requirement |
| --- | --- | --- |
| `origin_ref` | `HistoricalOriginRef` | Exact bound source row. |
| `checked_at` | `datetime` | Required UTC hour, `>= target_theoretical_close_at`. |
| `theoretical_close_at` | `datetime` | Exactly `origin + 1h`. |
| `native_result_sha256` | `str` | Recomputed digest of the validated closed native result. |
| `outcome_view_sha256` | `str` | Recomputed digest of the exact outcome view. |
| `capability_nonce` | private opaque object | Process-private membership token; never serialized. |

Use `@dataclass(frozen=True, eq=False)` and a private weak registry. Equality is
object/capability identity, not field equality. Public construction, copying,
replacement, pickling, and JSON deserialization do not register authority. Its
canonical **descriptor** contains the five data fields above except the private
nonce and is explicitly labeled `untrusted_closed_outcome_descriptor`; loading
that descriptor never returns a `ClosedHistoricalOutcomeRef`.

Reject a synthetic or unregistered source, wrong source row/index/origin,
changed receipt/manifest binding, pre-closure access, audit-only origin,
non-represented native result, unresolved required association/linkage, or
tampered digest. Pre-closure results expose safe identity/clocks only and are
not instances of this type.

### 5.6 `HistoricalOutcomeView`

Immutable post-closure data-only view. The historical form is retained behind
the live capability; an explicitly synthetic form may be constructed only for
pure classifier verification and cannot be upgraded to historical authority.

| Field | Python type | Requirement |
| --- | --- | --- |
| `origin_ref` | `HistoricalOriginRef` | Exact source identity. |
| `target` | `float \| None` | Finite non-Boolean value iff valid; otherwise null. |
| `target_valid` | `bool` | Exact source flag. |
| `original_invalid_reasons` | `tuple[str, ...]` | Exact lexical source order. |
| `ordered_invalid_reasons` | `tuple[str, ...]` | Same set normalized by existing target priority. |
| `target_primary_null_reason` | `str \| None` | First ordered reason iff invalid; null iff valid. |
| `target_manifest_anomaly` | `bool` | Exactly whether endpoint occurrences exist. |
| `target_value_sensitive` | `bool \| None` | Exact source value when present; null means not asserted, never recomputed. |
| `target_endpoint_occurrences` | `tuple[NativeOccurrence, ...]` | Exact original order/multiplicity and endpoint role. |
| `feature_window_occurrences` | `tuple[NativeOccurrence, ...]` | Exact original order/multiplicity and window role. |
| `unresolved_occurrences` | `tuple[NativeOccurrence, ...]` | Exact original order/multiplicity and unresolved role. |
| `anomaly_evidence_status` | `Literal["no_occurrences", "recorded_references_unverified"]` | No invented verification. Unresolved linkage blocks issuance rather than entering this successful view. |
| `source_authentication` | `Literal["authenticated_pinned_history", "synthetic_fixture"]` | Pure classifier accepts explicit synthetic fixtures; deferred historical wrapper accepts only authenticated pinned mode. Neither literal authenticates itself. |
| `native_schema_version` | `str` | Exact approved native schema. |
| `native_policy_version` | `str` | Exact approved native policy. |
| `theoretical_close_at` | `datetime` | Exactly `origin + 1h`. |
| `checked_at` | `datetime` | At or after close. |
| `closure` | `Literal["closed"]` | Required. |
| `native_envelope_sha256` | `str` | Recomputed digest of complete lossless envelope. |

The complete `NativeEnvelope` remains audit-side and source-bound. The canonical
view includes every occurrence's raw mapping, linkage, manifest indices and
evidence references; no token is translated. A valid target cannot be null or
nonfinite and has no invalid reasons. An invalid target is null with at least one
known source reason. Contradictory state is an integrity error.

### 5.7 `ScoreClassification`

Pure data-only output of `classify_native_score`; synthetic verification is
allowed. This record is not an authenticated historical score and contains no
producer or completion claim.

| Field | Python type | Requirement |
| --- | --- | --- |
| `origin_ref` | `HistoricalOriginRef` | Exact data identity shared by the inputs. |
| `model_id` | approved model literal | Exact forecast value. |
| `sample_policy` | approved sample literal | Exact forecast value. |
| `forecast_status` | approved forecast literal | Copied unchanged. |
| `score_status` | approved final score literal | Derived only by the existing rules. |
| `prediction` | `float \| None` | Exact forecast value. |
| `target` | `float \| None` | Exact outcome value when scored; otherwise null. |
| `abstention_reasons` | `tuple[str, ...]` | Exact immutable forecast reasons. |
| `original_target_reasons` | `tuple[str, ...]` | Exact source lexical order. |
| `score_exclusion_reasons` | `tuple[str, ...]` | Existing total priority order. |
| `primary_score_reason` | `str` | First exclusion reason, or `scored`. |
| `all_diagnostics` | `tuple[str, ...]` | Ordered exclusions plus approved overlapping diagnostics. |

It has no `score_id`, authentication flag, execution-completion flag, or
capability. Supplying hash-shaped strings cannot upgrade it. The deferred
`score_historical` wrapper must independently revalidate the live forecast,
closed-outcome capability, producer authority, and execution instance before it
may copy this classification into a `HistoricalScore`.

### 5.8 `HistoricalScore`

Immutable final classification for one forecast/outcome pair.

| Field | Python type | Requirement |
| --- | --- | --- |
| `schema_version` | `Literal["pqta-historical-scoring-accounting-v1"]` | Required. |
| `scoring_spec_id` | `str` | Required; exactly equals parent scope and forecast. |
| `scoring_build_id` | `str` | Required; exactly equals the forecast and accounting build. |
| `execution_instance_id` | `str` | Required future immutable execution-instance identity; exactly equals the authenticated forecast execution. |
| `forecast_id` | `str` | Exact recomputed immutable forecast digest. |
| `outcome_view_sha256` | `str` | Exact digest bound by the live outcome capability. |
| `origin_ref` | `HistoricalOriginRef` | Must match forecast and outcome exactly. |
| `model_id` | approved model literal | Must match forecast. |
| `sample_policy` | approved sample literal | Must match forecast. |
| `period_id` | approved in-split period literal | Must match origin. |
| `checked_at` | `datetime` | At or after target theoretical close. |
| `forecast_status` | `Literal["emitted", "abstained"]` | Copied unchanged from forecast. |
| `score_status` | `Literal["scored", "emitted_but_not_scored", "not_scored_no_forecast"]` | Existing final vocabulary only. |
| `prediction` | `float \| None` | Exact forecast value; never repaired. |
| `target` | `float \| None` | Exact outcome value; finite only when scored. |
| `abstention_reasons` | `tuple[str, ...]` | Exact immutable forecast reasons. |
| `original_target_reasons` | `tuple[str, ...]` | Exact source lexical order. |
| `score_exclusion_reasons` | `tuple[str, ...]` | Existing total priority order, no duplicate. |
| `primary_score_reason` | `str` | First exclusion reason, or `scored`. |
| `all_diagnostics` | `tuple[str, ...]` | Ordered exclusions plus `unknown_historical_availability`; overlaps retained. |
| `score_id` | `str` | SHA-256 of canonical score payload with `score_id` omitted. |

Identity is `(scoring spec, scoring build, execution instance, source, period,
origin, model, sample, forecast_id, outcome_view_sha256)`. Reject any parent or
child identity mismatch, cross-source/method/sample/period substitution,
pre-closure use, mutated emission, unknown/duplicate reasons, wrong precedence,
or inconsistent value/status combinations. Hash syntax or equality does not
authenticate the producer or execution.

### 5.9 `AccountingReconciliation`

Pure data-only output of `reconcile_native_accounting`. It validates an exact
declared identity set and arithmetic; it does not assert that a historical model
ran or that the supplied records were issued by an authorized producer.

| Field | Python type | Requirement |
| --- | --- | --- |
| `scoring_spec_id` | `str` | Exact parent scope identity. |
| `scoring_build_id` | `str` | Exact common build across supplied forecasts/classifications. |
| `scope` | `HistoricalScopeSpec` | Exact declared non-audit ledger universe. |
| `model_id` | approved model literal | One method. |
| `sample_policy` | approved sample literal | One sample. |
| `forecast_ids` | `tuple[str, ...]` | Exact origin order, one per declared origin. |
| `classification_keys` | `tuple[str, ...]` | Exact canonical keys, one per declared origin. |
| `counts_and_reasons` | immutable canonical mapping | Exact counts, exclusive and overlapping reasons, and conservation values specified in §9. |
| `scored_origins` | `tuple[datetime, ...]` | Sorted unique data-only scored set. |
| `scored_timestamp_set_sha256` | `str` | Recomputed existing timestamp-set digest. |
| `historical_execution_verified` | `Literal[False]` | Always false for the pure result. |
| `reconciliation_id` | `str` | Digest of this canonical data-only record with this field omitted. |

Exact key-set equality and parent/child spec/build consistency are mandatory.
An `AccountingReconciliation` cannot be relabeled or serialized as completed
historical accounting.

### 5.10 `HistoricalAccountingResult`

Produced only for a completed authorized scope; it is not an evaluation report.

| Field | Python type | Requirement |
| --- | --- | --- |
| `schema_version` | scoring schema literal | Required. |
| `scoring_spec_id` | `str` | Required recomputed logical specification SHA-256. |
| `scoring_build_id` | `str` | Required recomputed build SHA-256. |
| `execution_instance_id` | `str` | Required future immutable execution-instance identity validated by the deferred completion authority. |
| `execution_completion_ref` | `str` | Required future data reference validated against live completion authority; never self-authenticating. |
| `scope` | `HistoricalScopeSpec` | Exact declared non-audit universe. |
| `model_id` | approved model literal | One method. |
| `sample_policy` | approved sample literal | One sample. |
| `forecast_ids` | `tuple[str, ...]` | Exact origin order, one per declared origin. |
| `score_ids` | `tuple[str, ...]` | Exact origin order, one per declared origin. |
| `origin_count` | `int` | Full declared universe. |
| `forecast_count` | `int` | Emitted count. |
| `abstention_count` | `int` | Genuine model abstentions. |
| `scored_count` | `int` | Final scored rows. |
| `emitted_but_not_scored_count` | `int` | Final unscored emissions. |
| `not_scored_no_forecast_count` | `int` | Final abstentions. |
| `exclusive_abstention_reason_counts` | `tuple[tuple[str, int], ...]` | Canonical reason order; sums to abstentions. |
| `primary_score_reason_counts` | `tuple[tuple[str, int], ...]` | Exclusive final funnel; plus scored equals origins. |
| `overlapping_diagnostic_counts` | `tuple[tuple[str, int], ...]` | Canonical reason order; may exceed origins. |
| `forecast_coverage` | `float \| None` | Emitted/origins, null only for an allowed empty synthetic scope. |
| `scored_origins` | `tuple[datetime, ...]` | Sorted unique scored set. |
| `scored_timestamp_set_sha256` | `str` | Existing timestamp-set digest, recomputed. |
| `audit_only_origins` | `tuple[HistoricalOriginRef, ...]` | Preserved separately, never in counts/digest. |
| `reconciliation_id` | `str` | Exact pure reconciliation incorporated by the deferred wrapper. |
| `accounting_complete` | `Literal[True]` | Validated accounting fact only. |
| `research_only` | `Literal[True]` | Required. |
| `execution_ready` | `Literal[False]` | Required. |
| `point_in_time_verified` | `Literal[False]` | Required. |
| `decision_eligible` | `Literal[False]` | Required. |
| `accounting_id` | `str` | Digest of canonical accounting result with this field omitted. |

Equality uses all fields. Exact key-set equality is mandatory: counts alone are
insufficient. Every forecast and score must equal the result's scoring spec,
build, execution instance, source, scope, method, and sample. A partial, blocked,
not-run, interrupted, data-only, or merely hash-consistent execution cannot
construct this type. Construction requires the separately approved completion
wrapper, live producer authority, and validated execution completion; those
mechanisms are deferred.

### 5.11 `HistoricalScopeBlock`

Lifecycle/audit record, never a forecast or score.

| Field | Python type | Requirement |
| --- | --- | --- |
| `scope` | `HistoricalScopeSpec` | Exact requested declaration. |
| `classification` | `Literal["blocked", "failed"]` | Prerequisite/policy block versus integrity/interruption failure. |
| `execution_state` | `Literal["not_run", "interrupted"]` | Whether no decision ran or partial execution exists. |
| `diagnostic_codes` | `tuple[str, ...]` | Nonempty deterministic approved order; no model abstention code substitution. |
| `affected_origin_refs` | `tuple[HistoricalOriginRef, ...]` | Sorted unique audit identities; no source row discarded. |
| `executed_forecast_ids` | `tuple[str, ...]` | Actual immutable progress only; empty for not-run. |
| `finalized_score_ids` | `tuple[str, ...]` | Actual finalized progress only; subset consistent with forecasts. |
| `missing_origin_refs` | `tuple[HistoricalOriginRef, ...]` | Exact declared keys not completed. |
| `research_only` | `Literal[True]` | Required. |
| `execution_ready` | `Literal[False]` | Required. |
| `point_in_time_verified` | `Literal[False]` | Required. |
| `decision_eligible` | `Literal[False]` | Required. |
| `scope_block_id` | `str` | Digest of canonical scope-block record with this field omitted. |

`blocked/not_run` has no executed forecasts or scores. `failed/interrupted` may
retain actual immutable progress but cannot fabricate missing records or produce
completed accounting. Canonical equality uses every field. This record contains
no metrics. Allowed `(classification, execution_state)` pairs are
`(blocked, not_run)`, `(failed, not_run)`, and `(failed, interrupted)`; all other
pairs are rejected.

## 6. Forecast Contract

### 6.1 Status and value rules

Only these decisions exist:

```text
emitted  -> finite prediction, no abstention reasons
abstained -> null prediction, one or more approved ordered reasons
```

`pending`, `blocked`, `not_run`, and `projection_blocked` are not forecast
statuses. Source, authority, representation, or execution-scope failure returns
a scope/boundary record and does not create a forecast.

The identity tuple is exact source, scoring spec/build, execution instance,
period, origin, model, and
sample. The same origin under two samples is two decisions; the same timestamp
under another source/spec/build/execution instance is not interchangeable. The canonical forecast ID
binds the complete immutable payload but does not prove producer execution.

### 6.2 Issuance boundary

A future trusted coordinator must preissue the exact current-origin input view.
That view may contain only the existing allowlisted forecast fields, current
feature/lag quality masks, and source identity. It may not contain or resolve:

- current target value or validity;
- current target null reasons;
- endpoint anomalies or scoreability;
- a full historical row, native envelope, manifest, or row-content digest;
- a source/session/outcome capability; or
- another or future origin's input.

Producer history is separately admitted only after each label's theoretical
closure. The producer authority/receipt mechanism that proves a model call and
fit lineage remains deferred. Consequently, no caller-created forecast can yet
be called authenticated historical model output.

### 6.3 Immutability

After issuance, prediction, status, reasons, scoring spec/build, execution
instance, and producer trace are
frozen. Later outcome validity, anomaly flags, scoreability, checked-at clocks,
or reporting status cannot alter them. A changed field changes `forecast_id` and
is not the same forecast. No stale fit may be presented as a current fit after a
failed/skipped required midnight refit.

## 7. Closed Outcome Contract

For forecast origin `o`:

```text
theoretical_close = o + 1 hour
outcome access permitted only if theoretical_close <= checked_at
```

Before closure, the boundary may expose only `HistoricalOriginRef`, checked-at,
theoretical close, and classification `not_closed`. It must not traverse target
values, validity, reasons, endpoint/native anomaly records, attachments, or the
full-row content digest. Audit-only origins remain `audit_only` even after their
clock closes and never receive an outcome capability.

After closure, a private factory must verify, in order:

1. factory registration and authenticated pinned source mode;
2. unchanged receipt and raw/canonical manifest binding;
3. exact dataset/build/source file/row index/origin identity;
4. approved in-split period and known schema/policy versions;
5. `origin + 1h <= checked_at`;
6. unchanged bound row digest;
7. native core validity and representability;
8. required association and linkage integrity; and
9. exact outcome value/flag/reason/occurrence agreement.

Only then may it create `HistoricalOutcomeView` and register a
`ClosedHistoricalOutcomeRef`. A caller-supplied `authenticated=True`, digest,
receipt, source reference, or serialized descriptor is insufficient.

The exact runtime authority issuer and persistence/restart mechanism remain
deferred. This design specifies failure behavior but does not grant a usable
authority. Theoretical closure remains distinct from exchange publication or
observation availability.

## 8. Scoring Contract

`classify_native_score` is the pure data-only boundary. It consumes an
immutable forecast-shaped record, a closed outcome view, and the forecast's
already fixed sample policy. Synthetic fixtures may call it. It returns only a
`ScoreClassification`; it cannot authenticate a historical source, producer,
execution instance, outcome capability, or score.

`score_historical` is a separate deferred historical wrapper. Before producing
a `HistoricalScore`, it must reauthenticate the pinned source, validate the live
closed-outcome capability, verify producer and execution-instance authority,
recompute the scoring spec/build identities, run the pure classifier, and bind
the resulting classification to the exact forecast and outcome. No historical
wrapper is implemented or authorized by this document.

Rules are unchanged:

```text
abstained forecast
    -> not_scored_no_forecast

emitted + valid sample-eligible target
    -> scored

emitted + invalid or sample-excluded target
    -> emitted_but_not_scored
```

For A-primary, every valid finite target is eligible even when endpoint anomaly
records exist. For A-sensitivity, a valid target with any endpoint anomaly is
excluded only after closure. Feature-window-only anomalies do not create a
global target exclusion. They retain their existing AR/Ridge historical/current
input effects outside this scorer. Known endpoint `unknown` still triggers the
existing sensitivity exclusion; it is not translated to an OHLCV field.

Use existing `TARGET_REASON_PRIORITY`, `SCORE_PRIORITY`, `ordered_reasons`, and
method/sample forecast reason order. Preserve source lexical target reasons
separately. Do not implement another priority table. Add
`target_manifest_anomaly` only for A-sensitivity. Preserve
`unknown_historical_availability` as an overlapping diagnostic, not an exclusive
reason that erases valid Lane A research scoring.

Neither boundary may fit, predict, tune, select alpha, modify a forecast,
recalculate a target, infer numeric invalidity from anomaly tokens, or access an
outcome before closure. Malformed valid-null/nonfinite outcomes are integrity
errors, not silently removed rows.

## 9. Accounting Contract

The pure `reconcile_native_accounting` function validates, for one declared
period/method/sample scope:

```text
N_origins = N_emitted + N_abstained
N_emitted = N_scored + N_emitted_but_not_scored
N_abstained = N_not_scored_no_forecast
N_origins = N_scored + sum(primary_score_reason_counts)
sum(exclusive_abstention_reason_counts) = N_abstained
```

Exact source-ledger identity-set equality is required among declared origins,
forecast keys, and final classification keys. Reject missing, duplicate, extra, wrong-period,
wrong-model, wrong-sample, wrong-source, unauthorized-subset, or incomplete
records even if counts match.

Forecast coverage is `N_emitted / N_origins` using the full declared opportunity
universe, not valid targets, representable rows, or a common comparison subset.
Scored origins are sorted and unique; their digest uses the existing exact UTC
encoding. Audit-only origins are retained separately and never enter the
evaluation denominator.

Its output is `AccountingReconciliation`, which proves only that the supplied
data has exact keys, statuses, reason counts, and arithmetic conservation. It
does not prove that forecasts or outcomes came from historical execution and
cannot set `accounting_complete=true`.

If declared origins are nonempty but no historical execution occurred, the
lifecycle is `not_run`: actual forecasts are zero and no completed accounting
result exists. Do not fabricate abstentions to satisfy conservation. An
interrupted run retains actual immutable progress and explicit missing keys but
cannot issue a completed result. Scope blocks and failures are not model
abstentions. Empty synthetic scopes may validate zero arithmetic only; they do
not establish historical completion or performance.

Only the deferred `complete_historical_accounting` wrapper may create a
`HistoricalAccountingResult`. It must validate a live execution-completion
authority, producer authority, the exact execution instance, the pure
reconciliation, and every parent/child identity. Issuance and validation of
those authorities remain deferred; Stage C alone can never claim historical
completion.

Method-own counts remain independent from future direct-comparison intersections.
The typed metric/comparison bridge remains deferred, so this contract produces
no RMSE, MAE, directional accuracy, comparison status, or historical report.

## 10. Anomaly Semantics

Native scoring preserves the existing seven literal field tokens:

```text
open high low close volume candle unknown
```

It also preserves endpoint, feature-window, and unresolved collections;
original source column; occurrence position; multiplicity; raw values; absent
versus null keys; original timestamp strings; evidence references; manifest
record identity; and source identity.

- Never expand `candle` into OHLCV.
- Never interpret `unknown` as null, missing, wildcard, all-fields sensitivity,
  or unresolved association.
- A known endpoint role with `unknown` field attribution is still an endpoint
  anomaly for A-sensitivity.
- Numeric target invalidity comes from the validated target contract, not token
  inference.
- Feature-window-only records do not globally exclude a target.
- Required unresolved association or missing linkage blocks completion while
  preserving evidence; it is not an abstention.
- Contradictory linkage/source identity is an integrity failure.
- Recorded evidence references remain unverified unless their bytes are
  separately authenticated; source-byte authentication is a different axis.

Legacy 5C compatibility and its classifications/counts remain unchanged.
Native representability does not retroactively make a row legacy-compatible or
execution-ready.

## 11. Pure Helper Reuse

The future implementation must use this explicit boundary:

| Need | Reuse unchanged | Do not do |
| --- | --- | --- |
| UTC hour validation | `evaluation_protocol.validate_hour` | Require a timezone-name identity or accept nonzero offsets. |
| Split validation | `evaluation_split`, `require_evaluation_origin` | Move half-open boundaries or schedule audit-only origins. |
| Model/sample identity | Public constants and `forecast_accounting.identity` | Add a model/sample silently. |
| Finite scalar | `forecast_accounting.finite` | Accept Boolean, NaN, infinity, or silent coercion. |
| Forecast reasons | `forecast_reason_order`, `ordered_reasons` | Copy or reorder a second table. |
| Score reasons | Existing `TARGET_REASON_PRIORITY`, `SCORE_PRIORITY`, `ordered_reasons` | Infer new token-based exclusions. |
| Forecast/score status | `ForecastState`, `validate_score_state`, `validate_emission_unchanged` | Add pending/blocked/not-run as model statuses. |
| Conservation | `evaluation_protocol.validate_counts` plus native exact-key checks | Accept equal counts with different keys. |
| Timestamp-set digest | `evaluation_reporting.timestamp_digest` | Include audit-only/duplicate timestamps or substitute JSON payload hashing. |
| Metric mathematics | Existing `metrics` semantics only after a reviewed typed bridge | Duck type, forge 4A `Accounting`, or duplicate RMSE/MAE/sign logic. |

`Quality`, `Outcome`, `Score`, `Accounting`, `account`, `comparison_set`,
`build_report`, and `ValidationEvidence` are not native entry points. Private
report status helpers are not promoted to public historical APIs.

## 12. Canonical Serialization

Serialization is **PROPOSED — NOT IMPLEMENTED**. It creates data-only bytes and
never recreates source, execution, or outcome authority.

### 12.1 Canonical JSON rules

- UTF-8, `ensure_ascii=false`, lexically sorted object keys, compact separators,
  and exactly one final LF.
- Duplicate JSON keys, unknown schema fields, non-string object keys, and
  unknown versions are rejected.
- Aware zero-offset timestamps normalize to
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`; original raw manifest timestamp strings remain
  unmodified strings inside raw occurrence records.
- JSON null and an absent key are distinct. Required keys are never omitted;
  optional fields are present with null.
- Finite binary64 numbers only. Preserve `-0.0`; do not normalize it to `0.0`.
- Original occurrence arrays retain role grouping, source order, positions, and
  duplicates. Derived record arrays sort by period, origin, canonical model
  order, and canonical sample order.
- Immutable mappings become objects; tuples become arrays. Bytes, paths,
  registry tokens, weak references, callables, and capabilities are forbidden.

### 12.2 Exact bundle schema

The future canonical payload is one object with exactly these keys:

```text
schema_version
policy_version
serializer_version
scoring_spec_id
scoring_build_id
execution_instance_id
record_type
source_provenance
scope
forecasts
outcomes
score_classifications
scores
reconciliation
accounting
scope_block
research_only
execution_ready
point_in_time_verified
decision_eligible
payload_sha256
```

Exactly one of `reconciliation`, `accounting`, or `scope_block` is non-null.
A pure Stage B/C bundle uses `score_classifications` and may contain a
`reconciliation`, but has null `execution_instance_id`, empty `scores`, and
cannot claim historical completion. A future authenticated historical bundle
requires a validated non-null `execution_instance_id` and may contain
`accounting`. `forecasts`, `outcomes`, classifications, and scores contain only
actual records; blocked/not-run scope bundles use empty arrays. Interrupted
bundles may retain actual progress only.
`payload_sha256` hashes the canonical object with that field omitted. The
digest does not include itself.

### 12.3 Identity hierarchy

`scoring_spec_id` is SHA-256 of a canonical logical specification containing:

- schema/policy/protocol/dataset/native versions;
- exact source provenance hashes and source receipt identity;
- exact scope, fixed analysis boundary, period/use, methods, samples, immutable
  source-ledger evaluation identity set and separate audit-only identity set;
- approved status/reason/anomaly/conservation rules; and
- the declared frozen-selection identity where Test Ridge is requested.

It excludes code, dependencies, serializer implementation, processing clocks,
and result values.

`scoring_build_id` is SHA-256 of canonical:

```text
scoring_spec_id
code_content_sha256
dependency_versions
serializer_version
deterministic_build_configuration
```

Changing source/scope/policy changes the spec and therefore build. Changing
code, dependencies, serializer, or deterministic build configuration changes
the build. Runtime processing clocks do not silently change either identity.
An explicitly supplied semantic `checked_at` belongs to the outcome/score
payload and scope policy where applicable; it is not fabricated publication
time.

`payload_sha256` hashes the actual canonical payload bytes. Any payload change
changes it. A future persisted file also needs a separate exact artifact-byte
SHA-256 if its container bytes differ from this JSON payload.

`execution_instance_id` is a proposed future identity for one immutable,
authorized execution instance. It is distinct from a reusable build identity
and from the resulting payload bytes. Its canonical inputs, issuer, validation,
restart semantics, and persistence are deferred. Pure Stage A–C data has no
authenticated execution-instance identity. An authenticated historical
forecast, score, or completed accounting result would require the same validated
execution instance throughout the parent/child chain.

A digest is integrity metadata, not authentication or proof of model execution.
The current 5C/5E registries and conflict maps are process-local only. A future
build may validly produce many forecasts, scores, reconciliations, and payloads;
there is no one-build-to-one-payload invariant. Conflicting-byte detection needs
a properly scoped immutable execution or artifact identity plus record identity,
not `scoring_build_id` alone. Execution-instance issuance and persistent
publication/reader verification remain deferred, so this contract does not yet
claim conflict protection across calls, processes, restarts, or artifacts.

## 13. Threat Model

| Threat | Existing protection | Proposed 5G protection | Remaining limit |
| --- | --- | --- | --- |
| Forged source binding | 5C/5E private process registration and pinned factory | Require live registered source and exact provenance on every factory use | Hostile in-process code and persistence are not solved. |
| Caller `authenticated=True` | No such trusted public flag exists | No Boolean proof field; only factory membership can issue capability | Runtime issuer is deferred. |
| Caller model-execution claim | Source receipts explicitly do not prove model execution | Forecast requires future producer trace and authority validation | Producer authority/receipt format is deferred. |
| Swapped outcome | Bound source row/ref and native envelope identity | Forecast/outcome/source/origin digests must match exactly | Requires future live capability implementation. |
| Changed row index/key | 5C verifies bound row/index/origin | Recheck all reference fields before outcome traversal/scoring | No external signature. |
| Cross-sample substitution | Existing sample validators | Sample is in forecast and score identity; exact match required | Execution producer evidence deferred. |
| Cross-method substitution | Existing method validators | Method is in forecast and score identity; exact match required | Same limitation. |
| Pre-closure outcome read | 5C/5E check clock before row traversal | Private capability issued only after exact inclusive closure | Theoretical closure is not publication evidence. |
| Target leakage into forecast | Existing forecast allowlist and synthetic guards | Predictor gets only a preissued narrow input view, never reader/session | Coordinator/producer integration is deferred. |
| Duplicate/missing origins | Existing accounting and audit set checks | Pure reconciliation requires exact immutable source-ledger identity-set equality, not counts or generated timestamps | Partial execution yields no complete result. |
| Unauthorized scope reduction | 5E audits declared sets but does not execute | Scope pins every ledger evaluation identity, preserves missing/invalid/anomalous/unrepresentable/unscorable rows, and keeps audit-only identities separate | Execution authority remains deferred. |
| Fabricated abstentions | Approved statuses/reasons are validated | Only actual completed decisions count; scope blocks/not-run create no forecasts | Requires trusted producer receipt. |
| Synthetic relabeling | Synthetic and pinned factories are distinct; reporting is synthetic-only | Historical source mode required; serialized flags do not upgrade mode | Separate historical reporting remains absent. |
| Cross-build or cross-execution substitution | No historical executor exists | Enforce exact spec/build and, for future authenticated records, execution-instance equality across every parent/child | Issuance and live validation of execution identity are deferred. |
| Replayed/tampered bytes | Current canonical digests and process-local maps detect some conflicts | Recompute spec/build/record/payload IDs and bind exact source; never infer a one-build/one-payload rule | Proper execution/artifact-scoped persistent conflict registry and signatures remain deferred. |
| Historical reporting bypass | `ValidationEvidence` and `build_report` reject historical mode | Native result types are not accepted by synthetic reporting | Historical report interface/metric bridge remains deferred. |

The design does not claim to defend against arbitrary hostile Python code with
memory mutation inside the same process. Dataclass freezing, weak registries,
digests, and validation are correctness/integrity boundaries, not a security
sandbox.

## 14. Synthetic Verification Matrix

These are specifications for future separately authorized tests. No executable
test is added now. Synthetic fixtures must remain explicitly synthetic and may
not claim authenticated historical execution.

| ID | Fixture construction | Proposed API under test | Expected result / exception | Required invariant | Deferred authority dependency |
| --- | --- | --- | --- | --- | --- |
| F01 | Finite emitted forecast and valid closed synthetic value | `classify_native_score` | `scored`; value pair unchanged; only `ScoreClassification` returned | Pure classifier cannot issue authenticated history | None; output carries no authentication claim |
| F02 | Emitted forecast; invalid null synthetic target with ordered missing/close reason | `classify_native_score` | `emitted_but_not_scored`; no zero/imputation | Invalid label retained | None; historical wrapper remains deferred |
| F03 | Approved AR abstention plus closed synthetic value | `classify_native_score` | `not_scored_no_forecast`; forecast reason unchanged | Emission immutability | None; historical wrapper remains deferred |
| F04 | Valid endpoint-anomalous synthetic target, A-primary | `classify_native_score` | `scored`; occurrence retained | Primary keeps valid anomaly | None; output is synthetic data only |
| F05 | Same synthetic outcome, A-sensitivity; repeat volume and literal `unknown` | `classify_native_score` | `emitted_but_not_scored` | Endpoint rule, no field translation | None; historical wrapper remains deferred |
| F06 | Only feature-window anomaly | scorer and forecast-input validator | No global target exclusion; existing method mask remains separate | Association isolation | Input factory authority deferred |
| F07 | `candle`, `unknown`, absent/null keys, `-0.0`, duplicate occurrences | canonical encoder | Exact lossless round trip and stable digest | Literal/order/multiplicity retention | None for pure encoder |
| F08 | Swap dataset/spec/build/execution-instance/receipt/file/index/origin/period/model/sample or parent ID one at a time | all record validators/wrappers | Explicit rejection | Every parent/child identity must agree; timestamp/hash syntax is insufficient | Live registration and execution-instance issuer deferred |
| F09 | Caller hash/Boolean/copied or deserialized capability, or pure classification passed as a historical score | outcome/scoring factory | Explicit rejection; synthetic cannot upgrade | Authority is not data; pure classifier issues no `HistoricalScore` | Exact authority issuer deferred |
| F10 | Access before close, at close, and custom zero-offset close | closed outcome boundary | Safe `not_closed` before; capability exactly at close | Clock checked before target traversal | Runtime factory deferred |
| F11 | Trap target/value/anomaly/full-row access while changing future fields | forecast input/record factory | Forecast bytes/status unchanged | No current-target leakage | Coordinator integration deferred |
| F12 | Immutable ledger identities including missing/invalid/anomalous rows, then missing, duplicate, extra, generated-hour replacement, or equal-count wrong-key forecast/classification | `reconcile_native_accounting` | Preserve exact ledger universe; reject every mismatch | Exact source-ledger identity-set equality; audit-only remains separate | Synthetic scope sufficient |
| F13 | Blocked/not-run and interrupted scopes; pure reconciliation passed to completion wrapper without authority | scope/accounting factory | No fabricated rows; pure result rejected as completed accounting | Lifecycle and reconciliation are not authenticated completion | Execution receipt semantics deferred |
| F14 | Final `2026-10-20T13:00:00Z` origin at 13:00 and 14:00 | origin/outcome/scope boundary | Audit-only, never scheduled/scored | Test remains half-open | None for boundary fixture |
| F15 | Mixed scored, invalid emission, and abstention rows | `reconcile_native_accounting` | All equations and exclusive counts pass; historical execution remains unverified | Full-universe denominator without completion claim | Synthetic scope sufficient |
| F16 | Equivalent canonical inputs; multiple legitimate payloads from one build; then payload tamper or same execution/artifact identity with conflicting bytes | encoder/validator | Equivalent inputs match; shared build is accepted; tamper rejected; scoped conflict awaits authority | Spec/build/execution-instance/payload identity separation | Execution-instance issuance and persistent conflict protection deferred |
| F17 | Pass native objects into synthetic fixture/reporting | existing guards | Rejection; no 4A widening or relabeling | Contract isolation | None |
| F18 | Monkeypatch all fit/predict/tune/ingest/feature/network/write functions to fail | scorer/accountant | Calls complete without touching traps | Pure classification/accounting | None for synthetic kernel |
| F19 | Pass native results to `metrics`, `build_report`, or forged 4A book | existing reporting boundary | Rejection/no report | Typed metric bridge deferred | Yes, bridge review required |
| F20 | Trap dashboard, signal, order, and artifact publication APIs | all proposed pure kernels | No side effects | Research-only boundary | None |
| F21 | Empty synthetic scope and empty scored set | pure reconciler/encoder | Zero counts, null coverage where allowed, `historical_execution_verified=false` | No fabricated events or completion claim | Historical completion authority deferred |
| F22 | Unresolved association, missing linkage, and known endpoint `unknown` | outcome factory/scorer | First two block/fail with evidence; known endpoint follows sample rule | Do not guess association | None for synthetic native fixture |
| F23 | Overlapping target, anomaly, lag, fit reasons | forecast/scorer/accountant | Existing priority exactly; all overlaps retained | No second reason table | None |
| F24 | Own/baseline/feature/paired scored sets with blocked Ridge | future typed metric bridge | Exact participant/set equality; four-model comparison cannot omit Ridge | Own coverage independent of common set | Yes, typed metric/reporting bridge deferred |

Additional constructor tests must cover every required/optional field, enum,
Boolean/int distinction, nonfinite value, unknown key/version, immutable mutation,
digest recomputation, and canonical round-trip specified in §5 and §12.

## 15. Implementation Decomposition

No stage below is authorized by this document.

| Stage | Dependencies and entry criteria | Exit criteria | Forbidden side effects | Separate owner authorization |
| --- | --- | --- | --- | --- |
| A — Native types and validation | Final Architect approval of exact §5/§12 schemas; unchanged 4A–5F contracts | Frozen data-only types, strict validators, canonical encoder, constructor/tamper tests; no capability or execution-instance issuance | Source/data writes, models, scoring execution, reporting, new dependencies | **Required** |
| B — Synthetic scoring kernel | Stage A approved; synthetic factory design reviewed; existing reason/status helpers unchanged | Pure score classification passes F01–F08, F10, F22–F23 with invented data | Historical source I/O, fitting, prediction, metrics, reporting | **Required** |
| C — Synthetic accounting kernel | Stages A/B approved; exact ledger scope/key rules frozen | Data-only `AccountingReconciliation` passes F12–F16, F21; no `HistoricalAccountingResult` or fake completion | Historical I/O, completion claims, metric duplication, publication | **Required** |
| D — Historical source/capability integration | Producer/execution/completion authority, execution-instance issuer, outcome issuer, restart model, and source-binding review completed; Stage A–C approved | Exact pinned-source capability tests and no-leakage instrumentation; deferred wrappers can be reviewed without a historical model run | Model execution, performance metrics, publisher, dashboard | **Required; deferred** |
| E — Typed metric bridge | Exact native value-pair and comparison-set type review; numerical equivalence plan approved | Shared existing metric mathematics accepts only validated native bridge records; F19/F24 pass | Forged 4A books, cloned math, historical publication | **Required; deferred** |
| F — Historical execution and reporting | Separate Lane A execution authorization, producer receipts, frozen Ridge selection, persistent artifact/reporting contracts, human review | Only separately approved bounded run and validated report | Trading, model selection from Test, PIT claims, orders | **Required; deferred** |

Each stage must verify protected data and immutable artifacts before and after,
retain the three historical QNT-003 working-tree edits, and stop if evaluation
semantics would change. Stages D–F are not implied by approval of A–C.

## 16. Open Decisions and ADR

Architect review produced the following dispositions. They approve or defer
contract directions only; they do not authorize implementation of any stage.

| ADR | Final disposition | Approved or unresolved boundary |
| --- | --- | --- |
| ADR-5G-01 — Exact record schema | **APPROVED — Design Baseline** | Scoring identities are explicit on parent/child records; the exact universe comes from the immutable origin ledger; pure reconciliation remains distinct from completed historical accounting. |
| ADR-5G-02 — Serialized capability boundary | **APPROVED** | Serialized closed-outcome data is an untrusted descriptor and can never recreate live authority. |
| ADR-5G-03 — Pure-helper reuse | **APPROVED** | Use the §11 reuse matrix: scalar validators/reason/count/digest helpers only; no duck typing, 4A widening, private-status promotion, or duplicated metrics. |
| ADR-5G-04 — Native scoring/accounting kernels | **APPROVED — Synthetic Kernel Design** | Pure classification and reconciliation are eligible only for future synthetic implementation review; authenticated historical scoring and completion wrappers remain deferred. |
| ADR-5G-05 — Capability and producer authority | **DEFERRED** | Exact execution-scope issuer, model producer/refit receipt, outcome-capability registry, restart, and persistent validation design. |
| ADR-5G-06 — Typed metric bridge | **DEFERRED** | Exact native scored-pair/common-set adapter using existing metric mathematics. |
| ADR-5G-07 — Persistence and conflict registry | **DEFERRED** | Artifact layout, byte verification, cross-process conflict/replay handling, signatures if any, and immutable publisher/reader. |
| ADR-5G-08 — Historical execution/reporting/trading | **DEFERRED** | Lane A model execution, historical metrics/reporting, GitHub/dashboard publication, model choice, signals, backtesting, and trading. |

### 16.1 Requirements before Stage A authorization

Design approval does not authorize Stage A. A future implementation review must
resolve both matters below before any Stage A code is authorized:

1. The canonical logical specification hashed to derive `scoring_spec_id` must
   exclude the stored `scoring_spec_id` field itself, preventing recursive
   hashing.
2. `ScoreClassification` validation must bind each classification to its exact
   parent forecast identity, preventing substitution between forecasts that
   otherwise share origin, model, and sample fields.

These are future review requirements, not implementation authorization, and do
not alter the approved evaluation semantics.

Further review is required on whether `producer_trace_ref`, `fit_ref`, and
`alpha_selection_ref` become typed receipt references or remain digests inside
the data record. They cannot authenticate themselves either way. No decision is
needed now on performance thresholds, deployment selection, or trading logic.

## 17. Acceptance Criteria

This approved design milestone is closed only while all of the following remain
true:

1. Exactly this one new Markdown document is created.
2. All 17 required sections are present.
3. Every new API/type/schema is labeled **PROPOSED — NOT IMPLEMENTED**.
4. Existing implemented behavior, approved architecture, proposed contract,
   and deferred authority/integration are explicitly distinguished.
5. Forecast and score vocabularies, samples, periods, closure, anomaly rules,
   reason precedence, and conservation match existing contracts.
6. Source authentication, model-producer authority, execution-instance
   authority, and historical-completion authority remain independent.
7. Pre-closure diagnostics expose no target-bearing data.
8. `candle`, `unknown`, association roles, order, multiplicity, and raw evidence
   remain lossless; legacy 5C behavior is unchanged.
9. Canonical spec/build/execution-instance/payload identities are separate;
   one build may produce multiple payloads, and none is called authentication.
10. All F01–F24 future test specifications identify fixture, API, expected
    result, invariant, and deferred-authority dependency.
11. Local links resolve and Markdown/whitespace checks pass.
12. Existing tracked files, three pre-existing QNT-003 edits, 25 protected
    datasets, four immutable origin artifacts, and canonical manifest remain
    unchanged; Git index remains empty.
13. `classify_native_score` and `reconcile_native_accounting` are explicitly
    pure data-only interfaces; only deferred wrappers may issue authenticated
    `HistoricalScore` or completed `HistoricalAccountingResult` records.
14. The full evaluation universe is exactly the immutable source-ledger
    identity set, with audit-only origins separate and no filtering of missing,
    invalid, anomalous, unrepresentable, or unscorable rows.
15. No Stage A, B, or C implementation is authorized, and no implementation,
    executable test, historical execution, scoring,
    accounting, metrics, reporting, publication, trading, stage, commit, or push
    occurs.

**PQTA-003D-5G — APPROVED DESIGN; IMPLEMENTATION NOT AUTHORIZED.**
Stop for Architect review.
