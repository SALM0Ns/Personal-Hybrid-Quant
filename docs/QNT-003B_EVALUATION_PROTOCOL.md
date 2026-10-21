# QNT-003B — Statistical Baseline and Evaluation Protocol

**Status:** QNT-003D audit-resolution draft for owner review; documentation
only. The two-lane and model conventions below are proposed design choices,
not approval to execute them.
Nothing in this document authorizes target generation, fitting, scoring,
backtesting, trading signals, or use of the Gold snapshot for decisions.
The QNT-003A research question and target are unchanged.

## 1. Scope and study boundary

The proposed study asks whether the seven existing QNT-002B historical
features improve prediction of the next BTC/USDT 1-hour log return over
simple statistical baselines under chronological evaluation. It is limited
to Binance Spot BTC/USDT 1-hour OHLCV, the existing Silver source, and the
local research-only QNT-002B Gold snapshot. No other instruments, venues,
timeframes, indicators, or feature families are proposed. The existing
Silver/Gold bytes, anomaly manifest, formulas, and eligibility fields are
not changed by this design.

The pinned Gold timeline covers `[2021-01-01 00:00, 2026-10-20 13:00)` UTC
and contains 14 explicit missing-hour rows. Its seven features are defined
in `docs/QNT-002B_FEATURE_CONTRACT.md`; its real-data audit is
`docs/QNT-002B_REAL_DATA_AUDIT.md`. No predictive result is reported here.
The fixed feature order throughout this protocol is `log_return_1h`,
`volatility_24h`, `volatility_168h`, `momentum_24h`, `momentum_168h`,
`volume_change_1h`, `normalized_range_1h`.

## 2. Target, event order, and forecast origin

For an hour-aligned UTC candle-open time `t`, let `C_t` be the validated
Silver close for `[t,t+1h)`. The QNT-003A target on feature row `t` is:

```text
y_t = target_next_1h_log_return(t) = ln(C_(t+1h) / C_t)
```

It requires **both** consecutive, valid, fully closed candles at `t` and
`t+1h`. It is null when either is absent, incomplete, or has an invalid
close; a multi-hour change is never substituted. Its theoretical outcome
closure is `t+2h`. A feature row at `t` uses candles opening no later than
`t`; neither `C_(t+1h)` nor any later outcome/quality value enters its
predictors.

The *mathematical research forecast origin* for row `t` is the event just
after candle `t` is complete at the nominal UTC boundary `o_t=t+1h`.
Event ordering at a shared timestamp is: complete/validate candle `t`,
admit any already-completed historical labels, perform a scheduled refit
if applicable, then produce the forecast for `y_t`. In this mathematical
ordering, the immediately preceding target `y_(t-1h)` closes at `o_t` and
may enter history; `y_t` closes only at `o_t+1h` and cannot. This convention
does **not** assert that Binance actually published candle `t` at `o_t`.
Publication/observation and quality-manifest availability remain unknown,
so `o_t` is not an evidenced historical trading decision time.

For any earlier target `y_s`, the mathematical training cutoff is
`s+2h <= o_t`, with the closing event ordered before the forecast event
when equal. A target with `s+2h > o_t` is unavailable even in this
theoretical sequence. No current target, future close, or future score may
enter a forecast or its fitted parameters. Retrospective target-quality
annotations can be used only as a separately approved audit/filter, never
as predictors or as proof they were known at `o_t`. Because the current
manifest was assembled later, even an ex-post anomaly-filtered training
history is **not** a point-in-time-reproducible training history.

## 3. Three prespecified statistical baselines

All predictions are on the raw hourly log-return scale. No transformation,
annualization, market-cost assumption, or fitted feature is implicit.

### A. Zero Return

`y_hat_t = 0` at every otherwise eligible forecast origin. There are no
parameters, training observations, refits, or cold-start period. For fair
comparison, score it only on the same evaluation timestamps as the other
included methods; also report how many mathematically target-valid rows it
could have covered on its own.

### B. Expanding Historical Mean

At origin `o_t`, predict the unweighted arithmetic mean of eligible
historical targets `y_s` with `s+2h <= o_t`, subject to the lane-specific
training policy in §6. Do not average price levels or feature values.
The primary valid-target sample admits every finite target with two
consecutive valid source candles, **including** numerically valid targets
with retrospective anomaly flags. The fixed-manifest sensitivity sample
excludes from its mean history targets with a documented anomaly at either
endpoint. A gap makes affected targets null; history may resume after the
gap without filling it. The mean may pool separately valid targets across
distinct contiguous segments; no multi-hour return is created across a gap.

Require at least **720 eligible historical targets** (approximately 30
days of hourly outcomes) before forecasting. Until then, abstain and record
`insufficient_training_history`; do not silently substitute zero or a
shorter mean. This threshold is a prespecified design choice, not a
data-optimized result. Recompute the expanding mean at every eligible
hourly forecast origin using only targets admitted by that origin.

### C. AR(1) on consecutive hourly log returns

Define `r_u = ln(C_u/C_(u-1h))` only for consecutive valid candles. For a
training row indexed by `s`, set `x_s=r_s` and `y_s=r_(s+1h)`. Fit

```text
y_s = alpha + beta * x_s + epsilon_s
y_hat_t = alpha_hat + beta_hat * r_t
```

by ordinary least squares with an **unpenalized intercept**. The forecast
lag `r_t` uses only closes at `t-1h` and `t`, mathematically complete by
origin `o_t`. Each fitted pair requires the three candle opens
`s-1h, s, s+1h` to be consecutive and valid. The primary valid-target
sample retains numerically valid pairs even when the retrospective
manifest flags an endpoint. The fixed-manifest sensitivity sample excludes
a pair if **any** of those three opens has a documented anomaly; the
forecast lag is likewise excluded if either of its two opens is flagged.
A gap between pairs may remain in the historical training pool, but no
pair bridges a gap and no rows are made adjacent by dropping missing hours.

Require at least **720 eligible `(x_s,y_s)` pairs**. For deterministic
binary64 OLS, sort pairs by `s`, compute `x_bar=fsum(x)/n`,
`y_bar=fsum(y)/n`, `Sxx=fsum((x-x_bar)^2)`, and
`Sxy=fsum((x-x_bar)*(y-y_bar))`, using Python `math.fsum` semantics.
Reject any non-finite input or intermediate first with
`ar_numerical_failure`. Define `v_x=Sxx/n`, the population variance of
the lag sample. Fit only if `v_x > 1e-16`; otherwise record
`ar_ill_conditioned_lag` and abstain. When permitted, set
`beta_hat=Sxy/Sxx` and `alpha_hat=y_bar-beta_hat*x_bar`. Non-finite inputs,
intermediates, coefficients, or predictions cause an explicit
`ar_numerical_failure` abstention, never a zero/mean fallback or estimator
substitution. This fixed scale-specific threshold is a design convention,
not a data-derived optimum.

If the current `r_t` is missing or non-finite, abstain; in the sensitivity
sample also abstain when its two source candles are manifest-flagged.
Refit on an expanding pool at the **00:00 UTC** forecast event each day,
after admitting only pairs whose outcome closure precedes that event in
the §2 event order. Keep those coefficients for subsequent hourly origins
until the next scheduled refit. At the first validation/test origin, refit
from the then-admitted pool; there is no fit on the current or future
target. If 720 pairs first become available after 00:00, the model stays
in cold start until the next day's refit. A failed scheduled fit causes
abstention until the next scheduled fit; do not carry stale coefficients.
Missing forecast lag after a gap produces no AR forecast until a new
consecutive return exists.

The 720-target/pair thresholds and daily AR refit cadence are proposed
protocol parameters for owner approval; they were not selected by looking
at outcome performance.

## 4. Calendar splits and walk-forward order

Assign rows by **forecast origin** `o_t` to half-open, timezone-aware UTC
intervals, independent of return distribution or observed performance:

| Role | Forecast-origin interval `[start,end)` UTC | Use |
| --- | --- | --- |
| Initial training/history | `[2021-01-01 01:00, 2024-01-01 00:00)` | Accumulate eligible past outcomes and initial fits; no held-out result claim. |
| Validation | `[2024-01-01 00:00, 2025-01-01 00:00)` | Proposed chronological protocol selection only; score only after separate authorization. |
| Test | `[2025-01-01 00:00, 2026-10-20 13:00)` | Sealed final comparison window; only origins with `o_t+1h <= 2026-10-20 13:00` can have a complete target. |

The final bound is the **pinned snapshot's** fixed `analysis_as_of`, not a
moving “latest hour.” The last potentially scorable test origin is
2026-10-20 12:00 UTC, for an outcome theoretically closing at 13:00 UTC.
These dates are calendar rules chosen in advance, not optimized from
returns, regimes, gaps, or candidate performance. A later source snapshot
would need its own versioned protocol and review; do not silently extend
the test interval.

For each validation/test origin in order: form current predictors using
data through candle `t`; admit only mathematically completed historical
targets (`s+2h <= o_t`); update the expanding mean; refit AR and Ridge
only at their scheduled UTC daily origin; emit each available forecast;
**then**, after the next candle closes, assign and audit `y_t` for scoring
and possible inclusion in subsequent origins. Earlier validation or test
outcomes may enter later expanding/daily refits under this predeclared
online rule, but no later outcome may affect an earlier prediction.
Validation may select the Ridge penalty through the frozen §7 rule. Test
**metrics and protocol choices** remain sealed: no refit cadence,
threshold, preprocessing, mask, penalty, or hyperparameter may change in
response to test results. Every refit must log its UTC event, training-row
count, and maximum admitted outcome-closure time (at most that event).
Every prediction must log its forecast origin, most recent refit, and
source/feature/manifest/protocol identities if execution is separately
authorized. This is theoretical event ordering, not historical
publication evidence.

No random split, shuffled cross-validation, or full-sample preprocessing is
permitted: they would mix later market states and adjacent/overlapping
returns into earlier training and can leak information across time.
The 2024 validation period can select the prespecified Ridge penalty under
§7; its selected-penalty score is a **selection** score, not an unbiased
holdout estimate. The test period is untouched for **selection** until all
choices are frozen, though earlier test labels may be admitted to later
predeclared online refits. Each fold's fitting and scaling uses only its
past. Do not select dates, filters, thresholds, or hyperparameters using
test outcomes. Report calendar-period coverage and any empty/insufficient
period rather than moving boundaries afterward.

## 5. Metrics and reporting conventions

For a prespecified common set `E` of eligible, scored timestamps, with
`n=|E| > 0`, define errors `e_t=y_hat_t-y_t`:

```text
RMSE = sqrt((1/n) * sum_(t in E) e_t^2)       # primary
MAE  =       (1/n) * sum_(t in E) |e_t|       # secondary
Directional accuracy = (1/n) * sum_(t in E)
    1[sign(y_hat_t) = sign(y_t)]              # diagnostic only
```

`sign(z)` is `-1` for `z<0`, `0` for **exactly** `z=0`, and `+1` for `z>0`;
no tolerance band or rounding defines neutral. Exact-zero actual returns
remain in the denominator. An exact-zero prediction is correct only against
an exact-zero actual return; it is incorrect against either nonzero sign.
Neutral predictions and neutral outcomes are never omitted merely because
they are neutral. Non-finite or missing predictions/targets are not scored
and have an explicit exclusion/abstention reason. The zero-return baseline
will generally have limited directional-accuracy usefulness; RMSE is the
primary comparison, and this diagnostic must not be used to claim a trading
edge. Report `n` and the exact common timestamp set for each metric,
period, and method comparison. No metric value is computed in this stage.

## 6. Two research lanes, sample eligibility, and accounting

Keep **feature quality**, **target quality**, **forecast availability**, and
**historical decision availability** as separate dimensions. Every
retrospective observation and quality flag remains in the audit ledger;
sample membership never changes source values or Gold eligibility fields.

### Lane A — retrospective statistical study, not yet authorized to run

Define `V_t` as a finite target from two consecutive, validated, fully
closed candles with finite positive closes. The last row lacking a next
candle and every gap-spanning target have `V_t=false`; do not zero-fill.
Define `F_t` as all seven existing QNT-002B features non-null and finite.
Let `A_T(t)` mean **any** pinned-manifest record at either target endpoint
`t` or `t+1h`; `A_F(t)` mean any manifest record involved in **any** of the
seven feature dependency windows at row `t`; and `A_R(t)` mean a record at
either endpoint `t-1h` or `t` of AR's current lag. Missing-hour records
already make the corresponding numeric value invalid. Disputed `volume`
alone is provenance rather than numeric sensitivity for a close-only
target, but the sensitivity mask conservatively treats every documented
endpoint anomaly alike. Preserve the actual affected-field metadata.

Two **separately fitted and separately reported** Lane A samples are fixed:

| Sample | Historical training and forecast-side rule | Outcome-side scoring rule |
| --- | --- | --- |
| **A-primary: valid-target** | Mean uses all prior `V_s`; AR uses every numerically valid consecutive `(r_s,y_s)` pair and valid current lag; Ridge uses prior rows with `V_s AND F_s` and current `F_t`. A retrospective anomaly flag alone excludes none of these valid numeric inputs. | Score only `V_t` and an emitted finite forecast; Ridge also requires `F_t`. Keep anomaly flags, including shortened-close and disputed-close provenance, visible. |
| **A-sensitivity: fixed-manifest filtered** | Mean uses prior `V_s AND NOT A_T(s)`; AR pairs require valid numeric lag/target and no manifest record on `s-1h,s,s+1h`, with current `NOT A_R(t)`; Ridge uses prior `V_s AND F_s AND NOT A_T(s) AND NOT A_F(s)` and current `F_t AND NOT A_F(t)`. | Score only `V_t AND NOT A_T(t)` and an emitted finite forecast; Ridge also requires `F_t AND NOT A_F(t)`. Target-side filtering occurs only after the outcome; it is never a predictor. |

Zero Return has no training history and emits `0` at every forecast event;
its score is subject to the selected sample's outcome rule. Mean requires
720 sample-eligible past targets; AR requires 720 sample-eligible valid
pairs; Ridge requires 720 sample-eligible feature/target rows. All use the
same pinned Silver/Gold/manifest identities within a sample. The
**A-primary** sample does not silently drop numerically valid anomalous
observations. The **A-sensitivity** sample uses the **same fixed 19-record
candidate manifest** for both training and scoring, including four
shortened closes, one source discrepancy, and 14 missing hours; no revised
mask may be selected after seeing metrics. Because the manifest was
assembled retrospectively and `version_available_at=null`, even the
filtered *training membership* uses ex-post knowledge. Both samples are
retrospective mathematical constructs, not historical as-of forecasts.
Neither establishes a publication time, a tradable signal, or a backtest.

For each sample, the baseline-only common set is the target-eligible
intersection of finite predictions from Zero Return, Mean, and AR. The
feature-aware common set further requires `F_t`, the sample's feature-side
rule, and a finite Ridge prediction. **Recompute every method's metrics on
that identical set** for a feature-versus-baseline comparison. Report
baseline-only and feature-aware sets separately; do not compare their
unpaired metrics as if they used the same timestamps. Report A-primary and
A-sensitivity counts and metrics separately. If claiming a *paired*
sensitivity difference, additionally restrict both samples to the
intersection of their common timestamp sets and label it as such; do not
equate differing-sample metric changes with a causal anomaly effect.
No metric is computed or evaluation authorized by this document.

### Lane B — verified point-in-time study: blocked

Lane B would require evidence identifying the exact source revision and
its actual publication or local observation by each proposed decision
time; as-of source/feature snapshots; an as-of, versioned quality manifest
with auditable availability; verified feature `available_at`; and an
explicit decision-time eligibility check. A theoretical `t+1h` close,
retrospective archive retrieval, or present-day Silver `ingested_at`
cannot stand in for those facts. The current Gold snapshot has
`available_at=null` and `decision_eligible=false` on **all 50,845 rows**;
the Lane B candidate universe is empty and **BLOCKED**. These fields must
not be overwritten or reinterpreted. Lane A is not a workaround for Lane B.
Historical trading backtesting remains prohibited.

### Row-level audit contract and total exclusion order

A future authorized implementation must create **one audit row for every
hourly forecast origin** in each §4 calendar split, including origins where
no method forecasts or no target can be scored. Key it uniquely by
`(exchange, symbol, timeframe, forecast_origin_utc)`; derive
`feature_open_t=forecast_origin_utc-1h` and
`target_theoretical_close_at=forecast_origin_utc+1h`. Store the two Lane A
samples as nested, separately keyed records **within** that one origin row,
not as duplicate origin rows. Each row must carry:

- Pinned Silver/Gold SHA-256, feature/manifest versions and digests,
  `analysis_as_of`, a protocol version, both fixed sample names, and copied
  read-only Gold `available_at` and `decision_eligible` values.
- Current/next candle presence, completeness, validation and close checks;
  `V_t`, the nullable target and all target-invalid reasons; `A_T(t)` with
  record timestamps, types, affected fields and value-sensitivity.
- All seven feature values' validity/null reasons in contract order,
  `F_t`, their anomaly-involvement and field-sensitivity metadata, and
  `A_F(t)`; current AR lag validity and `A_R(t)` separately.
- For **each method and sample**: training-eligibility rule, actual eligible
  history count, forecast cutoff `o_t`, most recent refit event, maximum
  admitted historical outcome-closure time, fit status, **forecast status**
  (`emitted` with a finite prediction, or `abstained` with its method-specific
  reason), and distinct **score status** (`scored`,
  `emitted_but_not_scored`, or `not_scored_no_forecast`). Record
  sample/comparison-set membership, a primary exclusive score-exclusion
  reason, and **all** overlapping reasons in deterministic order. Every
  origin has exactly one forecast status and one score status per
  method/sample. A next-candle anomaly may enter target audit metadata
  only after target observation, never a forecast-time feature or method
  status.

The **total priority order** for each method/sample's exclusive
*score-exclusion* reason is below; skip codes not applicable to that
method/sample. Keep every applicable reason independently in the full
reason list, even when a higher-priority reason wins. For the seven
feature-specific codes, break ties by their exact §1 feature order.

1. `current_missing`, then `next_missing`, then
   `current_incomplete`, then `next_incomplete`, then
   `nonconsecutive_opens`.
2. `current_invalid_source`, then `next_invalid_source`, then
   `current_invalid_close`, then `next_invalid_close`, then
   `target_nonfinite`.
3. `target_manifest_anomaly` (**A-sensitivity only**).
4. `feature_null__<feature>` in the fixed seven-feature order (**Ridge
   only**), then `feature_manifest_anomaly__<feature>` in that order
   (**A-sensitivity Ridge only**).
5. `ar_lag_missing_or_invalid`, then `ar_lag_manifest_anomaly`
   (**A-sensitivity AR only**).
6. `insufficient_training_history`, then `ar_ill_conditioned_lag`, then
   `ar_numerical_failure`, then `ridge_numerical_failure`, then
   `nonfinite_prediction` (applicable method only).
7. `scored` if no exclusion applies and target/prediction are finite.

This is an accounting order **after** the outcome is known, not a rule
allowing target-side information at forecast time. Within each method,
forecast-time abstention has its own fixed priority: Zero Return has none;
Mean uses `insufficient_training_history`, then `nonfinite_prediction`;
AR uses invalid/missing lag, sensitivity-only lag anomaly, insufficient
history, ill-conditioned fit, numerical fit failure, then non-finite
prediction; Ridge uses first null feature, sensitivity-only first
anomaly-involved feature, insufficient history, numerical fit failure,
then non-finite prediction. A failed daily fit causes the same fit reason
to be logged for later hourly abstentions until the next scheduled refit;
no stale fit or substitute model is allowed. The full reason list also
retains unknown historical availability on every affected row, but it
does not erase a valid Lane A research target. No reason may silently
remove a row from the audit ledger.

Forecast emission is fixed at `o_t` from information allowed by the
sample's forecast-side rule. A later target-invalid or target-anomaly
score exclusion **cannot retroactively turn an emitted finite forecast
into an abstention**. In particular, `emitted_but_not_scored` retains its
finite prediction and its post-outcome exclusion reason; an abstention
has `not_scored_no_forecast` even if a valid target is later observed.
The exclusive score-exclusion priority above describes scoring only and
does not override the separate forecast-status/abstention priority.

For each calendar split, sample, and method, require the reconciliation
invariants `N_origins = N_emitted + N_abstained`,
`N_emitted = N_scored + N_emitted_but_not_scored`, and
`N_origins = N_scored + sum(N_primary_exclusion_code)` over all
non-`scored` codes, with exactly one exclusive primary code per origin.
`N_emitted` counts every finite forecast produced at its origin,
**regardless** of whether its target is later scorable; `N_scored`
counts emitted forecasts with an eligible observed target. The count of
`not_scored_no_forecast` must equal `N_abstained`, and the count of
`emitted_but_not_scored` must equal the corresponding term above.
Publish multi-label reason counts separately; they need not sum to
`N_origins`. For every baseline-only, feature-aware, and paired
sensitivity comparison, assert the common UTC timestamp set is exactly
the intersection of the participating methods' **scored-forecast** sets
under that sample and that every metric denominator equals its
cardinality. Sort unique origins ascending, serialize each as
`YYYY-MM-DDTHH:MM:SSZ\n`
in UTF-8 (empty set = empty bytes), and publish SHA-256 of those bytes,
the row count, first/last origin, and the pinned protocol/source/manifest
identities. Do not generate this ledger or its metrics in QNT-003D.

## 7. Fixed Ridge feature-aware comparator — design only

The single proposed comparator is **Ridge regression with an intercept**
on exactly the seven existing QNT-002B features in §1 order. The
intercept is unpenalized; no indicator, regime label, missing-value
imputation, or additional feature is permitted. A row with any null or
non-finite feature abstains at forecast time and is omitted from Ridge
training; the QNT-002B numeric values and null reasons remain unchanged.
Lane A-primary retains numerically valid anomaly-flagged feature/target
rows; Lane A-sensitivity uses §6's fixed-manifest rule. Lane B cannot fit
or score using the current Gold snapshot.

At each daily **00:00 UTC** forecast event (after that boundary's candle
completion in §2's mathematical order), fit an expanding-window Ridge on
sample-eligible pairs `(X_s,y_s)` with `s+2h <= o_t`; require at least
**720** such rows. If this count first reaches 720 later in a day, remain
in cold start until the next 00:00 refit. Hold the fitted scaler and
coefficients through the following hourly origins. A failed scheduled fit
causes explicit abstention until the next refit, never a stale fit or
fallback. At validation/test boundaries, perform the scheduled 00:00
refit using only outcomes admitted by that origin.

For each fit, use the StandardScaler convention: calculate each training
column's mean `mu_j` and population standard deviation (`ddof=0`)
`sigma_j` on **that fit's eligible historical rows only**. Transform
`z_ij=(x_ij-mu_j)/sigma_j`;
if `sigma_j=0`, set its scale to `1` so its standardized training column
is zero. Apply the same fitted `mu_j` and scale to subsequent forecast
rows; never use validation/test-future or full-sample statistics.
With `alpha > 0`, minimize the fixed sum-of-squares objective

```text
sum_i (y_i - beta_0 - sum_(j=1..7) beta_j*z_ij)^2
    + alpha * sum_(j=1..7) beta_j^2
```

in Float64, with an unpenalized intercept. The **only** candidate alpha
grid is `{0.01, 0.1, 1, 10, 100}`; the objective is a *sum*, not a
sample-size-normalized mean. A fit fails closed with
`ridge_numerical_failure` if any eligible input, scaled value, matrix
operation, coefficient, or prediction is non-finite, or if the solver
cannot produce a finite solution to this objective. No estimator,
penalty, scaler, or imputation fallback is permitted. A library used in a
future authorized implementation must match these semantics; none is
added or imported here.

Select **one alpha** using only the A-primary 2024 validation path,
partitioned into these fixed chronological inner folds:

| Fold | Scored forecast origins `[start,end)` UTC | Training at each scheduled refit |
| --- | --- | --- |
| 1 | `[2024-01-01 00:00, 2024-05-01 00:00)` | All A-primary eligible outcomes theoretically complete by that refit, starting with the fixed pre-2024 training history. |
| 2 | `[2024-05-01 00:00, 2024-09-01 00:00)` | Same expanding rule, now allowing completed earlier 2024 outcomes. |
| 3 | `[2024-09-01 00:00, 2025-01-01 00:00)` | Same expanding rule, never admitting an outcome beyond each refit cutoff. |

Fix the validation candidate set **before** comparing alphas: it contains
exactly the 2024 fold origins with an A-primary valid target `V_t`, all
seven finite features `F_t`, and at least 720 A-primary eligible training
rows at the origin's most recent scheduled daily fit. These are the
frozen validation eligibility rules; the set may not depend on alpha,
candidate predictions, numerical outcomes, test-period data, or observed
performance. For each alpha, follow the identical daily-refit/prequential
schedule across all three folds. Log every numerical fit or prediction
failure and its timestamp. A candidate failing at **any** origin in the
fixed validation set is disqualified; never improve its score by dropping
that origin only for that alpha. Score every surviving candidate on the
**one identical, fixed validation timestamp set** and minimize pooled
2024 RMSE; exact ties choose the **smallest** alpha. If that set is empty
or all candidates fail, Ridge is unavailable and no comparator claim is
allowed.

Select alpha **exclusively** from this fixed 2024 validation exercise and
finish selection **before any test scoring**. The selected alpha remains
fixed for the **entire** test period and for both Lane A samples. Daily
Ridge refits during test update only the training-window scaler and model
coefficients, **not alpha**. The chosen 2024 score is a tuning/selection
score, not an unbiased holdout estimate. Refit each sample's scaler and
coefficient path separately under its fixed training mask; do not retune
on the sensitivity sample or on test outcomes. Test labels observed
earlier may enter later predeclared daily refits, never penalty selection
or past forecasts.
This complete design remains unexecuted pending separate authorization.

## 8. Five distinct leakage and feasibility questions

1. **Mathematical target alignment:** features at `t` depend on candles
   through `t`; `y_t` depends on the following candle. The future close
   never appears in a feature or lag at `o_t`.
2. **Chronological training isolation:** fitted parameters and any
   preprocessing use only earlier, mathematically completed outcomes;
   test performance does not choose rules or hyperparameters. A calendar
   split alone is insufficient without per-origin cutoffs.
3. **Historical point-in-time source availability:** the selected Silver
   revision was observed locally during retrospective ingestion, not
   proved published by historical `o_t`. Its as-of history is not
   reconstructed. Mathematical closure is not publication evidence.
4. **Quality-manifest availability:** the 19-record candidate was verified
   retrospectively, has unresolved provenance limitations, and has
   `version_available_at=null`. Its past availability cannot be inferred
   from archive checksums or the current `generated_at`.
5. **Trading execution feasibility:** even a leakage-controlled
   statistical comparison would say nothing about tradable prices,
   latency, fees, slippage, order execution, or profitability. Trading
   backtesting and live/manual trade decisions are not authorized here.

`available_at=null` and `decision_eligible=false` remain unchanged in the
existing Gold snapshot. Research-only retrospective evaluation itself
requires a separate owner authorization; historical trading backtesting is
not authorized. Never substitute `t+1h`, `o_t`, or a hypothetical candle
close for verified exchange publication or manifest availability.

## 9. Remaining approvals and protocol identity

The proposed thresholds, UTC boundaries, Ridge alpha grid/folds,
sample masks, numeric conventions, and audit schema are now fixed **in the
design draft**, not inferred from data. Owner approval of this written
protocol is still required. Changing any of these later requires an
explicitly versioned amendment before examining the affected outcomes;
no post-hoc optimization is allowed. A future implementation must pin an
immutable protocol version (proposed identifier `qnt-003d-design-v1`),
code revision, exact Silver/Gold/manifest bytes and digests, dependency
versions, fixed `analysis_as_of`, and deterministic row/set ordering.
No target, forecast log, or metric artifact is created by this document.

Separate owner authorization would be needed even for **Lane A**
retrospective non-trading statistical evaluation. Lane B remains blocked
until auditable publication/observation, as-of source revision, and
manifest-version evidence exist and the eligibility contract is separately
reviewed. Trading backtesting is not approved. No current design choice
can turn null Gold availability into a historical publication time.

## 10. Acceptance criteria for design review

- The QNT-003A target formula and UTC candle-open alignment are unchanged;
  the mathematical origin/event order and target closure are explicit.
- Zero Return, expanding mean, AR(1), and the single fixed Ridge proposal
  have complete formulas, sample-specific training rules, minima, gap and
  anomaly handling, cold-start behavior, numeric failure handling, and
  refit rules. Ridge scaling and tuning are strictly historical.
- Each fitted value is restricted to completed historical targets at the
  origin; AR lag/pairs never bridge a missing candle.
- Calendar split boundaries are fixed in UTC without examining outcomes;
  one alpha is selected on an identical, frozen 2024 validation timestamp
  set before test scoring and remains fixed throughout test; reported
  candidate failures cannot be hidden by alpha-specific exclusions.
- RMSE, MAE, and diagnostic directional accuracy have exact denominators
  and zero-return conventions; no values or performance claims appear.
- The valid-target and fixed-manifest sensitivity samples remain separate;
  the row-keyed audit schema separates forecast emission from scoring,
  reconciles both per-method counts and exclusion reasons, and publishes
  sorted digests of common scored-forecast timestamp sets.
- Unknown feature/manifest availability and zero Gold decision eligibility
  remain visible. Lane B is blocked; neither Lane A sample is presented
  as a trading backtest or proof of historical execution feasibility.
- No code, target or feature artifact, market data, dependency, model, or
  repository history is changed by this stage.
