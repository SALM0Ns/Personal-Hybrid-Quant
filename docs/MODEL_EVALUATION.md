# PQTA-003D-4 — Model Evaluation Architecture and Data Contract

**Status: reporting contract approved; PQTA-003D-4A Complete — Architect
Approved (Synthetic Only).** Historical evaluation,
artifact publication and dashboard integration remain unimplemented.
This milestone does not authorize historical fitting, forecasting, scoring,
Lane A execution, trading backtesting, inference, signals, or orders.

## 1. Scope, authority, and implementation boundary

The product goal is practical personal BTC/USDT 1h decision support with
manual execution, not an academic publication. Research metrics are an
engineering check, not trading confidence, profitability, or authorization
to select a trading model.

This proposal was inspected against commit
`b0d33fb574fcb67acbd89da9c4fefd8b136f57fe`. Normative policies remain
[QNT-003B §§2–7](QNT-003B_EVALUATION_PROTOCOL.md), closed by
[QNT-003D](QNT-003D_FINAL_RESEARCH_DESIGN.md), under
`qnt-003d-design-v1`. The source dataset contract remains
`pqta-003b-origin-ledger-v1`; see the
[approved architecture](PQTA-003B_ML_ARCHITECTURE_DESIGN.md) and
[dataset implementation](PQTA-003C_DATASET_IMPLEMENTATION.md).
The owner approved synthetic accounting/reporting under this version,
candidate tuning diagnostics only for Ridge validation, training-history
accounting only, and frozen-alpha test comparison. Research metrics are
not trading confidence. Storage/publication and UI remain future designs,
not amendments to statistical policy. Conflicts
require review rather than a silent implementation choice.

| Component | Actual state at this design |
| --- | --- |
| Silver/Gold and origin ledger | Existing immutable local research inputs; the origin ledger already has retrospective targets. |
| `evaluation_protocol.py` | Implemented pure time, eligibility, status and conservation checks. Not an evaluation runner. |
| `statistical_baselines.py` | Implemented in-memory Zero Return, Mean, AR(1), tested synthetically. |
| `ridge_regression.py` | Implemented in-memory seven-feature Ridge, scaling and alpha selection, tested synthetically. |
| `forecast_accounting.py`, `evaluation_reporting.py` | Implemented pure synthetic accounting, metrics, comparisons and strict evidence-linked report validation; no historical results exist. |
| `model_evaluation.py` | PQTA-003D-4B synthetic-only chronological coordinator implemented; Architect review pending. No historical reader or publisher. |
| `historical_adapter.py` | PQTA-003D-5A read-only pinned-source and lossless historical audit implemented; Architect review pending. No projection into 4A or execution bridge. |
| `historical_projection.py` | PQTA-003D-5C strict read-only compatibility layer implemented; Architect review pending. Source-bound in-memory plans/audit only, not a historical runner or reporting bridge. |
| `historical_representation.py` | PQTA-003D-5E native audit-side representation implemented; Architect Review Pending. Reuses source receipts and the lossless envelope; no native forecast/scoring API or historical evaluation. |
| Historical orchestration and published forecast/score/refit ledgers | Designed, unimplemented. |
| Application | Read-only historical Silver chart, `NO SIGNAL`; no model evaluation view. |

Scope is only the pinned Binance Spot BTC/USDT 1h history, seven existing
features, and candidate manifest. No recalculation of Gold, new source,
feature family, model, dependency, or research period is proposed.
The 4B test harness below uses invented synthetic feature/return fixtures
only; it does not consume or extend that historical study dataset.

## 2. Proposed minimal historical architecture

```text
Read-only verified origin build + pinned Silver/Gold/manifest provenance
  → chronological event coordinator
      → allowlisted current-origin view → existing model prediction APIs
      → separately admitted completed history → existing fit/update APIs
      → immutable forecast/refit accounting
  → post-closure outcome audit → separate score accounting
  → scored-set intersections → metrics + conservation validation
  → immutable LOCAL evaluation build + bounded reviewed summary
      → manual GitHub documentation publication (separate approval)
      → future read-only local evaluation panel (separate implementation)
```

A future historical coordinator would verify input byte digests,
dataset/build identities, schema, UTC keys, versions and split assignments
before use. It would consume the existing ledger and pinned validated
Silver, never exchange APIs. That reader is not implemented by 4B. The
separate 5A adapter described in §16 performs source/readiness inspection;
5C (§17) checks strict projection compatibility, and 5E (§18) adds a separate
native metadata representation audit. None connects history to
this execution flow.
AR's exact source-close observations must come from pinned Silver, not a
new return definition or row-shift approximation. Source validity and
anomaly flags must be mapped explicitly into the existing model APIs.

At each origin, expose only `forecast_side_view`-allowlisted fields to
prediction; pass historical labels via the separate history APIs after
closure gating. Do not pass a whole outcome-bearing ledger row to a model.
Process the two samples independently, including their fitted histories.
Validate input contracts and approved abstention reasons; malformed data,
unknown codes, identity mismatch or broken conservation abort publication.
Legitimate cold starts and numerical model abstentions remain auditable
outcomes, not dropped records or substituted predictions.

Keep the existing origin-build directory immutable. Proposed evaluation
storage is a **separate** ignored local root:
`data/research/pqta-003-evaluations/<evaluation_spec_id>/<evaluation_build_id>/`.
It would contain `forecast_ledger.parquet`, `score_ledger.parquet`,
`refits.parquet`, `alpha_selection.json`, `metrics.json`,
`validation.json`, `provenance.json`, and `provenance.sha256`.
No directory or artifact is created in this design task.

## 3. Time and period contract — inherited, not revised

For candle open `t`, origin `o=t+1h`, target
`y_t=ln(C_(t+1h)/C_t)`, and theoretical target close `o+1h`:

1. Close/validate candle `t` at the theoretical boundary `o`.
2. Admit historical labels only when `historical_label_origin+1h <= o`
   (equivalently candle-indexed `s+2h <= o`).
3. Perform the scheduled refit, then emit/abstain without current-target
   values, validity, next-candle flags or scoreability.
4. Only after target closure, apply outcome quality and score classification.

At `2025-01-01 00:00Z`, current feature open is `2024-12-31 23:00Z`.
The newest admissible historical label origin is `2024-12-31 23:00Z`;
it closes at 00:00. The current label origin is 00:00 and its outcome
closes at 01:00; it cannot enter the midnight fit. Equal-clock close
precedes refit by mathematical event order, not publication evidence.

| Period ID | Origin interval `[start,end)` UTC | Result interpretation |
| --- | --- | --- |
| `training_history` | `[2021-01-01 01:00, 2024-01-01 00:00)` | History/cold-start accounting; never held-out model performance. |
| `validation` | `[2024-01-01 00:00, 2025-01-01 00:00)` | Prespecified selection period; selected Ridge scores are tuning results. |
| `test` | `[2025-01-01 00:00, 2026-10-20 13:00)` | Frozen-protocol chronological comparison; earlier completed outcomes may enter later scheduled refits. |

The 50,845-origin source audit timeline includes one origin at
`2026-10-20 13:00Z` outside all splits. Report it separately; never add it
to forecast/score counts. Last in-split test origin is 12:00Z and closes
at the fixed `analysis_as_of=2026-10-20 13:00Z`. Split union has 50,844
origins, not 50,845. These are existing timeline facts, not evaluation results.
No split movement, random split, retrospective regime predictor, new
embargo, or full-sample preprocessing is introduced.

## 4. Versioned machine-readable comparison schema

JSON format: `pqta-model-evaluation-v1`. The strict Python validator
rejects unknown schema versions, duplicate record keys, incorrect types,
invalid digests, nonfinite numbers and unreconciled counts by rebuilding
the expected report from independent typed in-memory evidence. No external
JSON-schema dependency or standalone JSON Schema file is needed for this
stage. No historical result file has been generated.

The envelope contains `schema_version`, `evaluation_spec_id`,
`evaluation_build_id`, `provenance`, `validation`, `alpha_selection`,
`comparison_sets`, ordered `results`, and an `accounting` array.
`accounting` contains per-period/model/sample counts and quality metadata
without performance metrics, including training history and validation.
`results` and `comparison_sets` are test-period synthetic comparisons only.
The fixed window interpretation distinguishes accounting, tuning and test.
`provenance` binds every input
and local output digest, source feature/manifest versions, fixed
`analysis_as_of`, source-ledger byte digest, code/runtime/dependency
identities and processing-time policy; `validation` records all completion
gates in §8. Market identity is exactly `binance`, `BTC/USDT`, `1h`, with
target `target_next_1h_log_return` and unit `raw_hourly_log_return`.
`alpha_selection` retains grid, folds, frozen candidate-set digest/count,
all candidate statuses/failure origins/reasons and the frozen winner.
The public projection omits individual failure-origin arrays and refers
to their verified local artifact digest instead; aggregate reason counts
remain public. Public summary bytes have their own digest.

Each `results` record has the following required fields (nullable only
where stated):

| Field | Type and semantics |
| --- | --- |
| `exchange`, `symbol`, `timeframe`, `target_name`, `target_unit` | Fixed non-null strings matching the envelope's market and target identity. |
| `model_id` | Enum `zero_return`, `expanding_mean`, `ar_1`, `ridge_7`; display names Zero Return, Expanding Mean, AR(1), Ridge Regression (7 Features). |
| `evaluation_period` | Object `{period_id, start_utc, end_exclusive_utc, interpretation}` matching §3; no moving end. |
| `sample_policy` | Enum `a_primary`, `a_sensitivity`. No combined sample score. |
| `comparison_scope` | Enum `method_own`, `baseline_common`, `feature_common`, `paired_sensitivity_common`. Own-set metrics are descriptive, not direct method comparisons. |
| `comparison_id`, `timestamp_set_sha256` | Comparison identity and exact metric-set digest; participant models/samples are declared in `comparison_sets`. |
| `rmse`, `mae`, `directional_accuracy` | Nullable finite binary64 numbers; definitions in §5. Metrics are null for an empty set or blocked comparison. Numerical failure raises rather than dropping rows or producing a completed report. No NaN/Infinity. |
| `metric_count` | Nonnegative integer, exact cardinality of this record's declared scored timestamp set, retained even when blocked prerequisites prevent metric computation. |
| `origin_count` | All scheduled in-split hourly origins in this period, independent of target, history, feature validity or model success. |
| `forecast_count`, `abstention_count` | Nonnegative integers `N_emitted`, `N_abstained` for the method/sample/full period, not the common-set subset. |
| `forecast_coverage` | Nullable number in `[0,1]`, approved `forecast_count/origin_count`; null only if denominator zero. Not accuracy or confidence. |
| `own_scored_count`, `emitted_but_not_scored_count`, `not_scored_no_forecast_count` | Full-period method/sample counts, distinct from `metric_count` on a comparison subset. |
| `abstention_reasons` | Code-to-count object of exclusive forecast abstentions under existing method priority; sums to `abstention_count`. |
| `primary_score_exclusion_counts`, `all_score_exclusion_counts` | Exclusive score funnel and multi-label overlap counts under QNT-003B §6; only the exclusive counts reconcile to origins. Unknown historical availability remains separately visible. |
| `quality_counts` | Full-period target-valid, feature-complete, lag-valid, anomaly type/field, unknown availability and false Gold eligibility counts; categories can overlap. |
| `evaluation_status`, `status_reasons` | Final reporting status and deterministic reason list from §8. Status describes evidence/process, never profitability. |
| `evaluated_at_utc` | Nullable UTC processing-completion time; null for an unexecuted/blocked record. Never historical availability or forecast origin. |
| `dataset_spec_id`, `artifact_build_id` | Existing logical source dataset identity and **source origin-ledger** build identity. Do not reuse this build ID for evaluation bytes. |
| `protocol_version`, `dataset_contract_version` | Exactly `qnt-003d-design-v1`, `pqta-003b-origin-ledger-v1`. |
| `evaluation_spec_id`, `evaluation_build_id` | Distinct new reporting identities in §9; repeated for portable records. |
| `research_mode`, `point_in_time_verified`, `decision_eligible` | Exactly `retrospective`, `false`, `false` for this proposal; never overwrite original Gold fields. |
| `selected_alpha`, `alpha_selection_sha256` | Nullable Ridge-only metadata; linked to frozen A-primary validation selection, not test optimization. |

Unique result key is `(evaluation_build_id, period_id, sample_policy,
comparison_scope, comparison_id, model_id)`. Each comparison-set descriptor
contains its ID, period, ordered model/sample participants, count,
first/last origin (null for empty), and timestamp digest. The paired
sensitivity descriptor includes both samples explicitly. Each descriptor
also carries aggregate `evaluation_status` and ordered `participant_statuses`
(model, sample, raw method status and reasons). All methods on
one comparison set share its digest and `metric_count`; full-period
emission counts are repeated unchanged across that method's comparison
records and **must not be added together** across scopes.

## 5. Metric definitions — inherited

For exactly the declared scored origin set `E`, `n=|E|>0`,
`e_o=prediction_o-target_o`, using raw hourly log-return units:

```text
rmse = sqrt(sum(e_o**2) / n)           # primary
mae = sum(abs(e_o)) / n               # secondary
directional_accuracy = sum(sign(prediction_o) == sign(target_o)) / n
```

Sign is -1, 0, +1; zero means **exactly** zero, including signed binary
zero. No neutral band, tolerance, rounding, or exclusion of zero outcomes.
A zero forecast is directionally correct only when actual is exactly zero.
Directional accuracy is diagnostic, not a trading edge or confidence.
Metrics are fractions/raw returns, not percentages or annualized values;
a UI may format accuracy/coverage as percentages without altering bytes.

Proposed deterministic reduction: sorted unique origins, binary64 checked
errors, scaled `math.hypot` RMSE (as in existing `pooled_rmse`) and
`math.fsum` absolute-error reduction, integer direction matches. Any
nonfinite intermediate is an explicit reporting failure, not permission
to drop scored origins. No rounding before calculation, no average of
fold/period RMSEs; a pooled result must pool errors with its own count.
Formatting precision is display-only. Exact implementation choices need
synthetic equivalence/overflow tests before use, not new dependencies.

If `n=0`, all three metrics are null with a reason, not zero. For empty
comparison sets, report count zero, null endpoints and SHA-256 of empty
bytes. No ranking or winner is displayed. A one-row metric can be
arithmetically defined; the protocol supplies no minimum statistically
sufficient test count or profitability threshold. Do not invent one or
equate a nonempty metric with sufficient trading evidence.

## 6. Denominators, exclusions, and immutable accounting

The approved **forecast opportunity denominator** is every hourly
origin scheduled inside the selected approved split (`N_origins`). It
includes cold start, invalid inputs, missing targets and later anomalies.
Do not condition emission coverage on an ex-post valid target, `F_t`,
successful fit, or scored-set membership. Input-eligible and target-valid
subcounts may additionally be reported with explicit labels, never used
silently as `forecast_coverage`'s denominator. Empty period coverage is
null, with `empty_origin_universe`; a nonempty period with no emissions
has coverage 0 and null metrics.

Preserve distinct, final forecast and score fields per origin/method/sample:

```text
forecast_status: emitted | abstained
score_status: scored | emitted_but_not_scored | not_scored_no_forecast
N_origins = N_emitted + N_abstained
N_emitted = N_scored + N_emitted_but_not_scored
N_abstained = N_not_scored_no_forecast
N_origins = N_scored + sum(exclusive primary score exclusions)
```

A missing/invalid/incomplete next candle makes the target unscorable; it
does not cancel a finite forecast already emitted. A-sensitivity's target
anomaly filter is also post-outcome. Features and AR lags have separate
forecast-side validity/anomaly masks. Preserve all overlapping reasons and
the existing QNT-003B §6 total exclusive precedence without replacing it
with model error priority. No gap filling, interpolation, fabricated close,
silent anomaly removal, stale fit, or imputation is allowed.

Final `scored` and `emitted_but_not_scored` require the theoretical target
close to have occurred; `not_scored_no_forecast` may be known at origin.
No fourth pending score status is introduced. An incomplete run cannot
publish an apparently final ledger or claim completeness.

Rows marked target-valid with missing/nonfinite targets are inconsistent
inputs, not ordinary missing targets: fail closed at validation instead of
altering validity or the denominator. Preserve existing model behavior
if such inconsistent data reaches a component: Mean explicitly abstains,
AR/Ridge may fail numerically, and Ridge alpha selection raises
`ValidationDataIntegrityError`. The coordinator must not hide these as
successful evaluation or silently delete eligible labels.

## 7. Model comparison and tuning contract

| Model | Historical requirement and update | Failure accounting |
| --- | --- | --- |
| Zero Return | No history; emit finite `0.0` at every in-split origin in each sample. | No outcome-dependent abstention. Invalid targets affect scoring only. |
| Expanding Mean | At least 720 completed sample-eligible targets; update hourly using existing `math.fsum` API. | Explicit cold start/numerical abstention; never substitute zero. |
| AR(1) | At least 720 exact three-candle consecutive training pairs; exact two-candle current lag. Daily 00:00 fit with existing centered OLS/variance guard. | Missing/anomalous lag, cold start, ill-conditioning and numerical reasons remain visible; failed/skipped midnight cannot reuse yesterday's fit. |
| Ridge (7 Features) | At least 720 completed eligible feature/target rows; seven finite features, training-only population scaling, existing QR solver. Daily 00:00 fit. | Missing/anomalous features and fit/numerical abstentions remain visible; no imputation or stale fit. |

A-primary retains numerically valid anomaly-flagged inputs. A-sensitivity
uses the same pinned 19-record candidate manifest: exclude target endpoint
anomalies from historical training and scoring; additionally exclude AR
lag/pair anomalies and Ridge feature-window anomalies as specified in
QNT-003B §6. Preserve source field sensitivity separately from this
conservative any-anomaly filter. All sample paths fit independently.

Ridge selection is A-primary 2024 only, with alpha grid
`{0.01,0.1,1,10,100}` and folds `[2024-01-01,2024-05-01)`,
`[2024-05-01,2024-09-01)`, `[2024-09-01,2025-01-01)` UTC.
Freeze the candidate timestamp set from target/feature/720-history rules
before candidates. Any failed candidate forecast disqualifies the entire
alpha and records origin/reason; never shrink its denominator. Pool
validation RMSE, exact ties to smallest alpha. Malformed contracts abort,
not successful candidates. Empty set/all disqualified means Ridge
unavailable. Freeze selection before any test scoring and for both sample
paths throughout test; daily refits change scaler/coefficients only.
Selection boundary must be no later than each test fit cutoff. Wall-clock
processing later than the historical period does not authorize test tuning.

For each period/sample report separately:

- `method_own`: own scored-set diagnostics with full coverage/abstentions.
- `baseline_common`: exact intersection of Zero/Mean/AR scored-origin sets.
- `feature_common`: exact intersection of all four scored sets, including
  `F_t` and the sample's feature-side rule. Recompute **all four** metrics
  on that identical set; do not compare Ridge-own against baseline-own.
- `paired_sensitivity_common`, if approved for publication: intersection
  of A-primary and A-sensitivity common sets for the same participant
  group. State `baseline_common` or `feature_common` as the parent group;
  both sample paths use that one further-restricted set. This is descriptive,
  not a causal anomaly effect.

Publish every set's count, endpoints and canonical SHA-256. Use the
inherited timestamp encoding: sorted unique UTC origins as
`YYYY-MM-DDTHH:MM:SSZ\n` UTF-8; empty set is empty bytes. Do not replace
it with canonical JSON timestamp encoding. Keep the exact membership
locally for reconstruction. A missing Ridge cannot silently turn a
four-model comparison into a three-model claim; an empty feature-common
set has null metrics and an unavailable explanation.

The selected-alpha validation score is a tuning score, never independent
holdout evidence. The approved validation output is **candidate tuning
diagnostics only for Ridge**. No selected-alpha four-model or sensitivity
validation replay is published by this contract. Training history is
**accounting only**, not a performance comparison; no preselection alpha
is invented. The existing selection API returns candidate diagnostics;
future integration must retain those diagnostics, not reconstruct
predictions from aggregate RMSE. Test method ranking is descriptive;
it cannot choose a trading model, tune a threshold or authorize deployment.

## 8. Evaluation status and completion evidence

Reporting statuses are `not_run`, `complete`, `no_forecasts`,
`no_scored_forecasts`, `blocked`, `failed`. They are reporting statuses,
not new forecast/score statuses. No historical result exists today;
the UI default would be `not_run`, not a successful zero-valued result.

For validly constructed final reports, status precedence is explicitly:
`blocked` → `no_forecasts` → `no_scored_forecasts` → `complete`.
First check prerequisites. Then use **full-period** method emissions to
distinguish no forecasts; only then examine the comparison's scored set.
An empty common set is not evidence that a method emitted nothing.
`failed` remains the lifecycle classification for invalid/interrupted
execution; `not_run` remains unexecuted. Neither is a new forecast/score
status or a value inferred from empty performance data. The pure builder
raises on invalid contracts/numerics; it does not fabricate failure metrics.

- `complete`: authorized full requested period processed; evidence below
  validated; declared metric set nonempty and finite. This means an
  operationally complete retrospective result, not useful prediction.
- `no_forecasts`: nonempty opportunity universe, zero emissions; null
  metrics, coverage 0, explicit abstention counts/reasons. Do not call it
  a completed performance comparison.
- `no_scored_forecasts`: full accounting validated but declared metric
  set empty (including empty common set despite method-own forecasts).
  Metrics null; full-period coverage is retained unchanged. Reason
  distinguishes no own scorable outcomes from no common timestamps.
- `blocked`: missing authorization, empty origin universe, absent input,
  incompatible identity/version, or unavailable mandatory prerequisite
  such as no frozen Ridge alpha; no fabricated measurements.
- `failed`: interrupted execution, contract/data integrity, reconciliation,
  artifact verification or reporting-numerical failure. Partial diagnostic
  files stay local and cannot masquerade as complete results.

Ridge-specific prerequisite rules are fixed: missing/unavailable selection
means `blocked`, even with zero emissions. With a valid frozen selection,
zero period emissions means `no_forecasts`; finite emissions but an empty
scored comparison means `no_scored_forecasts`; a nonempty scored set with
all prerequisites satisfied means `complete`. Alpha selection itself is
unchanged.

The comparison descriptor aggregates participant statuses with the same
precedence. Any blocked participant blocks the comparison and every metric
record **in that comparison**, with `comparison_participant_blocked` for
otherwise-ready peers. Raw per-method states remain in `participant_statuses`.
An independent method-own comparison may still complete. This prevents a
blocked Ridge from making a four-model result appear complete without
mislabeling baseline-own results. Without blocked prerequisites, individual
method states stay distinct: one method can be `no_forecasts` while peers
with emissions are `no_scored_forecasts` on their empty common set.

Blocked records retain supplied emission/abstention/score accounting,
coverage, comparison membership/digest and `metric_count`; metrics are null
and no performance reduction runs. Nonempty blocked fixture data is not
certified as valid Ridge output. No forecast emission is retroactively
changed, no denominator is reset to hide the block, and no failed origin
is dropped.

Minimum evidence for `complete` is **all** of:

1. Separate owner execution authorization, fixed reviewed evaluation
   configuration and hash-verified origin/Silver/Gold/manifest provenance.
2. Exact origin coverage, unique linked forecast/score keys for both samples
   and all requested methods, including abstentions and unscorable targets.
3. Refits/history counts/max outcome closes, current-input isolation,
   no stale parameters, frozen Ridge selection and candidate failures logged.
4. All per-period/method/sample conservation and reason-priority checks,
   scored-set intersections and digests validated; finite metric reductions.
5. Synthetic/regression acceptance and deterministic pinned rerun checks;
   immutable artifact byte hashes and a human-reviewed limitations summary.

Individual model abstentions do not by themselves make a fully accounted
nonempty result incomplete. A run-validation record separately reports
whether all requested accounting completed; it does not upgrade a
`no_forecasts`, empty comparison or unavailable model to performance success.
A four-model claim requires all four on a nonempty identical scored set.
There is no approved minimum coverage or practical evidence threshold;
low counts/coverage must remain visible, not suppressed by a success badge.

## 9. Reproducibility and provenance proposal

Reuse source `dataset_spec_id` and source `artifact_build_id` unchanged;
verify the four origin-build files and canonical manifest, not just a
human-readable report. Do not append to that immutable build.

- `evaluation_spec_id`: canonical hash of reporting-contract version,
  governing protocol, source dataset/build and exact input byte digests,
  fixed analysis boundary, requested periods/models/samples/comparison
  groups, fixed tuning/refit/metric policies. This identifies intended
  evaluation independently of implementation. Selected alpha is an output,
  not a parameter chosen after test inspection.
- `evaluation_build_id`: canonical hash of evaluation spec, content hashes
  of every executed model/protocol/coordinator/reporting module, Git
  revision, exact Python/dependency/platform/libm evidence, serializer,
  schema/row/field ordering, deterministic writer/reduction configuration,
  and any injected processing timestamp embedded in bytes.
- `artifact_sha256`: exact bytes for each published local file and each
  GitHub summary. Provenance has a sidecar digest, not its own recursive hash.

Proposed JSON canonicalization follows PQTA-003C: sorted keys, compact
UTF-8, `ensure_ascii=false`, `allow_nan=false`, final newline; timestamps
UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Schema fixes array ordering by
period (`training_history`, `validation`, `test`), sample (`a_primary`,
`a_sensitivity`), lexicographic comparison ID, then model (`zero_return`,
`expanding_mean`, `ar_1`, `ridge_7`). Comparison descriptor arrays use
period then lexicographic ID; reason arrays use governing priority,
refits/origins ascend, and alpha candidates use ascending numeric order.
These orders are enforced in the in-memory reporting schema. Float values
use finite Python binary64 JSON round-trip numbers;
pin serializer/runtime, do not promise cross-platform bit identity.
Parquet uses pinned schema and writer settings recorded in the build.

`evaluated_at_utc` is processing time, not `analysis_as_of`. Inject a
fixed completion timestamp into deterministic published bytes and include
it in build identity; variable rerun timings belong in a separate receipt.
A new time embedded in bytes implies a new build identity, not an overwrite.
The same pinned build must reproduce identical bytes; otherwise fail
closed. Verify expected file set, all digests and no unexpected files;
publish atomically only after validation. None is executed in this task.

## 10. Read-only dashboard integration contract — future only

The current application is a historical candlestick preview, not an
implemented evaluation dashboard. A later separately authorized change
may add an independent **Model Evaluation** panel and a bounded local
GET-only summary endpoint, proposed `/api/model-evaluations`.

The endpoint would load only schema-validated, digest-verified, explicitly
configured summary builds; never accept arbitrary filesystem paths or
launch fitting/evaluation. No credentials, external URL, arbitrary fetch,
or raw forecast rows are exposed. Missing file gives `not_run`; corrupt,
unsupported or provenance-mismatched summary gives a visible unavailable
error, never cached metrics presented as current success.

Display inspected model, period with exclusive end, sample, comparison
scope/participants, RMSE, MAE, exact-zero directional accuracy, metric
count, opportunity/emission/abstention counts, forecast coverage, status,
source/evaluation IDs and processing time. Show null as “Not available,”
not `0`. Display all four methods including unavailable ones; allow
inspection, not automatic best-model deployment.

Persistent warnings must state **HISTORICAL / RESEARCH ONLY** and
**POINT-IN-TIME AVAILABILITY UNVERIFIED — NOT APPROVED FOR TRADING**.
Validation selection scores must be labeled separately from test metrics.
No metric becomes signal confidence or live suitability. No BUY/SELL/HOLD,
forecast overlay or position/order action is introduced. The chart's
`NO SIGNAL` stays unchanged; `Analyze Now` continues refreshing Silver
only, not refitting models, selecting alpha or running an evaluation.

## 11. GitHub documentation/publication plan

This document is the proposed human-readable architecture. The publication
index is [evaluations/README.md](evaluations/README.md). After separate
execution, validation and owner approval, propose a small reviewed pair:

- `docs/evaluations/<evaluation_build_id>.md`: methods, exact periods,
  counts, paired metrics, provenance, failures and limitations.
- `docs/evaluations/<evaluation_build_id>.summary.json`: versioned public
  projection with aggregate results, counts/set digests, identities and
  artifact references, not predictions or market observations.

Require private-path/secret scanning and staged-diff allowlisting. Keep
origin/forecast/score/refit Parquet, source OHLCV, row-level targets,
archive/REST evidence and fitted scalers/coefficients local under ignored
`data/`. No large attachments, release assets or automatic publication.
Aggregate facts and digests are sufficient for a provenance-linked public
summary but not independent dataset-free reproduction; say so. Changes
to existing published immutable results require a new identity and an
explicit supersession note, not rewritten results. No summary with
invented numbers or claimed performance is created now.

## 12. Unresolved decisions and approval gates

| Decision | Proposed disposition; approval needed |
| --- | --- |
| Reporting format/status/coverage | Approved for synthetic implementation: `pqta-model-evaluation-v1`, §4/§6 opportunity denominator and §8 reporting statuses. Eligibility is unchanged. |
| Validation reporting paths | Resolved: candidate tuning diagnostics only for Ridge. No selected-alpha validation replay or holdout claim. |
| Training-history outputs | Resolved: accounting only; no performance metrics or invented preselection penalty. |
| Test comparisons | Resolved: frozen-alpha model comparison only; no test-based model deployment or trading confidence. Historical execution is still not authorized. |
| Subperiods/evidence thresholds | Default reporting is the fixed protocol splits. Additional monthly/yearly reports, display precision and any minimum-evidence caution thresholds must be frozen before affected results; no new statistical threshold is selected here. |
| Publication/UI | Approve bounded public projection, local storage and future GET-only adapter independently; this does not authorize execution. |
| Execution | Owner must separately authorize historical Lane A fitting/forecasting/scoring, immutable local publication, then public summaries. None is authorized by this design. |

Unresolved historical availability is not an implementation bug to bypass.
Preserve Gold `available_at=null`, `decision_eligible=false`, candidate
manifest `version_available_at=null`, unresolved discrepancy/shortened-close
interpretation and archive/local-only missing-hour evidence. Lane A is
retrospective even when chronological and numerically correct; Lane B and
historical trading backtesting remain blocked. No metric resolves fees,
slippage, execution latency or profitability. A protocol ambiguity/change
requires a versioned owner decision, not a new model default.

## 13. Implementation milestones and future extension targets

These are proposals, not authorization or newly assigned milestone IDs.

1. Architect/owner resolve §12 and approve the reporting contract; execution
   authorization stays separate.
2. PQTA-003D-4A implements synthetic-only accounting/metrics and schema
   validation; Architect approved (synthetic only). Historical orchestration and its
   boundary tests remain future work. Prove invariants before historical I/O.
3. Implement read-only pinned runner/immutable publisher with synthetic
   fixture builds; independent review before any real-history execution.
4. Only after explicit owner approval: historical Lane A run, independent
   ledger/metric/provenance audit and deterministic rerun.
5. Separately approve bounded GitHub summaries, then read-only application
   integration. No signal or trading milestone is implied.

| File or future extension target | Responsibility and implementation status |
| --- | --- |
| `src/quant/research/model_evaluation.py` | Implemented synthetic-only chronological paths, sample isolation and public model API adapters; no historical I/O or formula duplication. |
| `src/quant/research/historical_adapter.py` | Implemented read-only historical source authentication, schema/identity/mask audit and lossless representations; no 4A projection or model calls. |
| `src/quant/research/forecast_accounting.py` | Implemented synthetic forecast/score records, reasons and conservation. Historical refit-record orchestration remains future work. |
| `src/quant/research/evaluation_reporting.py` | Implemented pure metrics/intersections and strict evidence-linked schema checks. Immutable file publication and public summary projection remain future work. |
| `configs/model-evaluation-summary.schema.v1.json` | Optional future standalone schema; not created or required by the current Python validator. |
| `tests/test_forecast_accounting.py`, `tests/test_evaluation_reporting.py` | Implemented synthetic arithmetic, accounting, set, schema and tamper checks; no historical I/O. |
| `tests/test_model_evaluation.py` | Implemented synthetic coordinator tests. Historical/immutable-runner tests remain future work. |
| `src/quant/app/server.py`, `web/index.html`, `web/app.js`, `web/style.css`, `tests/test_app_preview.py` | Later read-only summary API/panel and regression isolation; not part of evaluation execution. |
| `docs/evaluations/`, `README.md`, `docs/ARCHITECTURE.md` | Reviewed aggregate reports and accurate implementation status. |

Required synthetic cases include exact-zero sign matrix, empty sets/no
forecasts/all unscorable targets, overlapping exclusions, common-set
equality and digest encoding, every scheduled origin, all candidate
failures, future-prefix invariance, no current-target access, midnight
refit failure/stale rejection, malformed/contradictory inputs, missing or
tampered artifacts, and unchanged source files. The pre-implementation
regression baseline was 492 tests. Synthetic regression results do not
establish historical predictive performance.

## 14. PQTA-003D-4A implementation contract

Public accounting interfaces are `OriginUniverse`, `Forecast`, `Outcome`,
`Quality`, `Score`, `Accounting`, and `account`. Forecast construction has
no current-target argument. A finite prediction means `emitted`; a null
prediction requires an approved, method/sample-specific abstention reason.
The caller supplies already validated model outputs and all applicable
forecast-time reasons; accounting does not rerun fit/input eligibility or
prove a supplied prediction came from a particular model. Existing model
and protocol APIs remain responsible for their training/current-input
sample rules. `Quality` is copied post-outcome audit metadata, not a new
predictor or substitute for those forecast-side checks.

Anomaly metadata integrity: flags are actual Booleans; type and affected-field
tuples are sorted, unique and closed-vocabulary. `Quality` describes row-level
audit claims (which can concern feature windows, not only target endpoints).
`target_manifest_anomaly` remains a separate endpoint claim. Missing types,
fields, record references or manifest evidence are never inferred from
that flag, nor does a false flag certify an anomaly-free history. Partial
synthetic fixtures are permitted. `Outcome.anomaly_evidence_status` is
explicitly `unverified` (default) or `partial`; `verified` and equivalent
verification claims are rejected. Even populated metadata remains unverified.
Reports count these statuses under `quality_counts` without altering sample
masks, target validity or score/exclusion priority. A future evidence verifier
would need actual versioned manifest references and checked bytes; none is
introduced here.
Zero Return must emit exactly zero. Score construction reads outcome audit
metadata only at/after theoretical closure, preserving the existing three
score statuses and separate forecast/score exclusion priorities. This
outcome-bearing interface requires closure even for an abstention; the
older pure protocol helper still permits target-free abstention
classification at origin. Valid-but-nonfinite target input fails closed.
Accounting sorts but never deduplicates or drops scheduled origins.

`metrics`, `timestamp_digest`, `comparison_set`, `Provenance`,
`ValidationEvidence`, `ReportInputs`, `build_report`, `validate_report`,
and `validate_report_json` are the reporting APIs. `metrics` is a pure
arithmetic primitive; the report builder prohibits model-comparison
records outside test. Full method-own coverage stays separate from metric
counts on common sets. Every selected comparison has exactly the required
participants and their exact scored intersection. The validator requires
the independent accounting/comparison/provenance evidence, not just a
summary that asserts its own hashes. Unknown/extra/missing fields,
duplicate JSON keys, tampered types/counts/metrics/digests/statuses and
contradictory source audits fail closed.

This stage accepts `ValidationEvidence.mode=synthetic` only, with
`historical_execution_authorized=false`. Evidence gates are explicit
synthetic assertions, not proof of historical execution authorization,
source-file authentication, human review or PIT availability. A `complete`
fixture report means the in-memory accounting/evidence checks passed.
Missing completion evidence cannot produce a completed nonempty metric
record. `failed`/`not_run` are reserved reporting states, not invented
forecast/score statuses or fabricated performance results.

For bounded synthetic fixtures, `OriginUniverse` accepts a predeclared
half-open window contained in an approved split, including an empty
window. Report period bounds record that exact fixture window, never
claim full-split coverage. Future historical integration must enforce the
full approved requested split windows before claiming completion; no
new real-data subperiod selection is authorized. Training-history and
validation accounting appear only in `accounting`, not metric records.
Candidate diagnostics are supplied as the existing immutable
`AlphaSelection`; no tuning is run by reporting. Computing Ridge test
comparison metrics requires a selected alpha and a selection boundary
no later than the test window start. A missing/unavailable selection
produces an explicit blocked report; supplied fixture emissions remain
in accounting but are not certified as valid Ridge outputs. A supplied
selection with a boundary after the test window is still a temporal
contract error, not a successful or retuned selection. Identical frozen
selection metadata is shared by both samples; no retuning occurs.

Provenance validates lowercase digest syntax, version identity and
separate dataset/source-build/evaluation-spec/evaluation-build IDs.
Valid 64-character lowercase SHA-256 text is a syntactic identity, not proof
that any artifact exists or matches that digest. `artifact_bytes_verified`
is always false in this milestone; constructing or tampering with a true
claim fails closed. `identity_checks_passed` is a synthetic identity-agreement
gate, not byte authentication. These distinctions remain visible even in a
`complete` synthetic fixture report.
Digest values are independently supplied expected identities: this stage
does not derive evaluation build IDs, authenticate file bytes or publish
immutable artifacts. These 4A modules implement no file or network I/O,
model fitting or application integration. Public summary projection and historical
orchestration remain future separately authorized work.

**Closure: synthetic implementation Architect approved;
historical execution, publication and UI integration remain blocked.**

Validation after Architect remediation: 158 accounting/reporting synthetic
tests (26 added to the initial 132); all 650 regression tests passed in
9.79 seconds with loopback permission for the existing HTTP preview test.
Ruff lint/format, `pip check`, and whitespace checks passed. No historical
result is implied.

## 15. PQTA-003D-4B synthetic chronological runner

**Status: Implemented; Architect review pending.** Governing protocol,
dataset and reporting versions are unchanged. The four model modules and
4A modules are reused without edits. No historical execution is authorized.

### API and fixture boundary

`run_synthetic(fixture, universe, *, provenance, evidence,
evaluated_at_utc, alpha_selection=None) -> SyntheticRun` accepts only
typed, in-memory inputs. `SyntheticFixture(synthetic=True, features=...,
outcomes=...)` requires immutable tuples of `SyntheticFeatures` and 4A
`Outcome` objects, sorted uniquely by origin. Each scheduled origin must
have an explicit outcome audit; no unknown outcome is fabricated. Extra
future fixture rows may exist but are not admitted early. Seed history
may have holes. Missing feature rows become a null forecast-input view,
not new observations or filled feature history.

`SyntheticFeatures(origin, values, anomaly_involved_features=())` uses
the exact seven-feature tuple order. Origin `o` means the source candle
opens at `o-1h` and theoretically closes at `o`. Values and feature-window
anomaly claims are supplied, not calculated or repaired. A target's
validity asserts the approved consecutive-candle contract; the coordinator
does not read OHLCV or independently prove those assertions. Synthetic
attestation is a scope requirement, not cryptographic proof of data origin.
Synthetic feature availability is caller-attested: `feature_open_t`
alignment alone does not independently prove causal feature construction.
Historical source authentication remains unimplemented; synthetic
evaluation is not live-trading evidence.

The result exposes forecasts, `Admission` events, `ModelUpdate` audits
(exact eligible label origins, maximum outcome close and immutable fit),
4A report inputs/accountings/comparisons, the validated report and its
canonical UTF-8 bytes. There is no loader, writer, CLI, socket, publication
command or chart integration. Receipt time is explicitly injected; fixed
inputs/receipt/runtime produce byte-identical reports.

### Event order and isolation

At each scheduled UTC origin `o`, `advance(o)` admits only `h+1h <= o`
through the existing protocol helper. No target value, validity or
target-anomaly attribute is read before that gate. This is equivalent to
`s+2h <= o` for candle-indexed training rows. The current target at `h=o`
cannot enter history. The boundary phase admits closed outcomes and
audits previously pending forecasts, before any model update/refit or
new emission using distinct current-input
mappings. For a nonempty universe, a final `advance(end)` classifies the
last emitted target but does not add an origin or refit. An empty universe
has no admission, update, emission or scoring events, even with seed history;
its eight model/sample accounting entries have empty scores and zero counts.
Source tuple objects are not modified.

Forecast construction accepts only current feature/time fields and
separately admitted history. Post-closure score audit copies supplied
target/anomaly claims and derives only `feature_complete` and
`ar_lag_valid` from the supplied current/past fixture inputs. It preserves
anomaly types, affected fields and unverified/partial evidence labels;
no missing manifest evidence is inferred. Score failure never retracts
an already emitted forecast. Theoretical event time remains distinct
from historical publication and processing receipt time.

### Model adapters, refits and alpha

| Method | Coordinator mapping |
| --- | --- |
| Zero Return | Existing `zero_return` with time-only mapping; no target or history. |
| Mean | Closed outcomes become `HistoricalTarget` objects; existing `prepare_mean_history` and `predict_mean` apply samples, 720 minimum and `math.fsum` hourly. |
| AR(1) | The candle convenience preparers cannot directly consume 4A outcomes. A local mapping creates public `ARPair`/`ARHistory` from exact labels `h-1h,h`, using protocol eligibility, and `CurrentLag` only from closed label `o-1h`. Existing `fit_ar`/`predict_ar` retain OLS, variance guard, 720 pairs, numerical behavior and priority. No return/OLS formula is duplicated. Two adjacent valid labels assert the three required candle opens; target-anomaly unions cover those opens in sensitivity. |
| Ridge | Closed labels and same-origin supplied features become `ResearchRow` history; existing `prepare_history`, `fit_ridge`, `predict` retain finite-feature masks, 720 rows, train-only population scaling and QR behavior. |

AR/Ridge states are separate by sample and replaced only at 00:00 UTC.
Old state is cleared before fitting; a returned failed fit replaces
yesterday's parameters. An unexpected exception aborts instead of
producing a successful report. A warm fixture starting midday cannot
invent an earlier fit and waits until the next scheduled midnight.

The caller supplies `AlphaSelection` diagnostics; the runner never calls
`select_alpha` or searches penalties. Test selection must have its boundary
no later than the window start. One selected alpha is held throughout all
test refits and both samples. Missing/unavailable alpha skips Ridge fitting
and records `frozen_alpha_unavailable` in update audit. Prediction without
a fit uses the existing null-feature/sensitivity/input/insufficient-history
priority; it does not invent a penalty, fitted object or new forecast reason.
Thus a missing fit can carry `insufficient_training_history` even with
numerically sufficient seed rows, while the explicit selection blocker
remains visible in update/report metadata. This is not a numerical fallback.

Ridge fitting and selected-alpha prediction replay are Test-only, with a
valid frozen selection available at the forecast origin and the approved
selection boundary no later than the Test window start. Before that selection
is mathematically available, Ridge is not fit. Training-history reports are
accounting-only. Validation reports retain only supplied candidate tuning
diagnostics, never a selected-alpha replay. Outside Test, midnight update
audits record `ridge_replay_not_authorized` with no fit or selected alpha;
forecasts retain the approved abstention reasons and outcome accounting.
This audit-only explanation is not a new forecast/score status or reason.
All four methods and both samples remain in accounting; no unavailable
model silently disappears. Test windows create all four comparison scopes
through 4A, whose blocked-comparison, count, coverage, timestamp-digest and
null-metric policies are unchanged. No raw forecasts or summaries are saved.

### Runtime and remaining boundaries

No dependencies were added or changed. The inspected `pqta` environment
uses native arm64 Python 3.12.15, Polars 2.0.0, DuckDB 1.5.6, CCXT 4.5.89,
Pandera 0.34.1, pytz 2026.5, pytest 9.1.1 and Ruff 0.17.1. Coordination
uses the standard library and existing modules; it does not call ingestion.
Bit-identical results across different Python/libm platforms are not promised.

Fixture target/source validity, feature causality, manifest claims and
identity digests are caller assertions. Report validation is in-memory
consistency, not source-byte, anomaly-evidence or PIT verification. All
PIT/decision flags remain false. No historical metrics, BTC predictability,
transaction costs, execution feasibility, trading confidence or profitability
are established. Historical runner/publication, dashboard, signals and
orders remain absent or blocked. Stop for Architect review; no Git closure
is authorized by this implementation task.

### Synthetic validation

After Architect remediation, all 47 coordinator tests passed in 4.23 seconds;
the complete repository suite passed 697 tests in 12.58 seconds using
`pqta` (loopback permission
for the existing preview HTTP test). Ruff lint and format check, `pip check`
and Git whitespace checks passed. The 25 protected dataset file hashes,
four immutable origin-build file hashes and canonical manifest digest
matched their preflight baselines; the three pre-existing QNT-003 header
diffs remained byte-for-byte unchanged. No files were staged or published.
These are synthetic software checks, not historical predictive evidence.
The regression additions independently test the non-Test period guard with
a valid, clock-available selection, and exercise actual training/validation
midnights with 721 seed rows and a supplied valid selection (whose availability
is necessarily later under the real protocol). Both Ridge fit and prediction
calls are forbidden in those integration tests. Empty windows with seed history
are tested across all three periods with admission/model/scoring call traps.

## 16. PQTA-003D-5A lossless historical adapter and readiness decision

**Status: Implemented; Architect review pending.** The owner approved a
lossless historical representation to resolve the source-mapping ambiguity,
not a change to `pqta-model-evaluation-v1`, its 4A `Quality`/`Outcome`/`Score`
types, `run_synthetic`, the models or the governing research protocol.
The detailed mapping is in
[PQTA-003D-5A_HISTORICAL_ADAPTER.md](PQTA-003D-5A_HISTORICAL_ADAPTER.md).

### APIs and validation boundary

`audit_pinned_history(root) -> HistoricalAudit` verifies exact
approved Silver, Gold, manifest and four immutable origin-build files
before Parquet inspection. It checks the expected artifact file set,
pinned digests, canonical JSON and recorded identity hierarchy, then uses
the same semantic validation core as
`audit_frames(silver, gold, ledger, manifest, *, identity)`.
This second API is also the synthetic in-memory test boundary;
source identities supplied to it are not by themselves verified file bytes.

Validation preserves the existing schemas and canonical seven-feature
order, exact UTC hourly source/open/origin alignment, original source-row
identity, approved split boundaries, finite/null feature states, target
validity/reasons and separate target/feature/AR-lag masks. No feature or
target dataset is regenerated. The final out-of-split origin is retained
for audit and excluded from all three period universes. The audit is
deterministic in memory and writes no readiness or evaluation artifact.

### Architecture decision: historical is not synthetic `Outcome`

Typed `HistoricalFeatures` and `HistoricalOutcome` retain source information
without normalizing it into the restricted 4A quality vocabulary. Preserve:

- Target-endpoint anomaly records separately from feature-window records.
- Raw anomaly field names and values, including exact `candle` and `unknown`
  tokens; neither is translated into `open`, `high`, `low`, `close` or `volume`.
- Nullable feature states and null reasons, original target validity and
  invalid reasons, source identifiers and source row/timestamp identity.
- Original records with `unresolved` association when source evidence cannot
  establish target-endpoint versus feature-window membership.

The standalone `associate_anomaly` helper preserves records from an unknown
source column under `unresolved`. This does not relax `LEDGER_SCHEMA`:
the strict source audit rejects unknown ledger columns. Both existing
anomaly columns have explicit associations; zero unresolved associations
in the approved dataset is not a claim that evidence or causes are resolved.

Association follows explicit source evidence, not an inferred interpretation
of an anomaly flag. An unprojectable field is an explicit finding, not data
to discard. These objects are not accepted as synthetic fixtures, and no
adapter path constructs 4A `Quality`, `Outcome` or `Score` records. No
historical model fitting, alpha selection, forecasting, score classification
or metric calculation is performed.

### Readiness and evidence limitations

The audit reports observed anomaly categories, target-endpoint and
feature-window associations, unresolved associations, evidence completeness
and fields requiring additional projection policy. A successful read-only
inspection may be `ready_for_architect_review`; it cannot establish full
execution readiness. `execution_ready=false` remains explicit. The approved
5B policy and 5C compatibility implementation below do not authorize historical
execution. Any unresolved association affecting that projection remains
a visible limitation or blocker rather than a presumed quality claim.

Pinned source-byte authentication establishes that the inspected inputs
match the approved snapshots. It does not authenticate referenced anomaly
evidence, resolve root causes, prove historical publication availability or
upgrade Gold's null `available_at`/false `decision_eligible`. Manifest
references and their evidence limitations are preserved. The 4A reporting
milestone still has `artifact_bytes_verified=false`; the new adapter's
separate source audit does not change that contract or certify a report.

The historical adapter is deliberately not an execution bridge. The approved
[5B policy](PQTA-003D-5B_HISTORICAL_PROJECTION_POLICY.md) and compatibility
implementation below preserve the separate anomaly scopes and strictly block
unsupported fields rather than losing evidence. Historical execution still
requires explicit owner authorization. Lane A evaluation remains
unauthorized; Lane B, trading and backtesting remain blocked. No publisher,
dashboard integration, signal or order functionality is introduced.

## 17. PQTA-003D-5C historical projection compatibility

**Status: Implemented; Architect review pending.**
`historical_projection.py` applies policy `pqta-003d-5b-projection-v1` to the
existing historical adapter. The scope is read-only compatibility planning
and auditing, not historical evaluation, forecasting, scoring or reporting.
The 4A contracts, synthetic runner guards, model mathematics and governing
`qnt-003d-design-v1` protocol remain unchanged.

### Source and evidence boundaries

`verify_pinned_source(root)` uses the approved pinned-history verification
mechanism, then binds source records and immutable source identities to a
verified receipt. `bind_synthetic(adapter)` is the separate in-memory fixture
boundary: it cannot establish authenticated historical bytes. A caller Boolean
or syntactically valid digest is not proof. Source authentication checks the
approved bytes, not the completeness of referenced anomaly evidence, its root
causes or historical publication time. These remain distinct metadata states;
no synthetic fixture or unverified anomaly evidence is upgraded to verified.

### Projection views and fail-closed scope

- `plan_forecast_fields` returns only allowlisted feature/time information
  and an opaque identity reference without outcome access or a resolver.
- `plan_completed_history` gates target and target-flag access on exact
  theoretical closure, `h+1h <= forecast_origin`, then preserves the approved
  method/sample masks. A-sensitivity remains a retrospective training and
  current-input exception, not merely a scoring-only filter.
- `project_closed_outcome` keeps its full lossless audit attachment and
  derives supported target-endpoint-only 4A Quality; it retains original
  reasons with explicit priority normalization. Feature-window records and
  explicit `feature_complete`/`ar_lag_valid` remain separate. Before closure
  only clock/identity information is exposed, never future target metadata.
- `audit_compatibility` retains the requested scope and produces canonical
  report bytes/digest in memory, with no generated files or model calls.

Projection classifications are `compatible`, `blocked`, `failed`, `audit_only`
and `not_closed`, not new forecast/score statuses or abstention reasons.
Unsupported `candle`/`unknown` tokens are preserved verbatim. Unknown anomaly
types, unresolved associations and inconsistent source metadata fail closed.
Unsupported required rows block the entire requested scope: no origin is
silently dropped, no incomplete outcome is fabricated and no reduced-universe
performance metric is calculated. Out-of-split origins remain audit-only;
missing hours never compress adjacency or become fabricated candles.

Canonical compatibility reporting retains policy/source/receipt identity,
scope, all classification counts, blocking reasons, unsupported categories
and source-integrity state. It is deterministic for pinned inputs and fixed
configuration, with a separate payload digest. It is not a
`pqta-model-evaluation-v1` historical result. All three readiness values stay
false: `execution_ready`, `point_in_time_verified`, `decision_eligible`.

The immutable source receipt binds the factory-issued source object, exact
source key/index/origin and canonical record bytes. Copied/manual receipts or
caller verification flags do not mint that binding. This is an in-process
integrity boundary, not a cryptographic signature or hostile-Python sandbox.
The receipt authenticates the snapshot read, not future filesystem contents.
Source and policy identities remain separate from the projection build
identity, which pins code content, dependencies and serializer configuration.
`payload_sha256` hashes the canonical report without its own digest field;
the returned `canonical_report` includes that field. Raw arrays preserve
order/multiplicity, nulls and signed zero; datetimes use microsecond UTC `Z`
encoding. Canonical object keys are sorted and the UTF-8 JSON ends with LF.

### Read-only compatibility acceptance

At the fixed source analysis boundary `2026-10-20T13:00:00Z`, the authenticated
pinned source produced the following **representational compatibility** counts,
not forecasts, scores, predictive metrics or evaluation results:

| Classification | Origins |
| --- | ---: |
| Total audited origins | 50,845 |
| Compatible | 49,692 |
| Blocked | 1,152 |
| Failed | 0 |
| Audit-only (final origin outside the approved test interval) | 1 |
| Not closed | 0 |

Unsupported-field counts are **per affected origin and overlap**:
`candle=1,149`, `unknown=680`, with 677 origins containing both. All original
rows remain retained. The full requested scope is not projectable; compatible
rows must not be repackaged as a reduced executable evaluation universe.
All readiness flags remain false, including for representationally compatible
rows. The source origin-build identity remains
`693697c2dc1ea82297959c39b2b6ec8da472f8bc74070e4cd4043d106246cc96`.
The in-memory compatibility payload digest was
`558e3132c3f160aaa21d898d8673ffc2c60a2623bf151b9cd3ab89f370dc9427`;
no generated report file was written or published.

### Testing and remaining authority

With `pqta` active, run
`python -m pytest -q tests/test_historical_projection.py`. Synthetic tests
exercise representable and blocked cases, lossless evidence, source binding,
closure/isolation, sample masks and canonical determinism. Read-only pinned
compatibility auditing is not historical model execution or predictive
evidence. Historical execution requires separate authorization; historical
reporting remains deferred under ADR-5B-04 and needs a reviewed interface.
Lane B, backtesting, signals, dashboard integration and trading remain blocked
or unimplemented. No result is relabeled synthetic to bypass existing guards.

Acceptance validation passed 57 new projection tests, 387 relevant existing
research tests and the full 816-test suite (14.90 seconds on rerun). The first
full-suite attempt passed 815 tests and failed only the existing localhost
HTTP test because the sandbox prohibited socket binding; no test expectation
was changed. Ruff lint/format, `pip check`, documentation links/structure and
Git whitespace checks passed. The 25 protected dataset hashes, four immutable
origin-artifact hashes and canonical manifest digest remained unchanged, as
did the three pre-existing QNT-003 header edits. No dependency, existing
research contract, model implementation, synthetic runner or reporting-engine
change was needed.

## 18. PQTA-003D-5E native historical anomaly representation

**Status: Implemented; Architect Review Pending.** Implementation and testing
were separately authorized after the
[approved 5D design](PQTA-003D-5D_UNSUPPORTED_ANOMALY_REPRESENTATION.md).
The approved design document and ADR-5D-01–06 remain unchanged. Exact Phase A
schema, API, canonicalization and acceptance decisions are in the
[5E implementation contract](PQTA-003D-5E_IMPLEMENTATION_CONTRACT.md).
This authorization covers native representation and read-only auditing,
not historical execution, forecasting, scoring or result publication.

### Public boundary and authoritative source

`historical_representation.py` reuses existing `HistoricalRecord`,
`HistoricalOutcome` and `HistoricalAnomaly` objects rather than cloning 4A
Quality or the historical adapter. `NativeOccurrence` retains original raw
annotation content, source/manifest references, collection, association role,
original position and linkage findings. `NativeEnvelope` retains that existing
lossless record and its occurrences. `NativeResult` and `NativeAudit` describe
representation findings, not predictions, scores or evaluation-status records.

The public source factories are `verify_pinned_representation_source(root)`
and `bind_synthetic_representation(adapter, *, manifest_bytes=None)`.
`represent_closed(source, origin, *, checked_at, policy=...)` inspects a
closed audit row; `audit_native(source, *, checked_at, origins=None, policy=...)`
conserves the declared scope and returns canonical audit bytes in memory.
There is no writer, historical runner, model call, native forecast API,
label-admission API, executable scorer or dashboard route.

Schema `pqta-historical-anomaly-representation-v1` and policy
`pqta-003d-5d-representation-v1` have exactly the existing manifest's seven
literal field tokens: `open`, `high`, `low`, `close`, `volume`, `candle`,
`unknown`. `missing_hour` requires `candle`; the existing discrepancy and
shortened-close types permit OHLCV/`unknown`. Original nulls, numeric values,
reason order, array order and duplicate occurrences are retained. Endpoint,
feature-window and unresolved collections stay separate. `candle` is not
expanded to five field claims, and `unknown` is not interpreted as numeric
null, missingness, an unresolved role or a universal mask.

Unknown future types/tokens remain opaque raw evidence while native semantic
representability is blocked; they do not enlarge v1's vocabulary. Invalid
known type/token combinations fail validation. Annotation/manifest matches
require an exact unique timestamp/type identity plus consistent supplied
field, review, severity and evidence-reference content. Missing or ambiguous
links block interpretation, and contradictions remain explicit. No positional
fallback, fabricated detail, token expansion or evidence-status promotion is
permitted. Unresolved associations can be retained natively without resolving
their model/scoring meaning.

### Six independent audit dimensions

| Dimension | What the native audit reports | What it does not establish |
| --- | --- | --- |
| Native representability | `represented`, `blocked`, `failed`, `not_inspected` under the named native schema/policy. | Legacy 4A compatibility or model/sample eligibility. |
| Legacy 4A compatibility | Existing unchanged 5C classification for the same source-bound origin. | Native acceptance, a new model abstention or permission to drop blocked rows. |
| Source authentication | Factory-issued pinned-history versus synthetic-fixture source binding. | Referenced anomaly-evidence verification or historical publication. |
| Association resolution | `resolved`, `unresolved`, `not_inspected`, separately from literal field attribution. | Guessed endpoint/window roles or a root cause. |
| Evidence completeness | Recorded references unverified, unresolved linkage, no occurrences or not inspected. | Independently verified archive/REST evidence or anomaly-free history. |
| Temporal closure | `closed` or `not_closed` from exact clocks. | Publication time, PIT availability or decision eligibility. |

Counts are derived for every requested origin on each dimension. The 5C
reference counts in §17 remain legacy findings, never hardcoded native output
or a reason to exclude 1,152 origins from a future evaluation universe. A
positive native result does not make an evaluation `complete`. Readiness/PIT/
decision flags remain false for the scope and its results.

### Receipt reuse and temporal isolation

The pinned native factory reuses `historical_projection.verify_pinned_source`
and its exact source-bound receipt. Native contexts additionally retain strict
raw manifest bytes/identity and per-record binding. Manual/copied receipts,
reconstructed contexts, plausible SHA-256 text and caller verification flags
cannot establish historical authentication. The separate synthetic factory
never upgrades its source mode. The boundary protects in-process consistency,
not hostile Python introspection or signature verification. The observed raw
manifest hash is bound separately; it is not relabeled as a previously pinned
raw hash in the legacy receipt.

`represent_closed` validates source/clock/key identity before any outcome
inspection. If `origin+1h > checked_at`, there is no envelope, full-row digest
traversal, target value/validity/endpoint flag read or outcome-derived anomaly
diagnostic. Out-of-split rows remain audit-only with no envelope; their
independent closure axis still reports the clock, including the final origin
that closes after the pinned analysis boundary. Existing forecast-only plans
are unchanged: no source context, full manifest, native attachment, outcome
resolver or current/future target information is exposed through them.

### Canonical schema and three identity levels

Serializer `pqta-003d-5e-canonical-v1` is separate from unchanged 5C
`pqta-003d-5c-canonical-v1` and comparison timestamp encoding. It uses UTF-8
JSON with sorted object keys, compact separators, one final LF and aware
zero-offset timestamps encoded with six fractional digits and `Z`. Original
raw timestamp strings remain strings. Binary64 values use finite round-trip
JSON numbers, preserving `-0.0`; integers are not coerced to floats. Missing
keys remain distinct from explicit null. Array order and duplicate occurrence
positions are preserved. NaN, infinity, duplicate JSON keys and unknown schema,
policy or serializer versions fail closed.

| Identity | Inputs and separation |
| --- | --- |
| `representation_spec_id` | Logical source dataset/build identity, source byte references, manifest reference, schema/policy/protocol contracts, fixed scope/closure boundary and preservation rules. No implementation revision or runtime clock. |
| `representation_build_id` | Spec ID, relevant code-content hash, exact dependency versions and serializer/configuration. Code-content-only changes under unchanged approved spec encoding affect build identity, not an unchanged logical specification. |
| `payload_sha256` | Canonical audit object bytes with its own digest field omitted; the returned report includes that field. Not an existing dataset/build or comparison identity. |

No source identity, existing serializer or comparison digest is overwritten.
No representation artifact is published. `canonical_payload` and the identity
helpers validate serialization/specification inputs; accepting a well-formed
digest never authenticates source bytes by itself. Processing time is not
historical availability, and no runtime timestamp enters logical identity.
Deterministic repeats under one representation build are allowed; conflicting
payloads under the same build ID fail closed within the current process.
This is not persisted/cross-process immutable-artifact verification. A future
publisher and historical reporting interface remain separately deferred.

Identity invariance is conditional on fixed logical inputs and the unchanged
approved canonical-spec encoding. There is no automatically sampled runtime
clock in the spec. The explicit `checked_at` cutoff is part of the declared
scope, so changing it intentionally changes spec/build/payload identities.
Changing source byte references (including raw-manifest bytes/hash) changes
their logical specification; changed canonical payload bytes change its SHA-256.
Changed bytes at an approved pinned source fail authentication rather than
silently authorizing a new historical source; identity helpers provide no such
authorization.
Code-only changes that preserve the logical inputs and approved encoding change
the build rather than the logical spec. The serializer-version test changes
the build helper's declared version input; it does not execute another codec.
Actual audit policies reject unapproved serializer versions. A future codec
migration remains reviewed/versioned and is not guaranteed to preserve spec bytes.

### Read-only acceptance findings

The final 112 synthetic representation tests passed in 2.03 seconds, including
literal/type restrictions, roles/order/multiplicity, missing/null/signed zero,
full-manifest linkage contradictions, copied/forged contexts, closure non-access,
independent legacy/native classifications and conflicting-build rejection.
The complete suite passed **928 tests in 15.31 seconds**, with no failures,
skips or collection errors. All 816 existing tests are included. The earlier
restricted existing-test run had 815 passes and one localhost socket-binding
permission failure; the final full run used loopback permission without
altering tests. Ruff lint, Ruff format (80 files), `pip check`, documentation
and Git whitespace checks passed. Pip warned that its cache was disabled;
it reported no broken requirements. No dependency was installed or changed.

At fixed `checked_at=2026-10-20T13:00:00Z`, the approved pinned source factory
authenticated the original bytes and bound the observed raw manifest. A
complete, read-only **per-origin native scan** then retained all 50,845 origin
identities exactly once:

| Independent dimension | Actual findings |
| --- | --- |
| Native representability | `represented=50,844`; `not_inspected=1`; `blocked=0`; `failed=0`. |
| Legacy 4A compatibility | `compatible=49,692`; `blocked=1,152`; `audit_only=1`; `failed=0`; `not_closed=0`. |
| Source authentication | `authenticated_pinned_history=50,845`. |
| Association resolution | `resolved=50,844`; `not_inspected=1`; no unresolved source roles observed. |
| Evidence completeness | `no_occurrences=49,692`; `recorded_references_unverified=1,152`; `not_inspected=1`. |
| Temporal closure | `closed=50,844`; `not_closed=1`. |

Each dimension conserves the full scope independently. These are actual
metadata observations, not hardcoded native output or predictive results.

**Evidence counting unit:** `recorded_references_unverified=1,152` means
**1,152 distinct source-bound origins**, not anomaly occurrences, manifest
records, evidence references or evidence files. `audit_native` first rejects
duplicate/unbound origins, builds one `NativeResult` per origin, then counts
one value of each dimension per result. After successful core validation,
`represent_closed` aggregates that origin's endpoint/window/unresolved
occurrences before assigning one evidence category: no occurrences gives
`no_occurrences`; any unmatched linkage gives
`unresolved_linkage`; all nonempty occurrences matched gives
`recorded_references_unverified`. Repeated occurrences do not increase this
origin count. `no_occurrences` does not certify universally clean source data.

The numerical equality with `legacy blocked=1,152` is a finding of this pinned
snapshot only, not a coded relationship, proof of identical sets or a general
invariant. The two dimensions are computed independently. Supported OHLCV
anomalies can be legacy-compatible while their recorded references remain
unverified, as the seven-token synthetic tests demonstrate. Source-byte
authentication does not verify any referenced anomaly-evidence bytes.

The final origin at 13:00 is outside the half-open Test split and its target
closes at 14:00. It has no native envelope or outcome inspection at this cutoff.
Legacy `audit_only` precedence therefore coexists honestly with native
`temporal_closure=not_closed`; no split boundary or v1 count changed.
`resolved` refers to source-column association roles, not anomaly root causes
or independently verified evidence. All readiness/PIT/decision flags and
`anomaly_evidence_verified` remained false.

For that exact final origin, status fields at the historical cutoff are:

| Field | Value at checked-at `2026-10-20T13:00:00Z` | Meaning |
| --- | --- | --- |
| `period` | `outside_approved_evaluation_window` | The Test end is exclusive; do not admit the origin. |
| `native_representability` | `not_inspected` | No row-level native-schema outcome assessment, not `failed` or unsupported. |
| `legacy_4a_compatibility` | `audit_only` | Unchanged legacy out-of-split precedence. |
| `source_authentication` | `authenticated_pinned_history` | Registered source-byte authentication remains independent of outcome inspection. |
| `temporal_closure` | `not_closed` | The theoretical target close is `2026-10-20T14:00:00Z`. |
| `association_resolution` / `evidence_completeness` | `not_inspected` / `not_inspected` | No endpoint/occurrence evidence diagnostics are derived. |
| `envelope` / `findings` | null / `["audit_only"]` | No target, validity, anomaly flags, attachment or resolver. |

The branch checks **outside-split OR not-closed** before a full-row digest or
outcome read. At checked-at 14:00, `temporal_closure` becomes `closed`, but the
origin remains `audit_only` / `not_inspected`, with null envelope and unchanged
audit-only findings. Clock closure does not move it into Test or trigger outcome
inspection. Schema support and source authentication are not reclassified as
failures. Source authentication is a separate offline-verification boundary;
this no-outcome-access claim concerns the temporal inspection/forecast APIs,
not a claim that source authentication never reads the historical artifact.

Canonical payload verification used a **separate bounded 39-origin scope**:
the first/last two source origins plus bound origins at each manifest anomaly
timestamp and one/two hours later, deduplicated and sorted. Two `audit_native`
calls, including reversed input order, produced identical canonical bytes.
The following identities belong to that anchor scope, not a published
full-history representation artifact or an evaluation build:

| Anchor identity | Value |
| --- | --- |
| `representation_spec_id` | `436bec6c7b6d4985daf900347e08199c92d0ca4b52842043841c6f1d24ae7777` |
| `representation_build_id` | `174c74ae91fa41936a3ad0cf342ba15152e24ba248f818d1feda6e297fd132d1` |
| `payload_sha256` | `5def9a224bfea5331cd8c08e50b71308f2e188994db2e5cfc0587b27a72c9ba8` |
| Code-content SHA-256 | `65d6a4017651d772dee8a3a646a84ad628baad2e7cb6566157888aac2d934b38` |

The successful full scan plus anchor verification took 175.84 seconds. An
earlier full-payload batched attempt reached its 300-second limit after 40,000
origins; it was incomplete and is not the source of the full-scope counts.
The final scan avoided repeated full-row batch serialization. No full-history
canonical artifact was generated, written or published. The verifier's model,
scoring, network and dataset-write entry points were guarded to fail if called.

All 25 protected dataset hashes, four immutable origin files, source-build
identity and canonical manifest digest remained unchanged. Canonical/raw
manifest SHA-256 was
`86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4`.
The approved 5D design and three pre-existing QNT-003 header edits were untouched.
Only new source/tests/implementation-contract documentation and these directly
affected documentation files were changed; no existing runtime contract changed.

### Environment and remaining gates

The verified development environment is native arm64
Python 3.12.15, Polars 2.0.0, DuckDB 1.5.6, CCXT 4.5.89, Pandera 0.34.1,
pytest 9.1.1 and Ruff 0.17.1. This implementation adds no dependencies.

4A contracts, the synthetic runner/reporting guards, 5B/5C compatibility
semantics, numerical models, sample masks, refit/alpha rules and temporal
closure are unchanged. Matching source bytes does not independently verify
anomaly evidence or resolve root causes; historical `available_at` stays null.
Native historical scoring/accounting/reporting remains deferred under
ADR-5D-06 and requires a separately reviewed interface. Historical execution
requires explicit owner authorization after blockers are resolved. Lane B,
backtesting and trading remain blocked; the chart stays `NO SIGNAL`.
`execution_ready=false`, `point_in_time_verified=false` and
`decision_eligible=false` remain mandatory. Synthetic/read-only representation
validation establishes no predictive accuracy, profitability or live-trading
evidence.
