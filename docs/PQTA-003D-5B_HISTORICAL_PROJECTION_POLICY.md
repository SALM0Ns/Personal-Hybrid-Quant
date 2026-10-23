# PQTA-003D-5B — Historical Projection Policy Design

**Status: Approved Design — Not Implemented**
Starting commit: `737ebd08462032177b9f7ba09cafc45848db5f95` on `main`.
Design-policy identity: `pqta-003d-5b-projection-v1`.
Governing protocol: `qnt-003d-design-v1`; source dataset contract:
`pqta-003b-origin-ledger-v1`; existing reporting schema:
`pqta-model-evaluation-v1`.

This document records the approved design for a **lossless projection envelope
with fail-closed 4A compatibility checks**, not a historical execution bridge.
The policy identity identifies this design; it is not evidence of an executable
projection. Design approval does not authorize implementation, models,
evaluation, publication or trading.
The current historical inputs are **not declared execution-projectable**.
Where a complete projection would require guessing or lossy conversion, the
policy requires `blocked`; any alternative requires separate review and approval.

## 1. Architecture decision record

### Finalized architecture decisions

| ADR | Final decision | Boundary |
| --- | --- | --- |
| ADR-5B-01 — Quality Scope | **APPROVED:** target-endpoint-only anomaly summaries for historical-to-4A `Quality`. | Preserve feature-window records separately; keep `feature_complete` and `ar_lag_valid` explicit. No existing 4A contract changes. |
| ADR-5B-02 — Unsupported Anomaly Fields | **APPROVED: Strict Fail-Closed v1.** Preserve `candle` and `unknown` verbatim; unsupported required fields yield `blocked`. | No translation, dropped records/origins, incomplete outcomes or model-abstention substitution. Full historical execution remains blocked. |
| ADR-5B-03 — Provenance | **APPROVED IN PRINCIPLE:** source receipt/key binding, policy identity, build identity and canonical payload digest design. | Actual implementation and verification require separate review. Caller-supplied verification flags are not authenticated evidence. |
| ADR-5B-04 — Historical Reporting | **DEFERRED:** separately reviewed historical reporting interface required. | Do not modify synthetic reporting contracts, bypass guards or label historical evaluation synthetic. |

### Authorization separation

| Authorization | Current state |
| --- | --- |
| Design approval | Approved as `pqta-003d-5b-projection-v1`, with the ADR statuses above. |
| Implementation authorization | Not granted by this design or this documentation-finalization task; separate scope, review and approval required. |
| Historical execution authorization | Not granted. No historical fitting, forecasting, scoring or model evaluation may run. |

The following state is retained unconditionally by this finalized design:

```json
{
  "execution_ready": false,
  "point_in_time_verified": false,
  "decision_eligible": false
}
```

### Context and future design flow

[PQTA-003D-5A](PQTA-003D-5A_HISTORICAL_ADAPTER.md) preserves a typed historical
record, all original ledger values and nulls, source identity, and separate
target-endpoint, feature-window and unresolved anomaly records. These are not
synthetic fixtures or 4A `Outcome` objects. Proposed future flow:

```text
Verified read-only HistoricalAudit / HistoricalAdapter
  -> policy and source-identity checks
  -> lossless source-keyed projection envelope
       +-> forecast-only field plan (no current/future outcome access)
       +-> completed-history selection plan (closure-gated)
       +-> closed-outcome field plan (complete 4A compatibility or blocked)
  -> STOP: execution, historical reporting and publication remain unauthorized
```

Keep the source record immutable and distinct from every derived view. Do not
flatten away association, field vocabulary, evidence or source-row identity.
Prefer a separate projection layer; change none of the existing 4A contracts,
`run_synthetic`, model mathematics, feature definitions, splits or sample rules.
ADR-5B-01 approves the historical target-only quality-summary scope below;
it does not redefine the scope of existing 4A synthetic fixtures or implement
their historical projection.

## 2. Actual source-contract compatibility

The following source was inspected, not inferred from milestone summaries:

- [`historical_adapter.py`](../src/quant/research/historical_adapter.py):
  `HistoricalFeatures`, `HistoricalOutcome`, `HistoricalRecord`,
  `associate_anomaly`, `_inspect`, `_report`, `audit_pinned_history`.
- [`forecast_accounting.py`](../src/quant/research/forecast_accounting.py):
  `Quality`, `Outcome`, `Score`, reason priorities, `account`.
- [`evaluation_reporting.py`](../src/quant/research/evaluation_reporting.py):
  `Provenance`, `ValidationEvidence`, `_status`, comparisons, `build_report`.
- [`model_evaluation.py`](../src/quant/research/model_evaluation.py):
  synthetic fixture guard, admitted-label adapters and Test-only Ridge replay.
- [`evaluation_protocol.py`](../src/quant/research/evaluation_protocol.py),
  [QNT-003B §6](QNT-003B_EVALUATION_PROTOCOL.md),
  [QNT-003D §5](QNT-003D_FINAL_RESEARCH_DESIGN.md), and the
  [manifest contract](../src/quant/features/manifest.py).

| Difference | Existing behavior | Projection disposition |
| --- | --- | --- |
| Object types | `HistoricalOutcome` is not 4A `Outcome`; the runner accepts typed synthetic fixtures only. | No casting, synthetic relabeling or guard bypass. Separate future projection API only. |
| Raw fields | Manifest permits `candle` and `unknown`; 4A quality accepts OHLCV names only. | Preserve originals; block exact compatibility when required records contain unsupported fields. |
| Association scope | Historical endpoint/window records are separate; existing 4A row-level quality has no prescribed historical union. | ADR-5B-01 specifies target-endpoint-only type/field summary for historical projection; retain other associations separately. No implicit union. |
| Quality booleans | `feature_complete` and `ar_lag_valid` are post-outcome audit fields. | Copy validated values explicitly; they do not enforce model inputs or training eligibility. Never use constructor defaults as source evidence. |
| Reasons | Historical invalid reasons are lexically ordered; 4A requires `TARGET_REASON_PRIORITY`. | Preserve the original tuple; derive a separate priority-ordered tuple with exactly the same reason set and primary reason. |
| Anomaly orders | 4A type/field tuples are sorted unique; feature names follow `FEATURES` order. | Apply the correct order to each derived view; retain raw record order separately. |
| Source identity | 4A `Outcome` has no raw row, source hash, association or row index. | Keep a mandatory source-keyed lossless attachment; an unattached flattened outcome is not the historical projection product. |
| Out-of-split row | 5A retains final `2026-10-20 13:00 UTC` audit origin; 4A rejects it. | Retain as `audit_only`, outside every evaluation universe and scored-set digest. Do not move the test boundary. |
| Evidence labels | 4A outcome accepts `unverified`/`partial`, not `verified`. | Preserve the 5A unverified evidence limitation; byte authentication does not upgrade it. |
| Historical reporting | 4A provenance forces `artifact_bytes_verified=false`; evidence forces synthetic mode and no historical authorization; Test interpretation is explicitly synthetic. | Separate historical verification receipt. Do not use existing reporting to certify a historical run or falsify its mode. Historical reporting is a further blocking interface decision. |

4A `Score` applies forecast reasons, target invalid reasons and (for
A-sensitivity) the target endpoint flag. It does **not** implement feature or
lag eligibility by inspecting `Quality` booleans. A future orchestration layer
must enforce those existing method-specific rules before emission and retain
their approved abstention reasons. Projection is not that orchestration layer.

## 3. Quality concepts and approved projection semantics

| Concept | Authoritative historical input | Design use |
| --- | --- | --- |
| Target-endpoint quality | `target_endpoint_anomalies`, `target_manifest_anomaly`, original validity/reasons | Closed-outcome audit; endpoint flag drives the existing sensitivity scoring rule. |
| Feature-window quality | `involved_anomalies`, `anomaly_involved_features`, quality/null flags | Retain raw window records and per-feature masks independently. Not target quality. |
| Forecast-side eligibility | Current finite features/exact lag, their approved sample masks, separate fit state/history | Forecast-only view; never uses the current target or its scoreability. |
| Outcome-side validity | `target_valid`, finite nullable target and all invalid reasons | Read after closure; null target cannot be scored or admitted as a training label. |
| Evaluation-only exclusions | Closed target flag and fixed retrospective manifest; scored-set intersections | Post-outcome scoring/comparison. Do not retract emissions or select masks from performance. |

**Approved `Quality` scope (ADR-5B-01):** for a fully supported row, copy explicit audited
`feature_complete` and `ar_lag_valid` booleans. Set `anomaly_types` to the sorted
unique types of its **target-endpoint records only**, and `affected_fields` to
the sorted unique fields of those same records. This is an exposure summary,
not a statement that every field changes a return, nor an evidence certificate.
Feature-window records are not silently folded into this summary. Their full
raw records, masks, sensitivity metadata and links remain in the envelope.
No anomaly at an endpoint may be omitted because its numeric effect is small,
because a target is null, or because it affects only volume/high/low/open.

`target_manifest_anomaly` means **any** endpoint record, including on a null
target. `target_value_sensitive` instead refers to a valid calculated target
with possible numeric sensitivity; preserve it in the attachment, never use it
to narrow the approved sensitivity exclusion. Likewise retain authoritative
per-feature masks; do not replace them with a generic interpretation of the
maximum-window anomaly list or a field-name-based eligibility guess.

The numeric target and feature values are copied, never recalculated or
repaired by projection. Reason reordering is explicit representational
normalization only; unknown/duplicate reasons or conflicting primary reasons
are errors, not an opportunity to choose a replacement reason.

## 4. Anomaly-field decision table and lossless retention

| Original field | 4A can encode the exact field? | Approved handling |
| --- | --- | --- |
| `open` | Yes | Copy the literal into a supported endpoint summary; retain the full raw record. |
| `high` | Yes | Same; do not infer close/return sensitivity. |
| `low` | Yes | Same; do not infer close/return sensitivity. |
| `close` | Yes | Same; retain disputed-close provenance without replacing a value. |
| `volume` | Yes | Same; close-only numeric sensitivity does not waive endpoint sensitivity exclusions. |
| `candle` | No | Preserve verbatim; exact projection is `blocked` under ADR-5B-02. Never expand into five OHLCV names. |
| `unknown` | No | Preserve verbatim; exact projection is `blocked` under ADR-5B-02. Never choose an OHLCV field or equate this with a missing numeric value. |

For this **approved Strict Fail-Closed v1 (ADR-5B-02)**, any unsupported token in a required row's
endpoint, feature-window or unresolved collections prevents that row from
being declared fully projected. A numeric-only subset is not a complete
quality projection. A feature-window-only unsupported record stays outside
the approved endpoint summary, but its overall projection classification is
still explicitly blocked, not silently called complete. Any unknown anomaly
type, unresolved association, inconsistent record/mask, or unspecified source
semantics also blocks compatibility. Invalid schema/identity is a failure.

Preserve raw field names/values, timestamps (including shortened closes),
source-column association, original row index/key and order, severity, review
status, references, manifest identity and all original nullable source values.
Deduplicated type/field summaries never replace raw record multiplicity. A
record may correctly appear in both endpoint and feature-window roles; retain
both associations. Unknown-column records preserved by `associate_anomaly`
remain unresolved; the strict 5A ledger reader still rejects schema drift.

**Stop boundary:** 5A documented unsupported tokens in the current inputs.
Do not implement a full-history exact 4A projection by deleting them, replacing
them with empty tuples, or dropping their origins. ADR-5B-02 retains the
continuing block. Any different versioned representational solution requires
separate Architect/owner review and approval; this design does not select one.

## 5. Temporal eligibility and examples

Use timezone-aware, hour-aligned UTC-equivalent datetimes as accepted by the
existing validators; do not impose a new `tzinfo` identity requirement.

For forecast origin `o`, source candle open `t=o-1h`:

- Feature values use candles through `t` only; their theoretical boundary is
  `o`. All seven remain in canonical `FEATURES` order, with original nulls.
- Current target is `ln(C_o / C_(o-1h))` using candles opening `o-1h,o`;
  theoretical target closure is **`o+1h`**, not `o`.
- Admit historical label `h` only when **`h+1h <= o`** (equivalently candle
  indexed row `s=h-1h` requires `s+2h <= o`). Check clocks before reading its
  target value, validity or target-anomaly flag. Current label `h=o` is excluded.
- Then apply the existing sample/method training rules; closure alone does not
  imply numeric validity, adequate history, fit success or forecast eligibility.
- `available_at=null` remains null; local ingestion times, manifest evidence
  times, projection receipt time and theoretical closure are not interchangeable
  with exchange publication availability. PIT and decision eligibility stay false.

Example at `2025-01-02 00:00 UTC`: the feature candle opens `2025-01-01 23:00`.
Label origin `2025-01-01 23:00` has theoretically completed and can be considered
for history. Label origin `2025-01-02 00:00` closes at `01:00`; neither its value
nor its target flag can control the midnight forecast/refit.

An AR training pair for target label `h` uses lag label `h-1h`, covering exact
candle opens `h-2h,h-1h,h`. The current AR lag at `o` uses exact opens
`o-2h,o-1h`, equivalent to completed label `o-1h`. Require both valid lag
endpoints and the valid target endpoints for a training pair. Never find a lag
by shifting over filtered rows; a missing or invalid adjacent candle breaks
the pair. Missing-hour audit rows remain on the hourly timeline; no fill,
interpolation, synthetic candle, compressed adjacency or target zero is allowed.

Keep existing scheduling: Mean requires 720 sample-eligible completed targets
and updates hourly. AR/Ridge require 720 eligible pairs/rows respectively at
midnight-only scheduled refits. Failed or
skipped scheduled refits cannot reuse stale state. Ridge uses the fixed
A-primary 2024 selection for both samples, frozen before Test; no new alpha
selection or selected-alpha replay in training/validation. This design does
not run any of these operations.

## 6. A-primary, A-sensitivity and information roles

The default prohibition on ex-post exclusions changing emission is preserved,
with the **explicit already-approved exception** in QNT-003B §6 and QNT-003D
§5. Those documents require separately fitted retrospective sensitivity paths:

| Method | A-primary historical / current-input rules | A-sensitivity additional rules |
| --- | --- | --- |
| Zero Return | No training; time-only current input; emit zero at every in-split origin. | Same emission; target flags affect scoring only after closure. |
| Mean | Completed, valid finite historical targets; no current-target inspection. | Exclude completed historical labels with endpoint manifest flags. |
| AR(1) | Completed valid exact return pairs; valid exact current lag. | Training pair excludes any manifest record across its three opens; current lag excludes records on either lag endpoint. |
| Ridge | Completed valid targets and all seven finite historical features; current complete finite feature vector. | Historical rows also need no target or feature-window anomaly; current vector needs no involved-feature anomaly. |

This is **not a newly authorized mask**. Making sensitivity scoring-only would
contradict the governing protocol; changing that behavior requires a protocol
decision outside this milestone. Conversely, projection may not add any extra
target-side forecast filter or performance-selected subset. All fixed-manifest
training/current-input masks are explicitly retrospective ex-post knowledge;
they do not establish as-of availability or tradable historical forecasts.

Both samples exclude invalid targets from later scoring. A-primary retains
numerically valid anomalies; A-sensitivity excludes any endpoint anomaly after
the outcome closes. Ridge completeness/current-feature rules are enforced by
its own emission contract, not by repurposing `Quality` at score time. No current
or future target anomaly or scoreability field enters a forecast mapping. An
anomaly on the current feature candle may legitimately affect an existing
feature/lag mask, but a record on the next target candle must not be propagated
backward into that current feature/lag mask.

## 7. Per-condition decision matrix

The matrix specifies the underlying approved Lane A semantics, **conditional
on a future fully compatible and separately authorized projection/execution**.
`P` = A-primary; `S` = A-sensitivity. Conditions may overlap; retain all reasons
and use existing primary-reason priorities. An audit/projection block is not
a new forecast abstention or a sample exclusion.

| Condition and information boundary | Forecast eligibility at `o` | Training admission at later `o'` | Scoring after `o+1h` | Evaluation exclusion |
| --- | --- | --- | --- | --- |
| Valid current target; outcome-side fact | Do not inspect it to emit. Use method inputs, history and fit only. | Only if `o+1h <= o'`; P retains valid anomalies; S applies approved masks; method minima still apply. | Finite emitted forecast + valid target; S also needs no endpoint anomaly; Ridge's feature rule remains. | None from validity alone; other reasons may exclude. |
| Null/invalid target; outcome-side fact | Must not retract or prevent an otherwise valid current emission. | Never admit as eligible label/pair/feature-target row. | Emitted forecast is `emitted_but_not_scored`; abstention remains `not_scored_no_forecast`. | Preserve all target invalid reasons and exclusive primary reason. |
| Missing candle | If current/past input: Ridge null-feature and/or AR missing-lag abstention; Zero/Mean still depend only on their own requirements. If next candle: no current-emission influence. | Reject every label/pair/window whose required exact observations are absent; no bridging. | Affected target invalid; retain missing reasons. | Numeric missingness is not an asserted exchange outage; `candle` also blocks strict projection. |
| Feature-window anomaly; separate retrospective feature mask | P retains finite values. S Ridge/AR apply only their approved current feature/lag masks; Mean/Zero do not inherit arbitrary feature exclusions. | P retains valid inputs. S Ridge feature mask, AR three-open mask; Mean only completed endpoint target mask. | Feature metadata alone is not an invented target exclusion; retain method's original emission and source outcome. | Record masks and sample-specific abstentions; do not add a blanket all-method feature exclusion. |
| Target-endpoint anomaly; outcome-side fact | Current/future target flag is forbidden. Any overlapping past/current feature/lag association is separately governed above. | After closure, P retains valid values; S excludes flagged historical target (and corresponding AR/Ridge masks). | P can score valid target. S emitted forecast becomes unscorable on endpoint flag. | Use existing `target_manifest_anomaly`, not `target_value_sensitive`. |
| `unknown` field / unresolved association | No new model reason or guessed field. Structural compatibility is blocked; do not start an ostensibly complete run or selectively emit a reduced origin set. | No guessed membership or field translation; retain raw record and defer projection. | No fabricated 4A outcome/score or clean summary. | Projection blocker, not a newly invented evaluation exclusion or forecast status. |
| Missing/invalid exact AR lag; forecast-side fact | AR abstains using approved reason; other methods use their own inputs. | No AR training pair spanning the absent/invalid lag; Mean/Ridge assessed separately. | Preserve AR abstention; it has no scored forecast. Other finite forecasts use target rules. | Count AR abstention and overlapping reasons; do not remove the origin globally. |

Before any future historical emission, validate compatibility of the declared
scope as a **run prerequisite**, not a per-origin target-dependent emission
filter. If unsupported metadata prevents complete projection, stop the whole
requested scope and return a projection-block report. Do not call skipped
origins model abstentions or calculate metrics on a conveniently reduced set.
If a fault is discovered after an emission in a future execution system, retain
that immutable emission and stop final accounting/report completion; never
retroactively recast it. This milestone has no such execution path.

## 8. Typed interface proposal — signatures only

All names below are proposed, not existing code or authorization to implement:

```text
HistoricalProjectionPolicy
  version, quality_scope=target_endpoint_only,
  unsupported_field_action=block_exact_projection,
  unresolved_association_action=block_exact_projection

HistoricalSourceReceipt
  dataset/build/contract identities, expected and observed hashes,
  byte-verification evidence, source audit version and canonical digest

LosslessRowAttachment
  original HistoricalRecord, full manifest identity/evidence references,
  original source key/index/column associations, raw values/nulls/reasons
  (retained behind the audit boundary, not returned to forecast consumers)

OpaqueSourceRef
  source identity/key/index and receipt reference only;
  no HistoricalRecord, raw outcome, resolver or data-access capability

ForecastFieldsPlan
  origin, feature_open_t, canonical nullable seven-feature tuple,
  explicit completeness, per-feature anomaly names, exact-lag masks,
  research_only=true, unchanged historical availability/eligibility

OutcomeEnvelope
  compatible 4A Outcome plus mandatory LosslessRowAttachment
  (only representable, closed rows; never a substitute for the raw record)

ProjectionResult[T]
  classification = compatible | blocked | failed | audit_only | not_closed
  value: T | None, opaque source reference, ordered findings, provenance
  execution_ready=false, point_in_time_verified=false, decision_eligible=false

plan_forecast_fields(features: HistoricalFeatures, *, policy, receipt)
    -> ProjectionResult[ForecastFieldsPlan]

plan_completed_history(records: Sequence[HistoricalRecord], *, forecast_origin,
                       method, sample, policy, receipt)
    -> immutable eligible-label plan + retained per-label audit reasons

project_closed_outcome(record: HistoricalRecord, *, checked_at, policy, receipt)
    -> ProjectionResult[OutcomeEnvelope]
```

Preconditions: known approved policy version, verified 5A source identity/byte
receipt bound to these exact records, exact market/timeframe/feature order,
unaltered versions and masks, explicit association, valid schemas and keys.
An in-memory-only 5A result with asserted hashes is insufficient for historical
source authentication. Do not trust an unbound caller Boolean as a receipt.

Postconditions: unchanged audit-side raw attachment; no imputation/value repair; all
ordered views are reproducible and source linked; no future outcome in the
forecast plan; no incomplete label in eligible history; no unsupported row
called compatible; no mutation or writing. Forecast planning takes
`HistoricalFeatures`, not a full outcome-bearing row. Its result may carry
only `OpaqueSourceRef`, never the full raw attachment. Predictors must receive
only the allowlisted feature/time mapping and separately admitted history;
they cannot receive or dereference the audit-side record or a resolver for it.
Closed-history planning
may index clocks first but must gate each label before reading its target flags.

For compatible closed outcomes, explicitly supply target value/validity, the
priority-ordered full invalid-reason tuple, endpoint flag, approved quality
summary and `anomaly_evidence_status=unverified` matching 5A's present evidence
assessment. No `verified` status is legal. `partial` would need documented
per-record evidence coverage and its own reviewed rule; a populated record or
matched manifest hash alone cannot justify that label. Outcomes must be shared
identically across methods and samples; sample filtering stays outside them.

`not_closed` results expose only clock/source identity and a fixed incomplete
classification; do not expose outcome-bearing attachments, flags, derived
anomaly findings or serialization that traverses those outcomes. The original
record remains losslessly retained on the separate audit side. Only a closed
`OutcomeEnvelope` can include its full source attachment in the outcome-side
interface. Blocked diagnostic attachments likewise remain audit-only, not
forecast inputs.

`not_closed`, `audit_only`, `blocked` and `failed` are **projection-envelope
classifications only**, never additions to 4A forecast/score vocabularies.
Do not construct an `Outcome` before closure through this proposed API, even
though the low-level type constructor itself does not enforce a checked time.
`Score` requires closure even for an abstained forecast because it reads the
outcome; the protocol's earlier no-forecast status check is not permission to
read future outcome metadata.

## 9. Provenance, ordering and canonical serialization

ADR-5B-03 approves this provenance design **in principle**, not an implemented
or verified receipt/binding mechanism. Keep these distinct in the future
immutable projection receipt/envelope:

| Provenance group | Required contents |
| --- | --- |
| Source identity | `dataset_spec_id`, source `artifact_build_id`, market/timeframe, original file identifier, row index and UTC origin/key. |
| Checked bytes | Expected and observed Silver/Gold hashes; origin-ledger, dataset-validation, provenance JSON and sidecar hashes; canonical manifest digest and raw-file digest where recorded; verification method and 5A audit version/digest. |
| Contracts | Dataset and evaluation protocol versions, feature version and exact `FEATURES` order, manifest version/identity, policy identity `pqta-003d-5b-projection-v1` and separately reviewed serializer version. |
| Evidence | Separate source-byte verification, anomaly-evidence completeness/reference checks, unresolved associations and deferred fields. Keep historical `available_at` null, PIT false, decision eligibility false. |
| Temporal assumptions | Fixed analysis boundary, exact split intervals, `label_origin+1h` closure rule, retrospective sample semantics; no assumed publication latency. |
| Build identity | Future projection code-content digest, dependency versions, deterministic configuration and policy-content digest. Do not relabel the source build as a projection/evaluation build. |

Retain the in-principle design of a logical `projection_spec_id` over source identities, contracts, fixed
boundary and policy-content digest; a separate `projection_build_id` additionally
pins code/dependencies/serializer/configuration; `projection_payload_sha256`
hashes the actual canonical payload bytes. These are future identity requirements,
not actual published IDs. Processing/receipt time is separate from historical
availability and must be explicitly injected; exclude variable processing time
from logical spec identity and any claimed byte-deterministic payload.

Use existing canonical JSON conventions: UTF-8, sorted object keys, compact
separators, no NaN/infinity, final LF; UTC timestamps encode
`YYYY-MM-DDTHH:MM:SS.ffffffZ`. Preserve source IEEE-754 values (including signed
zero) and nulls without rounding; do not replace raw binary source hashes with
JSON hashes. Maintain original raw array/record order and multiplicity in the
attachment. Derived quality sets use lexical order; feature tuples/masks use
`FEATURES` order; projected invalid reasons use `TARGET_REASON_PRIORITY`.
Reject duplicate JSON object keys, ambiguous identities and duplicate row keys.

Batch derived rows sort by market/timeframe/origin within the declared scope;
out-of-split rows stay in a separate audit collection. Reordering an input list
must either be explicitly canonicalized with original indices retained or
rejected by source validation, never silently alter row identity. Any future
scored-origin digest must keep the existing distinct encoding
`YYYY-MM-DDTHH:MM:SSZ\n`, sorted unique UTC origins, not JSON timestamps.

4A reporting provenance has no projection-policy field and explicitly rejects
`artifact_bytes_verified=true`. Store actual checked-byte/projection receipts
outside that strict schema. `ValidationEvidence` currently accepts only
`mode=synthetic` and no historical authorization; its Test interpretation is
synthetic too. Do not supply false synthetic evidence or bypass these guards.
A historical reporting boundary is **DEFERRED under ADR-5B-04** and needs
separate review; this design neither implements nor declares it solved.

## 10. Failure, blocking and accounting consequences

| Classification | Example | Required behavior |
| --- | --- | --- |
| `failed` | Hash/version/schema mismatch, duplicate/misaligned key, invalid reason or conflicting mask | No compatible output; retain diagnostic/source reference, stop requested projection. Do not repair source. |
| `blocked` | `candle`/`unknown`, unresolved association, unauthenticated source receipt, unapproved policy | Keep complete raw attachment and findings; no flattened 4A outcome or sample shrinkage. |
| `not_closed` | `h+1h > checked_at` | No target/flag inspection or completed-label admission; retain clock identity only in the closed-history result. |
| `audit_only` | Final origin outside approved split | Retain raw audit row; never schedule/score it or extend the split. |
| `compatible` | Representable verified forecast-input view, or closed outcome/history view with its required audit linkage | Current-target closure is required for outcome/history views, not the forecast-only view; means representation only, not execution approval. |

No new forecast/score status, abstention reason or target exclusion is defined.
A future fully authorized run must preserve original full-universe accounting:

```text
N_origins = N_emitted + N_abstained
N_emitted = N_scored + N_emitted_but_not_scored
N_abstained = N_not_scored_no_forecast
```

Forecast emission and scoreability are separate. Every method/sample/origin has
one forecast and one final score status in a completed run; score exclusions
cannot erase emissions. An incomplete blocked projection cannot be packaged as
a complete 4A `Accounting` by fabricating absent scores. Retain independent
projection-block counts; evaluation remains not run/blocked, with no metrics.

Future direct comparisons retain exact scored intersections, all required
participants and common timestamp digests. Do not drop blocked Ridge from a
four-model comparison or use method-own coverage as a common-set metric count.
Keep existing status precedence `blocked`, `no_forecasts`,
`no_scored_forecasts`, `complete`; `failed`/`not_run` retain their existing roles.
Projection readiness does not set an evaluation's status to `complete`.

## 11. Design verification and future synthetic tests

Existing synthetic tests are evidence of **current contracts**, not tests of
this unimplemented policy. Relevant anchors:

- `test_historical_adapter.py`: `test_source_rows_values_and_nulls_preserved_losslessly`,
  `test_original_non_ohlcv_anomaly_fields_are_never_translated`,
  `test_unknown_source_association_is_unresolved_without_loss`,
  `test_historical_adapter_cannot_bypass_synthetic_runner_guard`,
  `test_valid_hash_syntax_does_not_establish_verified_source_bytes`.
- `test_evaluation_protocol.py`: completed-label boundary/flag isolation,
  sample masks, exact AR pair and Ridge-history rules, score timing and counts.
- `test_model_evaluation.py`: guarded future-outcome access, prefix invariance,
  future anomaly isolation, exact AR mapping, Test-only Ridge replay and refits.
- `test_forecast_accounting.py` / `test_evaluation_reporting.py`: reason
  priorities, evidence restrictions, full-universe counts, exact intersections
  and blocked-participant propagation.

Future implementation must add independent, synthetic positive/negative tests:

1. OHLCV-only endpoint summaries exactly preserve literal fields/types and
   raw multiplicity; distinct feature-window records never leak into them.
2. Every `candle`/`unknown` occurrence and unresolved association blocks strict
   compatibility without deletion, expansion, empty-field substitution or
   silently reduced universes; unknown anomaly types fail closed.
3. Lexical raw reasons remain intact while the derived tuple follows exact
   priority and preserves the full reason set/primary reason.
4. Change current/future targets and endpoint flags while instrumenting access:
   forecast values/eligibility cannot change or read them. Forecast and
   `not_closed` results have identity-only references, never outcome-bearing
   attachments or resolvers. Admit the prior label exactly at
   closure, not one instant earlier; demonstrate the explicit sensitivity
   completed-history exception without leaking the current target flag.
5. Missing rows never compress adjacency; invalid/missing previous candle
   prevents the corresponding AR pair/current lag. No label/window is filled.
6. Null/nonfinite features reject or preserve approved null states appropriately;
   Quality booleans alone cannot make Ridge/AR eligible. A valid anomalous
   primary input remains valid; sample masks match the governing protocol.
7. Target-only versus feature-only anomalies produce separate source roles;
   volume-only endpoints retain the conservative sensitivity target exclusion.
8. Tamper source hashes, row keys/index/attachments, policy content/version,
   manifest identity or provenance binding: reject without source mutation.
   Valid digest syntax cannot pass checked-byte gates by itself.
9. Repeated pinned synthetic inputs and injected processing time produce
   byte-identical canonical envelopes; derived ordering, signed zero, nulls and
   UTC encodings are tested independently. Source bytes are never rewritten.
10. Out-of-split audit origins remain preserved but cannot enter universes;
    shared outcomes are identical across methods/samples. No models, files,
    network, runner, reporting-mode bypass or publication path is invoked.

## 12. Remaining execution blockers, non-goals and review gates

ADR-5B-01 and ADR-5B-02 are resolved design decisions, not open approval
questions. The following implementation-review and execution blockers remain:

1. No historical projection implementation or execution bridge is authorized
   or implemented by this milestone. Implementation requires separate approval
   and review against the approved endpoint-only scope and fail-closed policy.
2. Unsupported required tokens still produce `blocked` under ADR-5B-02. Keeping
   raw tokens outside 4A cannot justify a falsely complete numeric-only summary.
   No affected record or origin may be dropped, no incomplete outcome may be
   created, and no projection block may be treated as a model abstention.
3. Historical reporting is deferred under ADR-5B-04. Its interface and evidence
   handling require separate review; existing synthetic contracts and guards
   remain unchanged. Historical evaluation must not be labeled synthetic.
4. ADR-5B-03 is approved in principle only: actual source-receipt/key binding,
   policy/build identity and canonical payload digest implementation and
   verification require separate review. Caller-supplied verification flags
   alone are never authenticated evidence. Any per-record `partial` evidence
   rule likewise needs separate review. Root causes, independent anomaly
   evidence verification and historical publication remain unknown.
5. Historical execution requires its own explicit authorization after applicable
   implementation/readiness gates pass. Design approval alone grants none.

There is no conflict resolution by assumption: the existing sensitivity
exception is preserved, unsupported/lossy conversions stop, and unresolved
requirements are explicitly blocking for execution. The policy is
**Approved Design — Not Implemented**; neither historical projection,
historical reporting nor model evaluation is implemented by this design.
It does not certify historical projection or execution readiness.

Non-goals: no production code or dependency changes; no target generation,
source/manifest mutation, historical fitting, alpha tuning, forecasts, scores,
performance metrics, historical runner, live inference, trading backtesting,
signals, dashboard changes, file publication, orders, Git commit or push.
Historical performance must never be labeled live-trading performance.
Keep `point_in_time_verified=false` and `decision_eligible=false` throughout.
Stop for Architect review of the finalized documentation. Separate
implementation, historical execution and Git Closure authorizations remain
required; none is implied by this documentation-only finalization.
