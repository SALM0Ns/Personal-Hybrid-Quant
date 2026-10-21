# QNT-003C — Independent Leakage and Data-Quality Design Audit

**Status:** documentation-only independent review of the written QNT-003A
and QNT-003B proposals. No target, baseline, comparator, metric, backtest,
signal, or model was generated or executed.

## 1. Executive verdict

**CONDITIONAL — not yet ready for final protocol approval or execution.**
The core candle alignment, gap boundaries, and arithmetic training cutoff
are internally consistent on the explicitly *theoretical* close-event
timeline. No direct use of `y_t` or `C_(t+1h)` in a feature or baseline
forecast at origin `o_t` was found. Three **MAJOR** design gaps remain:
retrospective anomaly-mask use in fitting/scoring must be separated more
rigorously from as-of information; the proposed feature-aware comparator
is not reproducibly specified; and the sample-accounting funnel needs
per-method, disjoint reason rules. These block final approval of a
comparative protocol, not preparation of this audit. There are no
**CRITICAL** findings under the documents' explicit non-trading,
non-execution restrictions.

The Gold snapshot's `available_at=null` and `decision_eligible=false` on
all 50,845 rows remain hard restrictions. This audit does not authorize
retrospective statistical evaluation or trading backtesting.

## 2. Scope and evidence reviewed

Read the full written specifications in:

- `docs/QNT-003A_RESEARCH_DESIGN.md` (§§2–8): question, target,
  feature/target timing, anomalies, and unavailable historical evidence.
- `docs/QNT-003B_EVALUATION_PROTOCOL.md` (§§1–10): baselines, event order,
  splits, metrics, sample filters, optional comparator, and open decisions.
- `docs/QNT-002B_FEATURE_CONTRACT.md` (§§2–6): seven feature dependency
  windows, anomaly propagation, time semantics, and row eligibility.
- `docs/QNT-002B_MANIFEST_AUDIT.md`: conditional evidence for 19 candidate
  records and the unresolved REST/availability limitations.
- `docs/QNT-002B_REAL_DATA_AUDIT.md`: pinned input/output identities,
  14 gaps, feature nulls, and zero decision-eligible rows.
- `docs/DECISIONS.md`: approved QNT-002B policy and QNT-003 design-only
  boundary.

This is a specification audit, not a runtime proof of a future
implementation. No market-data distribution, prediction, or performance
was inspected or computed. QNT-003A and QNT-003B were **not edited**.

## 3. Forecast-origin and target audit

For a Gold row with UTC candle open `t`, all seven numeric feature
dependencies end at or before `t`; the QNT-002B feature contract explicitly
forbids a later candle in a feature. QNT-003A §3 defines
`y_t=ln(C_(t+1h)/C_t)`, requiring the adjacent candle. QNT-003B §2 places
the theoretical forecast event just *after* candle `t` completes at
`o_t=t+1h` and the target's theoretical closure at `t+2h`. The equality
case in `s+2h <= o_t` is safe only under the document's explicit event
order: close/validate the earlier outcome, then refit/forecast. It is **not**
proof of exchange publication at the clock boundary.

| UTC example | Feature/past outcome at forecast event | Future outcome and audit result |
| --- | --- | --- |
| `t=2024-01-01 00:00`; `o_t=01:00` | Features may use candles through the 00:00 open. The immediately previous target `y_(2023-12-31 23:00)` uses the 23:00 and 00:00 closes and theoretically completes at 01:00. | `y_t` additionally needs the candle opening 01:00 and closes no earlier than 02:00. It is excluded from the 01:00 mean/refit. |
| Daily AR refit at `o_t=2024-01-01 00:00` (`t=2023-12-31 23:00`) | Latest theoretical training target is `y_(2023-12-31 22:00)`, completing at 00:00. Its AR pair uses candles opening 21:00, 22:00, and 23:00. | The forecast target `y_t` needs the 00:00 candle and cannot close until 01:00; the refit must exclude it. |
| Last pinned forecast origin `2026-10-20 12:00` (`t=11:00`) | Candle 11:00 theoretically closes at 12:00. | The next candle opens 12:00 and closes at the pinned `13:00` analysis boundary; origin 13:00 lacks a complete next candle and is not scorable. |

The expanding mean's cutoff in QNT-003B §§2–3 excludes incomplete
outcomes mathematically. The daily AR refit in §3 uses pairs whose target
closure precedes the forecast event and holds coefficients until the next
scheduled refit. The phrase “at or after 00:00 UTC” should be read with
the same close-before-refit event ordering; a future implementation must
log the exact refit origin and maximum admitted target closure.

## 4. AR(1) pair construction

The equation is unambiguous at the return level:

```text
r_u = ln(C_u / C_(u-1h))
x_s = r_s                     # closes at opens s-1h and s
y_s = r_(s+1h)                # closes at opens s and s+1h
y_s = alpha + beta*x_s + epsilon_s
forecast at t: alpha_hat + beta_hat*r_t
```

Thus a fitted pair requires exactly three consecutive, valid candle
opens `s-1h, s, s+1h`; the forecast lag requires `t-1h, t`. The return
indexed by `s` is **not** a return known when candle `s` opens. The latest
fittable pair at `o_t=t+1h` has `s=t-1h`, because its outcome candle opens
at `t` and theoretically closes at `o_t`. A pair with `s=t` would use the
unobserved forecast target and is prohibited. QNT-003B §3 correctly
requires 720 eligible pairs, an intercept, OLS, daily UTC refits, and an
explicit abstention for missing lag, cold start, or unidentified slope.

The gap check is also sound. At the documented missing open
`2021-02-11 04:00 UTC`, `y_(03:00)` and `y_(04:00)` are null. At `t=05:00`,
`r_t` is null because the 04:00 candle is absent, even if `y_(05:00)`
could later be observed; AR must abstain. Training pairs at `s=03:00`,
`04:00`, and `05:00` fail because one of their three required opens is
missing. A subsequent pair can enter only when its own three opens are
consecutive; deleting gap rows does not make distant returns adjacent.

**Residual ambiguity:** “two distinct `x_s` values” is a mathematical
identification condition, not a numerical-stability policy for nearly
constant lags. See MINOR finding N2.

## 5. Gap and anomaly propagation

QNT-003A §5 and QNT-003B §§2, 3, and 6 forbid forward filling,
interpolation, fabricated OHLCV, and gap-crossing one-hour returns.
QNT-002B preserves explicit missing-hour rows and restarts 24/168-hour
feature warm-up after gaps. Baseline B may average separately valid
returns on either side of a gap; AR may pool separately valid three-candle
pairs; neither constructs a return across the gap.

Feature-side quality depends on candles at or before `t`. Target-side
quality depends on both `t` and `t+1h` and is assessed **after** the
outcome; QNT-003A §5 and QNT-003B §6 prohibit the next candle's anomaly
status from becoming a predictor. At the documented disputed close at
`2021-04-23 01:00 UTC`, `y_(00:00)` and `y_(01:00)` are value-sensitive;
the target formula does not use volume, so disputed volume is provenance
only. The QNT-002B feature `log_return_1h` is sensitive on rows 01:00 and
02:00. AR pairs can also inherit the disputed close through their lag;
for example, pair `s=02:00` has `x_s=r_(02:00)` and is affected even
though its target `y_s` may be clean. A shortened-close candle at either
target endpoint remains potentially affected; the 2021-08-13 01:00
999-ms case has unresolved interpretation and is not called an outage.

The proposed conservative QNT-003B filter excludes **any** documented
endpoint anomaly from its primary target sample, including a field that
does not change the target number. It retains calculable values and flags
for research, so it does not silently repair or delete Silver. The
manifest audit, however, verified archive/local absence for the 14 gaps
without retained raw REST gap-window responses; the backfill still labels
their coverage unknown. An “anomaly-free” row means only “not documented
in this pinned candidate,” not verified clean or point-in-time available.

## 6. Sample eligibility and auditable accounting

The two proposed universes are conceptually sound **if kept separate**:

- Baseline-only diagnostic universe: target-valid and conservatively
  target-clean origins where Zero Return, the 720-target mean, and the
  720-pair AR each emitted a forecast. It need not have all seven features.
- Feature-aware comparison universe: the baseline intersection further
  restricted to all seven non-null, anomaly-uninvolved QNT-002B features
  and a valid, separately specified comparator forecast. All compared
  methods must be rescored on this exact same UTC timestamp set.
- Verified point-in-time decision universe: empty for the pinned Gold
  snapshot because all 50,845 `available_at` values are null and all
  `decision_eligible` values are false. It must not be relabeled as a
  retrospective mathematical universe.

QNT-003B §6 correctly asks for overlapping reason counts, an exclusive
funnel, and method abstentions. It does **not** yet specify how to assign
one primary reason when, for example, a row has both a null feature and
an anomaly in that feature window, or AR has both a missing lag and too
few training pairs. Different implementations could produce different
exclusive counts while obeying the broad category order. For a future
auditable specification, define a keyed record for every candidate origin
with: source/target validity bits; all target anomaly bits; each feature's
null reason and anomaly involvement; each method's lag/training/fit/
prediction status; its theoretical close cutoff; and the actual inclusion
bits for each comparison universe. Freeze a **total** priority order for
exclusive reasons, keep independent multi-label counts, and assert that
per-method exclusive counts plus scored counts equal all origins in each
calendar interval. Pin the input/manifest/protocol identities and a sorted
digest of every common evaluation timestamp set. Do not overwrite Gold's
`decision_eligible` to make any retrospective funnel nonempty.

## 7. Temporal validation and availability review

The split is a fixed UTC calendar rule, not selected from measured
returns: training origins `[2021-01-01 01:00, 2024-01-01 00:00)`,
validation `[2024-01-01 00:00, 2025-01-01 00:00)`, and test
`[2025-01-01 00:00, 2026-10-20 13:00)`, with complete targets required
before the pinned end. QNT-003B §4 forbids random splits and shuffled
cross-validation. Earlier validation/test labels may be used in later
predeclared expanding or daily refits, but no future label, score-based
schedule change, or test-informed hyperparameter choice may affect an
earlier forecast. That is a valid *theoretical online-update* design, not
a historically evidenced simulation. The term “test remains untouched”
is too broad given its own permitted prior-test-label updates (N1).

QNT-003B §7 correctly bars full-sample scaling/preprocessing and
QNT-002A retrospective regime labels. Yet the optional regularized
comparator is only a family-level proposal: its exact fit window, scaler,
penalty grid, chronological tuning folds, cold-start/minimum sample, and
refit cadence are not fixed. A feature-versus-baseline claim cannot be
reproduced until they are, even if the baseline rules are otherwise clear.

Five distinct gates remain separate: correct feature/target algebra,
chronological outcome isolation, as-of source revision/publication,
as-of manifest/quality knowledge, and executable trading prices/costs.
Passing the first two does not pass the last three. Current Silver is a
retrospective selected revision; the manifest has
`version_available_at=null`; Gold has `available_at=null`. No
hypothetical candle-close time may be written as verified publication.
Research-only retrospective evaluation requires separate owner approval;
trading backtesting remains prohibited.

## 8. Classified findings

| ID | Severity | Evidence in written design | Why it matters; concrete correction | Blocks final design approval? |
| --- | --- | --- | --- | --- |
| M1 | **MAJOR** | QNT-003B §2 explicitly says the later-assembled manifest makes ex-post filtered training non-PIT; §§3 and 6 nevertheless use that filter to choose mean/AR history and primary scored targets. Manifest audit has `version_available_at=null`. | Training membership and scored sample can depend on evidence unavailable at the nominal origin. Specify a separate, explicitly retrospective **fixed-mask** experiment (if authorized), disclose the mask's future knowledge, predeclare unfiltered-valid versus anomaly-filtered sensitivity/accounting, and make no as-of claims. A PIT experiment requires as-of source and manifest evidence and is currently empty. | **Yes** for a final executable comparative protocol; not a flaw in the mathematical target formula. |
| M2 | **MAJOR** | QNT-003B §7 calls ridge “one possible” family and defers scaling, regularization, and missingness; §9 defers grid, folds, and minimum fitted sample. | The primary feature-versus-baseline question has no fully prespecified comparator, allowing outcome-dependent choices later. Freeze or explicitly remove the comparator before finalizing: exact estimator/penalty, preprocessing, λ grid, inner chronological folds, minimum sample, refit cadence, failure behavior, and common evaluation universe. Fit all transforms inside each past window. | **Yes** for a final design intended to compare features with baselines. |
| M3 | **MAJOR** | QNT-003B §6 gives category-level exclusion precedence but groups feature-null/anomaly and AR lag/training/forecast failures without a within-group priority or per-method conservation rule. | Exclusive counts can diverge; without formal membership sets and reconciliation, reported metric denominators cannot be independently checked. Define row-keyed masks, a total primary-reason priority, method-specific abstention counts, intersection-set identities/digests, and count-reconciliation invariants for every calendar period. Keep overlapping reasons separately. | **Yes** for a reproducible final evaluation protocol. |
| N1 | **MINOR** | QNT-003B §4 says the test is “untouched” while also allowing earlier test outcomes in later predeclared refits. | Clarify that test **metrics and protocol choices** are sealed, while prior test labels may enter the frozen online-update rule; log the exact refit cutoffs. | No, but clarify before implementation. |
| N2 | **MINOR** | QNT-003B §3 requires 720 pairs and two distinct AR lag values, but gives no near-singularity/finite-coefficient rule. | Prespecify a deterministic numerical rank or variance threshold and abstention for ill-conditioned/non-finite OLS rather than silently changing the estimator. | No, but clarify before implementation. |
| I1 | **INFORMATIONAL** | QNT-003A §§3–5 and QNT-003B §§2–3 correctly use `t`, `t+1h`, `t+2h`; QNT-002B dependencies end at `t`. | The nominal alignment prevents direct future-candle input into predictors; it does not verify data publication. | No. |
| I2 | **INFORMATIONAL** | QNT-003A §5, QNT-003B §§3/6, and QNT-002B §5 preserve explicit gaps and distinct feature/target anomaly roles. | No gap-spanning return or silent source replacement is specified. | No. |
| I3 | **INFORMATIONAL** | QNT-003B §§4–6 specify UTC calendar splits, equal timestamp intersections, RMSE/MAE, and an exact-zero three-class directional-accuracy diagnostic. | These are suitable prespecified conventions, subject to M1–M3 and owner approval; no result is reported. | No. |
| I4 | **INFORMATIONAL** | QNT-002B real-data audit reports 50,845 Gold rows, 14 missing hours, null availability, and zero eligible decisions. | The research-only boundary is correctly repeated; no trading/backtest approval follows. | No. |

Counts: **0 CRITICAL, 3 MAJOR, 2 MINOR, 4 INFORMATIONAL**.

## 9. Required corrections before finalizing the design

1. Resolve **M1** by writing a two-lane policy: (a) an explicitly
   retrospective, fixed-manifest statistical study that reports its
   ex-post filtering and sensitivity to it, only if separately approved;
   (b) a verified-as-of study that cannot proceed with current null
   availability. Never call lane (a) a trading backtest or PIT forecast.
2. Resolve **M2** by finalizing or removing the feature-aware comparator.
   If retained, specify the complete estimator/tuning/refit contract and
   predeclare how the common feature-complete timestamp universe is formed.
3. Resolve **M3** with a total, method-specific exclusion/abstention
   vocabulary and reconciliation equations for each split. Preserve every
   overlapping quality flag; never force a calculable anomaly value to
   disappear from provenance.
4. Clarify **N1–N2** before any implementation. Independently verify
   boundary, gap, anomaly, and count behavior with synthetic fixtures if
   implementation is separately authorized; no such tests were run here.

## 10. Final approval recommendation

**CONDITIONAL.** QNT-003A's target and QNT-003B's three baseline formulas
are mathematically coherent on the stated hypothetical event timeline.
The three major specification gaps block final approval of a reproducible
feature-versus-baseline evaluation design until the owner reviews and
resolves them. Current Gold availability and decision eligibility also
block any point-in-time/trading interpretation. No predictive evaluation,
backtest, model fitting, target generation, or data change is authorized by
this audit.

## 11. Validation and repository integrity

Only this Markdown audit was created during QNT-003C. The already untracked
QNT-003A and QNT-003B drafts were left unchanged; no source code,
dependency declaration, configuration, or market dataset was edited.
Tracked-file `git diff --check` and a whitespace check of this untracked
file produced no errors. No test suite or model was run because this is a
design audit, not an implementation. No market-data request was made.

All six local Bronze/Silver Parquet SHA-256 values still match the baselines
in `docs/QNT-002B_REAL_DATA_AUDIT.md`. The QNT-002B Gold snapshot still
matches SHA-256
`18f70e22ce189787e74fad2d8f7d14202625e09f355bf81792f2aac7bcd1a66d`.
These read-only checks do not alter the unknown historical availability or
the candidate manifest's unresolved status. Nothing was staged, committed,
or pushed.
