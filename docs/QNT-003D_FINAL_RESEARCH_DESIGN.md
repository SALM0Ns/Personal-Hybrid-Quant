# QNT-003D — Final Research Design for Owner Review

**Status:** QNT-003C audit findings resolved in the written QNT-003B
protocol; the concrete numerical/design conventions below remain subject
to owner review. This is documentation only. It does **not** authorize
target generation, statistical evaluation, fitting, backtesting, signals,
trading, data changes, or a point-in-time claim.

## 1. Scope and authoritative documents

The QNT-003A question is unchanged: whether the seven existing historical
BTC/USDT 1h Gold features could improve next-hour log-return prediction
over simple statistical baselines under chronological evaluation. It is a
research question, not a finding. `docs/QNT-003A_RESEARCH_DESIGN.md`
defines the target; the **revised**
`docs/QNT-003B_EVALUATION_PROTOCOL.md` is the normative proposed
evaluation contract; `docs/QNT-003C_LEAKAGE_QUALITY_AUDIT.md` remains
unaltered historical review evidence. This document records the audit
resolutions and remaining approval boundary. No ETH/USDT, SOL/USDT,
other venue, timeframe, indicator, or new source enters the study.

The pinned inputs for any later separately authorized study would be the
existing BTC Silver snapshot (SHA-256
`edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3`),
the QNT-002B Gold snapshot (SHA-256
`18f70e22ce189787e74fad2d8f7d14202625e09f355bf81792f2aac7bcd1a66d`),
and the 19-record candidate manifest (canonical SHA-256
`86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4`).
Pin code, dependency, protocol, and source versions at execution time;
none is created or changed here. The existing `analysis_as_of` is
2026-10-20 13:00 UTC.

## 2. Immutable time and target semantics

For a feature row opening at UTC `t`, the mathematical forecast event is
just after candle `t` theoretically closes at `o_t=t+1h`.
The next-hour target remains exactly

```text
y_t = target_next_1h_log_return(t) = ln(C_(t+1h) / C_t)
```

and cannot theoretically close until `t+2h`. Each feature depends only
on candles opening at or before `t`. A historical training target `y_s`
may enter only when `s+2h <= o_t`, with the earlier close/validation event
ordered before a same-clock refit event. AR lag `r_t` uses only the
consecutive candles opening at `t-1h` and `t`; an AR fitted pair at `s`
uses `s-1h,s,s+1h`, never a row-count adjacency across a gap. These are
mathematical ordering rules, **not** evidence of publication at the
clock boundary. The current source and candidate manifest were assembled
retrospectively.

For example, the first validation origin `2024-01-01 00:00 UTC` belongs
to the feature row opening `2023-12-31 23:00 UTC`. Its target uses closes
at the 23:00 and 00:00 candle opens and cannot theoretically be observed
until `2024-01-01 01:00 UTC`. The scheduled 00:00 AR/Ridge refits can
admit only outcomes theoretically closed by 00:00; they cannot use this
row's target. The same-clock closing event precedes the refit event by
the fixed mathematical event order, without implying actual publication
at 00:00.

## 3. QNT-003C finding-resolution matrix

| Finding | Written resolution in QNT-003B | Closure state and remaining boundary |
| --- | --- | --- |
| **M1 — retrospective anomaly knowledge** | §6 now defines Lane A-primary with all numerically valid targets, including anomaly-flagged ones, and a separate Lane A-sensitivity using one pinned manifest for both historical training and ex-post scoring. It requires separate counts/metrics and explicit disclosure that the sensitivity mask was unavailable historically. Lane B has evidence requirements and remains blocked. | **Design resolved.** Neither Lane A sample is as-of or trading-valid; even retrospective evaluation still needs separate owner authorization. |
| **M2 — underdefined feature comparator** | §7 fixes one Ridge model on exactly seven existing features, its intercept/scaling/objective, alpha grid, three 2024 chronological folds, fixed candidate-eligibility set, selection/tie rule, 720-row minimum, daily UTC refit, null/anomaly policy, and failure/abstention behavior. Alpha selection finishes before test scoring and is never repeated during test. | **Design resolved.** Values are proposed conventions for owner review, not executed or performance-selected. |
| **M3 — non-auditable sample funnel** | §6 specifies one row per origin, target/feature/lag validity and anomalies, lane membership, separate forecast and score statuses, all overlapping reasons, a total primary-reason order, method-specific abstention priority, emission/scoring count reconciliation, and a canonical timestamp-set SHA-256. | **Design resolved.** A future implementation must prove the invariants; none has been run. |
| **N1 — “untouched test” ambiguity** | §4 seals test **metrics and protocol selection** while allowing prior test labels in later predeclared expanding/daily refits. Every refit logs its cutoff and maximum admitted outcome closure. | **Design resolved.** Future test outcomes may never change an earlier forecast or the frozen penalty/rules. |
| **N2 — AR numerical stability** | §3 defines binary64 OLS sums, `v_x=Sxx/n > 1e-16`, finite-value checks, explicit ill-conditioned/numerical abstention, daily fit failure carry-through, and no estimator substitution. | **Design resolved.** The threshold is a reviewable convention, not an empirical result. |

QNT-003C reported **0 CRITICAL, 3 MAJOR, 2 MINOR, and 4 INFORMATIONAL**
findings. This matrix records written resolutions; it does not retroactively
edit or erase the audit.

## 4. Fixed proposed comparison design

| Component | Proposed rule |
| --- | --- |
| Baselines | Zero Return (`0`), 720-target expanding historical mean, and intercept-bearing AR(1) OLS on consecutive returns with 720 eligible pairs. |
| Feature-aware comparator | One intercept-bearing Ridge regression on the seven QNT-002B features; no imputation or other feature family. |
| Ridge scaling and objective | Per-refit training-only StandardScaler convention: means and population standard deviations (`ddof=0`); a zero-variance column gets scale `1`. Minimize **sum** of squared errors plus `alpha` times the squared seven-slope norm; intercept unpenalized. |
| Ridge alpha selection | Fixed grid `{0.01, 0.1, 1, 10, 100}`. A-primary folds `[2024-01-01, 2024-05-01)`, `[2024-05-01, 2024-09-01)`, `[2024-09-01, 2025-01-01)` UTC; one frozen validation-eligible timestamp set, pooled RMSE on that identical set, exact ties to smallest alpha. Report and disqualify candidates with numerical failures on that set; do not selectively drop their failed timestamps. Finish selection before any test scoring. |
| Refit | Mean expands hourly; AR and Ridge refit at the 00:00 UTC forecast event, using only mathematically completed prior outcomes. Failed fits abstain until the next scheduled refit; no stale coefficients. Ridge daily refits update scaler and coefficients, never the validation-selected alpha, which stays fixed for the entire test period and both Lane A samples. |
| Calendar periods | Training-history origins `[2021-01-01 01:00, 2024-01-01 00:00)`, validation `[2024-01-01 00:00, 2025-01-01 00:00)`, test `[2025-01-01 00:00, 2026-10-20 13:00)` UTC. The last target must theoretically close no later than the pinned analysis boundary. |
| Metrics | RMSE primary, MAE secondary, exact-zero three-class directional accuracy diagnostic. Every direct comparison uses one identical timestamp intersection and reports its denominator. No metric is calculated here. |

The validation candidate timestamp set is fixed from the 2024 A-primary
target/feature/720-row eligibility rules, independent of candidate
predictions, numerical results, test data, and performance. The 2024
selected-alpha score is a **tuning** score, not an unbiased holdout
result. Earlier validation or test labels can affect only later
predeclared refits after theoretical completion; test metrics cannot
change the protocol. Each refit's scaler and coefficients use only its
eligible historical rows; alpha remains the frozen validation selection.
No QNT-002A retrospective regime label or full-sample transformation is
permitted.

## 5. Two research lanes and sample accounting

**Lane A-primary (valid-target):** retain every finite next-hour target
from consecutive validated candles in training and scoring, even when
the retrospective manifest flags an endpoint. Mean and AR use numerically
valid prior returns/pairs; Ridge additionally needs all seven non-null
features. All anomalies remain visible as metadata; no source value is
replaced. **Lane A-sensitivity:** use the same pinned candidate manifest
to exclude anomaly-involved target endpoints from both training and
scoring; also exclude anomaly-involved AR lags and Ridge feature windows
from those methods' training/forecast inputs. Its selected Ridge alpha is
inherited from A-primary, but scaler and coefficients are fitted afresh
on its separately filtered historical rows. Target-side filtering is
applied after observation, never fed as a predictor. Both samples are
retrospective and require separate approval before execution.

For each Lane A sample and each split, report the full origin count,
target-valid count, feature-complete count, anomaly counts by type/field,
per-method eligible-training, finite-forecast, abstention, scored, and
emitted-but-not-scored counts, and baseline-only and feature-aware
**common** scored sets. The row-level
ledger in QNT-003B §6 assigns one exclusive primary reason by a total
priority order while retaining every overlapping reason. Each
method/sample/origin has one forecast status and one separate score status;
later score exclusions never change forecast emission. It requires
`N_origins=N_emitted+N_abstained` and
`N_emitted=N_scored+N_emitted_but_not_scored`, plus
`N_origins=N_scored+sum(N_primary_exclusion_code)` for each
method/sample/split. `N_emitted` includes finite forecasts regardless of
later target scoreability. Every comparison set is the exact intersection
of the methods' **scored-forecast** sets; report its sorted timestamp-set
SHA-256 using `YYYY-MM-DDTHH:MM:SSZ\n` UTC serialization and its count.
A-primary and A-sensitivity metrics are separate; a paired sensitivity
comparison must also use their cross-sample timestamp intersection. No row disappears
silently and unknown availability remains separately counted.

**Lane B (verified point-in-time): BLOCKED.** It requires as-of source
revision and publication/observation evidence, as-of manifest and quality
evidence, verified feature availability, and decision-time eligibility.
The pinned Gold snapshot has `available_at=null` and
`decision_eligible=false` for **all 50,845 rows**. The Lane B universe
is empty; no closure timestamp, current ingestion time, or retrospective
manifest check may be substituted for historical publication evidence.
Neither Lane A sample is a trading backtest.

## 6. Remaining limitations and review gate

The manifest audit's missing-hour findings are archive/local absence,
not retained raw REST proof of every gap. One disputed BTC close/volume
and four shortened-close observations remain unresolved; no outage or
root cause is inferred. The selected Silver revision and manifest are
retrospective, so even mathematically chronological Lane A results, if
later authorized, cannot establish historical point-in-time performance,
execution feasibility, or profitability. The Gold snapshot remains
research-only and has zero decision-eligible rows.

Owner review must accept or request a **versioned design change** to the
explicit numerical conventions, samples, accounting rules, and comparison
boundaries before any separate implementation/evaluation authorization.
The proposed protocol identifier is `qnt-003d-design-v1`; assigning it
here creates no executable artifact. QNT-003A's target and QNT-003C's
historical audit were not changed. No source code, market data, feature
snapshot, dependency, target dataset, prediction, model fit, or metric
was produced by QNT-003D.
