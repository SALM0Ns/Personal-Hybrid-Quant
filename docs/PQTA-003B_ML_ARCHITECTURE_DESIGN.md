# PQTA-003B — Retrospective ML Research Architecture (Design Only)

**Status:** Complete — Architecture Approved (Design Only).
Decisions A–F below authorize this documentation and status correction,
**not** target construction, dataset publication, baseline execution, Ridge
fitting, scoring, backtesting, inference, signals, or trading. No experiment
has been run. The owner-reviewed `qnt-003d-design-v1` research protocol remains
the governing statistical contract; this document does not amend it.

## 1. Scope, approvals, and evidence boundary

| Approved architecture decision | Boundary in this design |
| --- | --- |
| A — Lane A only | A retrospective statistical study may be designed. Executing either Lane A sample still requires separate approval. Lane B remains blocked. |
| B — Separate ledger | A research-only forecast-origin ledger is separate from Silver, Gold features, forecast records, and score records. |
| C — Four methods | Zero Return, expanding Mean, AR(1), and exactly seven-feature Ridge; no other model family. |
| D — Existing splits | Use the forecast-origin intervals in QNT-003B §4 without moving boundaries. |
| E — Dependency evaluation | Compare NumPy-only with NumPy plus scikit-learn; install and pin neither here. |
| F — Design only | No executable ML implementation, target, forecast, or metric artifact. |

The normative target, event order, method rules, sample rules, metrics, and
exclusion precedence are in `docs/QNT-003A_RESEARCH_DESIGN.md` and
`docs/QNT-003B_EVALUATION_PROTOCOL.md`, as closed by
`docs/QNT-003D_FINAL_RESEARCH_DESIGN.md`. In case of a future discrepancy,
preserve `qnt-003d-design-v1` and request a versioned owner decision; do not
silently select a different formula or policy. QNT-003A/B/D still contained
pre-closure status wording when this design was prepared; that status is not
an amendment to their technical sections. Historical approval requests also
remain in QNT-003B §9 and QNT-003D §6; `docs/DECISIONS.md` records the later
owner review, while separate execution authorization is still required.

The intended inputs are the *existing* Binance Spot BTC/USDT 1h Silver
Parquet, QNT-002B Gold feature Parquet, and 19-record candidate anomaly
manifest. Pin their exact bytes and digests before any later authorized run:

| Input | Current local identity |
| --- | --- |
| Silver | `data/silver/binance/1h/BTC-USDT.parquet`; SHA-256 `edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3` |
| Gold | `data/gold/qnt-002b/btc_usdt_1h/candidate_v1/features.parquet`; SHA-256 `18f70e22ce189787e74fad2d8f7d14202625e09f355bf81792f2aac7bcd1a66d` |
| Manifest | `configs/qnt-002b-btc-anomalies.candidate.v1.json`; canonical SHA-256 `86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4` |

The fixed `analysis_as_of` is `2026-10-20 13:00:00 UTC`. Gold has 50,845
hourly rows, including 14 explicit missing hours; all 50,845 `available_at`
values are null and all `decision_eligible` values are false. The selected
Silver revision and candidate manifest are retrospective. No current row is
historically point-in-time verified, regardless of mathematical alignment.
The manifest's missing-hour evidence is archive/local absence without retained
raw REST gap-window responses; shortened-close interpretation and the disputed
close/volume remain unresolved. The ledger must preserve these limitations.

## 2. Proposed versioned research dataset contract

Proposed contract identifier: `pqta-003b-origin-ledger-v1` (not yet approved
for implementation). The **Gold source timeline** is keyed by candle open
`t`; the corresponding **research audit timeline** is keyed by forecast origin
`o=t+1h`. A future immutable origin ledger may preserve **one row per Gold
candle-open hour**, including missing and out-of-split origins, keyed uniquely
by `(exchange, symbol, timeframe, forecast_origin_utc)`. Its origin rows are
sorted and strictly one hour apart. The **evaluation universe** is only the
subset whose origins fall inside one of the approved chronological splits in
§3. A non-null `split_id` from `training_history`, `validation`, `test`, or
`outside_approved_evaluation_window` classifies every audit row by the fixed
half-open intervals; the last value excludes a row from all forecast, score,
and per-method evaluation counts without removing it from the audit ledger.
The sample-specific objects are nested within one origin row, not duplicate
origin keys. Timestamp fields are nullable only where indicated and stored
as timezone-aware UTC microseconds.

| Field or family | Type and invariant |
| --- | --- |
| `exchange`, `symbol`, `timeframe` | Non-null strings, exactly `binance`, `BTC/USDT`, `1h`. |
| `forecast_origin_utc` | Non-null UTC hour; primary origin key `o`. |
| `split_id` | Non-null classification by §3's fixed forecast-origin intervals, or `outside_approved_evaluation_window`; out-of-split rows have no method forecast or score record. |
| `feature_open_t`, `feature_theoretical_close_at` | Non-null UTC hours; `t=o-1h`, close boundary `o`. Neither is verified publication. |
| `target_open_at`, `target_theoretical_close_at` | Non-null UTC hours; `target_open_at=o`, close boundary `o+1h`. The boundary exists even if the candle does not. |
| Seven feature columns | Nullable Float64 in the exact QNT-002B order below; never NaN or infinity. Copy pinned Gold values without recalculation. |
| `null_reason__<feature>` | Nullable closed-vocabulary string copied from Gold: `missing_candle`, `gap_in_window`, `insufficient_history`, `zero_denominator`; null exactly when the feature is non-null. |
| `source_present`, `missing_hour`, `quality_flags`, `anomaly_involved_features`, `value_sensitive_features`, `involved_anomalies`, `source_discrepancy_fields`, `recorded_source_close_at` | Copy Gold feature-side provenance. Retain ordered record references and field sensitivity; do not replace Silver values. |
| `current_candle_present`, `next_candle_present`, `current_candle_valid`, `next_candle_valid`, `current_candle_complete`, `next_candle_complete`, `consecutive_opens` | Non-null Boolean audit facts from exact Silver open-key lookup and fixed analysis boundary; never infer adjacency from neighboring non-null rows. A whole-source schema/OHLCV failure stops publication. |
| `target_next_1h_log_return` | Nullable Float64, defined only by the two adjacent validated, fully closed, finite-positive Silver closes. Never zero-fill. |
| `target_valid`, `target_null_reasons`, `target_primary_null_reason` | Non-null Boolean, sorted unique reason list, and nullable exclusive reason. The reason list is empty and primary null when valid. Preserve all applicable failures. |
| `target_endpoint_anomalies`, `target_value_sensitive` | Ex-post records at `t` and `t+1h`, including type, fields, evidence reference, and a separate close-value sensitivity bit. These are **outcome/audit fields**, never predictor inputs at `o`. |
| `feature_complete` (`F_t`), `target_valid` (`V_t`), `target_manifest_anomaly` (`A_T`), `feature_manifest_anomaly` (`A_F`), `ar_lag_valid`, `ar_lag_manifest_anomaly` (`A_R`) | Distinct non-null audit Booleans. `F_t` means all seven finite features. `A_T` checks either target endpoint; `A_F` checks every feature dependency window; `A_R` checks the two current-lag endpoints. |
| `lane_a_primary`, `lane_a_sensitivity` | Nested sample metadata with fixed sample name and target-score eligibility (`V_t`; respectively `V_t AND NOT A_T(t)`). Method-specific training and forecast eligibility remains in method records; no single row bit substitutes for them. Sensitivity masks use the same pinned manifest ex post. |
| `gold_available_at`, `gold_decision_eligible`, `research_only` | Copy original nullable Gold availability and Boolean eligibility unchanged; `research_only=true` is a separate non-trading marker. Never turn Gold's false eligibility into true. |
| Provenance fields | Non-null `dataset_spec_id`, dataset contract/protocol version, `analysis_as_of`, exact Silver/Gold/manifest digests, `source_feature_version`, and `manifest_version`. For a future built artifact, record its separate `artifact_build_id` and `artifact_sha256` in build provenance; neither is a Silver or Gold source digest. |

The seven fields, in immutable order, are `log_return_1h`,
`volatility_24h`, `volatility_168h`, `momentum_24h`, `momentum_168h`,
`volume_change_1h`, and `normalized_range_1h`. Gold's feature version is
`qnt-002b-v1`; its source hash means exact Silver Parquet bytes. The
PQTA-002B in-memory adapter has a different canonical-observation hash
contract and is **not** a replacement for this pinned historical Gold.
QNT-002A retrospective regime labels are not predictors.

Target formula, with no off-by-one reinterpretation:

```text
y_t = target_next_1h_log_return(t) = ln(C_(t+1h) / C_t)
feature_open_t = t = forecast_origin_utc - 1h
target_open_at = t + 1h = forecast_origin_utc
target_theoretical_close_at = t + 2h = forecast_origin_utc + 1h
```

`C_u` is the validated Silver close for the candle opening at `u`. The
target requires both exact hourly opens, valid positive finite closes, and
both theoretical candle closures no later than fixed `analysis_as_of`.
`target_null_reasons` uses only the applicable QNT-003B §6 codes:
`current_missing`, `next_missing`, `current_incomplete`,
`next_incomplete`, `nonconsecutive_opens`, `current_invalid_source`,
`next_invalid_source`, `current_invalid_close`, `next_invalid_close`, and
`target_nonfinite`. Its exclusive primary reason follows that section's
total order; the complete list retains overlaps. A source-wide schema,
market-identity, timestamp, uniqueness, or OHLCV audit failure aborts
publication instead of fabricating an otherwise valid target. The final
origin may retain `next_missing` and `next_incomplete` as applicable, but
never a synthetic outcome. The disputed 2021-04-23 01:00 close can affect
the targets indexed at both 00:00 and 01:00 UTC; disputed volume is only
provenance for this close-only target. Shortened closes at either endpoint
remain potentially value-sensitive, including the unresolved August case.

`V_t` does not imply `F_t`; `F_t` does not imply a valid next-hour outcome.
A-primary retains a numerically valid target even if anomaly-flagged.
A-sensitivity excludes a target with **any** pinned manifest record at either
endpoint for training and scoring; AR and Ridge have their additional
forecast-side and historical-training masks from QNT-003B §6. The target's
future anomaly status may be written into the eventual ledger only after
target observation. A forecasting interface must expose only current/past
features and admitted *historical* labels, never current-row target fields
or next-candle quality metadata.

## 3. Time, splits, and sample flow

At UTC origin `o`, the mathematical event sequence is: close and validate
candle `t=o-1h`; admit historical labels with theoretical close `<=o`;
perform a scheduled 00:00 UTC refit; emit the forecast for `y_t`; after
`o+1h`, audit/score its outcome. At equality, the earlier close/validation
event precedes refit. The latest training label indexed by `s` satisfies
`s+2h <= o`. The current label `y_t` cannot satisfy that condition. A
feature's own `timestamp=t` is an **open**, not its availability time.
Closure, local `ingested_at`, publication, manifest evidence, and
`generated_at` are different clocks; none may be substituted for another.

| Period | Forecast-origin interval `[start,end)` UTC |
| --- | --- |
| Training/history | `[2021-01-01 01:00, 2024-01-01 00:00)` |
| Validation | `[2024-01-01 00:00, 2025-01-01 00:00)` |
| Test | `[2025-01-01 00:00, 2026-10-20 13:00)` |

The first Gold candle opens at `2021-01-01 00:00 UTC`, giving the first
research forecast origin `2021-01-01 01:00 UTC`. The last Gold candle opens
at `2026-10-20 12:00 UTC`, giving the last research audit origin
`2026-10-20 13:00 UTC`. Because the test interval ends **exclusively** at
that same 13:00 boundary, the last audit origin has
`split_id=outside_approved_evaluation_window`. The last **in-split** test
origin is `2026-10-20 12:00 UTC`; its target may theoretically close at
13:00. For the pinned 50,845-row Gold source timeline, a full mapped audit
timeline would therefore contain 50,845 origins, of which 50,844 fall inside
the approved split union and one falls outside. This classification does not
move or extend a split boundary.

The first theoretically feature-complete 168-hour row can occur only after
168 consecutive returns (169 candles) from an observed segment start; the
24-hour features need 25 candles. A missing hour remains an explicit null
row, restarts rolling warm-up, and invalidates targets touching that hour.
Do not forward-fill, interpolate, shift by row number, or construct a
multi-hour return across a gap. A baseline may pool *separately valid*
historical targets/pairs across segments. Null feature rows cannot train or
forecast Ridge but may remain valid for baseline-only comparison. A
numerically valid anomaly-flagged row remains in A-primary; A-sensitivity
uses the fixed, retrospectively known candidate mask. The 13:00 audit origin
has no complete next-hour outcome **and is outside every approved split**;
it is not a future evaluation forecast or score record.
Origins before each 720-history threshold remain explicit abstentions.
AR/Ridge only leave cold start at a scheduled midnight refit; if a threshold
is reached midday, wait until the next 00:00. No additional embargo or purge
is specified by `qnt-003d-design-v1`; adding one would require a versioned
protocol amendment. Never use random/shuffled splitting.

## 4. Method contracts — no implementation in PQTA-003B

Every method forecasts raw hourly log return. Each method/sample/period
gets a distinct accounting path. Historical labels enter only under the
`s+2h <= o` cutoff, and each refit logs its maximum admitted outcome close.

| Method | Forecast, history, update, and failure rules |
| --- | --- |
| Zero Return | Emit finite `0.0` at every **in-split** forecast origin; no fit, minimum sample, or cold start. Post-outcome score only if the sample target rule is satisfied. An invalid future target cannot retroactively turn this forecast into abstention. |
| Expanding Mean | Arithmetic mean of sample-eligible prior targets, recalculated every hour; minimum 720 completed targets. A-primary pools every `V_s`; sensitivity pools `V_s AND NOT A_T(s)`. Before 720, abstain `insufficient_training_history`; no zero fallback. |
| AR(1) | `r_u=ln(C_u/C_(u-1h))`; fitted pair `x_s=r_s`, `y_s=r_(s+1h)` requires candles `s-1h,s,s+1h`; current lag `r_t` requires `t-1h,t`. Minimum 720 eligible pairs. Fit intercept and slope by QNT-003B §3 binary64 `math.fsum` OLS at each 00:00 origin. Require `Sxx/n > 1e-16`; otherwise `ar_ill_conditioned_lag`. Non-finite input/fit/prediction gives `ar_numerical_failure`; invalid current lag abstains. A-sensitivity excludes any manifest record on pair candles and either current-lag endpoint. No stale fit or mean fallback after a failed daily refit. |
| Ridge | Exactly seven finite features, no imputation, sample-specific minimum 720 eligible `(X_s,y_s)` rows. At each 00:00 origin, calculate training-only column means and population standard deviations (`ddof=0`); zero-variance scale becomes `1`. Hold that scaler and fit through the day. Minimize `sum_i (y_i - beta_0 - sum_j beta_j z_ij)^2 + alpha sum_j beta_j^2`; **the intercept is unpenalized**. Alpha grid `{0.01, 0.1, 1, 10, 100}`. Numerical failures are explicit `ridge_numerical_failure`, never silently dropped or replaced. |

Ridge alpha is selected **only** on A-primary's frozen eligible 2024
validation set, across `[2024-01-01,2024-05-01)`,
`[2024-05-01,2024-09-01)`, and `[2024-09-01,2025-01-01)` UTC folds.
The candidate origin set is fixed from `V_t`, `F_t`, and the 720-row
scheduled-fit count before comparing alphas; it may not depend on a
candidate's prediction or performance. Follow the same prequential daily
refits for each alpha. Disqualify any alpha with a numerical failure on
that one set; score surviving candidates on its identical full timestamp
set using pooled RMSE; exact ties choose the smallest alpha. If none
survives, Ridge is unavailable. Select alpha before **any** test scoring;
hold it fixed across the entire test and both Lane A samples. Test daily
refits update only scaler and coefficients, separately by sample. Earlier
test outcomes may enter later predeclared fits after theoretical closure,
but never choose alpha or change the protocol.

## 5. Forecast, score, and refit records

The origin ledger carries retrospective source/target audit facts. A future
forecast ledger and score ledger are separate and linked by an immutable
forecast identity. Proposed method IDs are `zero_return`,
`expanding_mean`, `ar_1`, and `ridge_7`; proposed sample IDs are
`a_primary` and `a_sensitivity`. Forecast and score records in a future
authorized evaluation cover **only in-split origins** (training/history,
validation, and test), never an `outside_approved_evaluation_window` audit
origin. A record key is the full
`(dataset_spec_id, origin_ledger_artifact_build_id, protocol_version,
exchange, symbol, timeframe, forecast_origin_utc, sample_id, method_id)`
tuple. This makes one method/sample forecast record per in-split origin,
including abstentions, and binds it to the exact source-ledger build. A canonical
hash of that tuple may serve as `forecast_id`; ordering and serialization
must be versioned. A score record has exactly the same key and references
that `forecast_id`, even when no score can be computed. Neither record is
a historical live prediction: `research_mode=retrospective`, with
`processing_at` kept separate from theoretical event time.

| Record | Required fields and invariants |
| --- | --- |
| Forecast | Identity, method/model version, sample, split, `feature_open_t`, theoretical origin, finite prediction or null, exactly one `forecast_status` (`emitted` or `abstained`), method-specific abstention reason, training cutoff `o`, eligible history count, maximum admitted outcome closure, most recent scheduled refit, fit ID/status, selected Ridge alpha if applicable, source/manifest/protocol/dataset/model provenance, and research processing time. An emitted prediction is finite; an abstention has null prediction. Current target and next-candle anomaly fields are inaccessible to forecast construction. |
| Score | Same identity and `forecast_id`, nullable target copied from outcome audit, target theoretical close, target validity and endpoint-anomaly status, exactly one `score_status` (`scored`, `emitted_but_not_scored`, `not_scored_no_forecast`), nullable signed and absolute/squared errors, one exclusive primary score-exclusion code plus all overlapping codes, common-set membership, and scoring/research processing time. Errors are finite only when scored. Later target failure never changes the forecast record. |
| Refit | `fit_id`, method/sample, UTC scheduled event, selected alpha if Ridge, eligible row count, maximum admitted outcome closure, scaler means/scales and fitted coefficients where applicable, solver/library/dependency versions, numerical status, and content digest. Failed fits remain audit records; no stale coefficients are reused. |

For every **approved split period**, sample, and method, enforce the QNT-003B §6
exclusive score-exclusion priority and method-specific forecast-abstention
priority without inventing a replacement order. Retain *all* overlapping
reasons. Reconcile:

```text
N_origins = N_emitted + N_abstained
N_emitted = N_scored + N_emitted_but_not_scored
N_not_scored_no_forecast = N_abstained
N_origins = N_scored + sum(N_primary_exclusion_code)
```

The last sum counts one exclusive non-`scored` code per origin. A finite
forecast with an invalid or sensitivity-excluded target is
`emitted_but_not_scored`, **not** an abstention. Direct comparisons use
only identical intersections of **scored-forecast** origins: baseline-only
(Zero Return, Mean, AR), feature-aware (those three plus Ridge), and, if
reported, the paired cross-sample sensitivity intersection. Publish each
set's cardinality, first/last origin, and SHA-256 of sorted unique UTC
origins serialized exactly as `YYYY-MM-DDTHH:MM:SSZ\n` in UTF-8. Every
metric denominator must equal its set cardinality. Coverage reports show
all origins, method-specific emissions, abstentions, emitted-but-not-scored
rows, scored rows, overlapping reasons, and the exclusive funnel; no
method disappears merely because it cannot forecast at an in-split origin.
Report out-of-split audit rows separately; do not include them in
`N_origins`, forecast/score ledgers, or comparison timestamp sets.

RMSE is primary, MAE secondary, and exact-zero three-class directional
accuracy diagnostic only. Sign is `-1`, `0` only for exact zero, or `+1`.
Report validation selection scores separately from test results; the
selected-alpha validation score is not an unbiased holdout result. No
test-informed method, threshold, mask, preprocessing, or penalty change.

## 6. Dependency comparison and recommendation

The existing `pyproject.toml` declares Polars, DuckDB 1.5.6, CCXT,
Pandera, and pytz, plus pytest/Ruff for development. It declares neither
NumPy nor scikit-learn; neither is installed in the inspected `pqta`
environment. Python's `math.fsum` must still implement the protocol's
specified AR OLS sums, whichever Ridge option is later chosen.

| Option | Contract fit | Trade-off |
| --- | --- | --- |
| NumPy only | A seven-column implementation can explicitly scale with `ddof=0` and solve an augmented Ridge least-squares system with an unpenalized intercept. | Smaller dependency footprint, but custom preprocessing, solver, failure handling, and equivalence tests become project-owned; normal-equation inversion is not an acceptable shortcut without conditioning evidence. |
| NumPy + scikit-learn | `StandardScaler` documents population (`ddof=0`) standard deviation; `Ridge` documents the summed squared-error plus `alpha` times slope L2 objective with a fitted intercept. An explicit dense `svd` solver is a candidate rather than environment-dependent `auto`. | Mature estimator reduces bespoke numerical code but adds scikit-learn and its dependencies, requires pinned compatible macOS arm64/Python 3.12 versions, and still requires exact contract/equivalence tests. |

**Recommendation for a later dependency approval:** NumPy + scikit-learn,
isolated to an optional research dependency group, with explicitly pinned
versions and a fixed dense solver after verification. This is a design
recommendation, **not** authorization to install or edit dependencies.
Before adopting it, test hand-solved and synthetic nonconstant/constant,
collinear, tiny-return, and zero-variance cases; compare coefficients,
intercept, scaled predictions, objective value, finite-failure behavior,
and unchanged alpha semantics with an independent augmented least-squares
reference. Test that a trailing future row or future label cannot change a
past scaler, fit, or prediction; assert identical candidate timestamp sets
and explicit disqualification on any alpha-specific numerical failure.
Pin package/BLAS versions, platform, solver settings, code revision, and
numeric tolerances; rerun equivalence on the target arm64 environment.
Do not silently change the Ridge objective to a mean loss or penalize the
intercept. The official [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)
and [StandardScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html)
documentation support the intended semantics; the proposed NumPy reference
would use documented [least squares](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html)
behavior. Installed version compatibility was not tested in this task.

## 7. Local-only storage and reproducibility design

Use **three separate identities**, never one overloaded snapshot hash:

| Identity | Exact meaning and canonical inputs |
| --- | --- |
| `dataset_spec_id` | SHA-256 of the logical dataset specification: `dataset_contract_version`, `protocol_version=qnt-003d-design-v1`, exact Silver Parquet SHA-256, exact Gold Parquet SHA-256, candidate manifest **canonical** SHA-256, fixed `analysis_as_of`, Gold `source_feature_version`, and manifest `manifest_version`. These are the relevant currently named source/manifest contract versions; a new version field requires a revised dataset contract. This ID is independent of code, dependencies, serializer, and processing time. |
| `artifact_build_id` | SHA-256 of a deterministic build specification containing `dataset_spec_id`, code revision, exact dependency-version map, serializer/canonicalization version, and deterministic build configuration (including schema/column order, row order, float encoding, Parquet compression and row-group settings, and any fixed processing timestamp embedded in bytes). A changed implementation or serialization gets a new build ID without redefining the logical dataset. |
| `artifact_sha256` | SHA-256 of each **actual published file's bytes**. It is computed only after serialization and is validated again on read; it is neither the logical specification ID nor the build ID. |

For both ID payloads, the future implementation must define and test
canonical UTF-8 JSON with lexicographically sorted object keys, compact
separators, a final newline, fixed-order arrays, lowercase SHA-256 hex,
and UTC timestamps encoded as `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Sort dependency
names and normalize version strings. For Parquet artifacts, pin schema field
order and dtypes, sort rows by their declared keys, reject duplicate keys
and NaN/infinity, and pin serializer/library version and writer options.
Do not hash an arbitrary in-memory mapping or platform-dependent timestamp
string. Verify every input digest before a build, then verify each published
file's `artifact_sha256` before use. These are future requirements, not
hashes or artifacts created in PQTA-003B.

Proposed future root:
`data/research/pqta-003/<dataset_spec_id>/<artifact_build_id>/`, ignored by
Git under `/data/**`. The same logical specification may have multiple
reviewable builds, but an immutable build ID may never map to conflicting
bytes.

| Proposed path under that root | Contents |
| --- | --- |
| `origin_ledger.parquet` | Full research-only audit timeline, including any out-of-split origin and null target. |
| `forecast_ledger.parquet` | One method/sample forecast or abstention record per **in-split** origin only. |
| `score_ledger.parquet` | One linked score-status record per method/sample/**in-split** origin only. |
| `refits.parquet` | Daily fit status and numerical/scaler/parameter provenance, not a trading model service. |
| `metrics.json` | Period/sample/method metrics, common timestamp-set counts/digests, coverage, and abstentions. |
| `provenance.json` | `dataset_spec_id`, `artifact_build_id`, input identities, per-file `artifact_sha256`, fixed UTC build time if embedded, serializer settings, and validation results. Variable run timing belongs in a separate receipt. This file does not recursively contain its own hash. |
| `provenance.sha256` | Sidecar SHA-256 of the exact published `provenance.json` bytes. |

A later writer should stage files on the same local filesystem, validate
keys/schemas/reconciliation, hash exact bytes, then publish atomically.
Never modify Silver, Gold, or the manifest. An identical pinned rerun may
confirm and reuse existing files only when every expected byte hash matches.
**Reject conflicting bytes under the same immutable `artifact_build_id`**;
do not overwrite or silently choose one result. If processing time is
embedded in artifact bytes, inject the build's fixed timestamp or place
variable run timing in a separate receipt, so an otherwise identical build
cannot acquire different bytes without a changed build identity. Do not
upload datasets, forecast rows, or fitted parameters to GitHub.

## 8. Proposed modules and synthetic verification

These are **future paths**, not files created in PQTA-003B. Keep offline
research separate from `src/quant/app/` and reuse the existing Gold values
and QNT-002B feature contract without recalculating or changing formulas.

| Future file | Single responsibility |
| --- | --- |
| `src/quant/research/forecast_dataset.py` | Read-only pin/audit of Silver, Gold, and manifest; exact UTC open-key join; target and origin-ledger construction. |
| `src/quant/research/evaluation_protocol.py` | Fixed split and lane masks, historical label cutoff, event order, reason priority, common-set membership. |
| `src/quant/research/statistical_baselines.py` | Zero Return, hourly Mean, and protocol-specific AR OLS with explicit abstentions. |
| `src/quant/research/ridge_comparator.py` | Seven-feature scaler/Ridge, daily refits, fixed 2024 alpha selection, numerical-failure contract. |
| `src/quant/research/forecast_accounting.py` | Linked forecast/score/refit records and conservation assertions. |
| `src/quant/research/evaluation_reporting.py` | Metrics, paired timestamp-set digests, immutable artifact/provenance publication. |
| `tests/test_forecast_dataset.py` | Synthetic target/gap/anomaly/UTC joins, null reasons, Gold-field preservation, deterministic ledger identity. |
| `tests/test_evaluation_protocol.py` | Synthetic split edges, same-clock closure, 720 cold starts, lane masks, origin/status reconciliation. |
| `tests/test_statistical_baselines.py`, `tests/test_ridge_comparator.py` | Hand-calculated fits, numerical failures, no future leakage, frozen-alpha and solver-equivalence cases. |

Future implementation must test that an added future candle or label leaves
earlier forecast-side records unchanged for pinned sources; anomalies at
`t+1h` may change only outcome audit/score, never earlier emitted forecasts.
It must test gaps at the exact missing opens, 24/168-hour warm-up,
duplicate/invalid source rejection, final unscorable origin, all exclusion
priorities and count identities, plus deterministic canonical digests.
These are test specifications, not tests executed here.

## 9. Open approvals and non-goals

Before implementation, the Project Owner and Architect must review this
proposed ledger contract/version, artifact layout, canonical identity
format, method-record schema, and dependency/solver choice. Separate owner
authorization is still required to construct targets or datasets, fit any
baseline/Ridge path, and score Lane A. Changing any governing numerical
convention, sample rule, date boundary, or exclusion priority requires a
versioned `qnt-003d-design-v1` amendment first. Lane B additionally needs
auditable historical as-of source revisions, publication/observation, and
manifest availability; the current Gold rows provide none. Trading
backtesting and application inference remain blocked. No profitability,
predictability, or live-trading claim follows from this design.
