# QNT-003A — Research Question and Target Definition

**Status:** proposed research design for owner review. This document defines a
study; it does not authorize target generation, model training, baseline
execution, predictive evaluation, backtesting, signals, or trading.

## 1. Title, motivation, and questions

**Working title:** Evaluating Short-Horizon BTC/USDT Return Predictability
Using Gap-Aware Historical Market Features.

QNT-002A established descriptive, gap-aware BTC/USDT analysis, and QNT-002B
produced seven historical features with explicit continuity and anomaly
metadata. A later study could ask whether these existing features contain
incremental information about the following hour. That is a hypothesis, not
a finding. Association, predictive improvement, economic value, and
historical decision availability have not been established.

**Primary question:** Can historical BTC/USDT hourly market features improve
next-hour log-return prediction compared with simple statistical baselines
under chronological evaluation?

Secondary questions, also untested:

1. What relationships exist between the seven historical features and
   next-hour returns?
2. How does evaluation performance vary across chronological periods?
3. How do gaps and anomaly flags affect usable sample coverage?
4. How stable are conclusions across evaluation windows?

The baseline definitions, evaluation windows, and metrics are deliberately
left for QNT-003B design review. No baseline or model is run in QNT-003A.

## 2. Dataset and feature scope

- Venue/instrument/timeframe: Binance Spot BTC/USDT, 1-hour OHLCV only.
- Historical inputs: the existing validated BTC/USDT Silver Parquet and the
  existing local, research-only QNT-002B Gold feature snapshot. Do not fetch,
  revise, fill, or regenerate market data or features for this stage.
- Feature set: exactly `log_return_1h`, `volatility_24h`,
  `volatility_168h`, `momentum_24h`, `momentum_168h`,
  `volume_change_1h`, and `normalized_range_1h`, as defined in
  `docs/QNT-002B_FEATURE_CONTRACT.md`. QNT-002A's retrospective volatility
  regime labels are not predictors in this proposed study.
- Study bounds: only the existing observed historical coverage and its
  explicit internal missing-hour timeline. The first observed candle is not
  proof of an instrument listing or verified availability start; periods
  outside the observed interval are not silently classified or synthesized.

No ETH/USDT, SOL/USDT, other venue, or other timeframe is in scope.

## 3. Formal prediction target

Let `t` be a timezone-aware, hour-aligned **UTC candle-open timestamp**.
The candle at `t` spans `[t, t+1h)` and the next candle spans
`[t+1h, t+2h)`. Let `C_t` be the validated Silver close of the candle
opening at `t`. A future, separately authorized target construction would
define, on the feature row indexed by `t`,

```text
target_next_1h_log_return(t) = ln(C_(t+1h) / C_t)
```

The target is the close-to-close return between two **consecutive hourly
candles**, not the return known at open `t` and not an executable return
promised at exact clock boundaries. Its observation horizon is the next
hour after candle `t` closes. The theoretical earliest complete-candle
boundary for observing it is `t+2h`. Actual availability may be later and
is **unknown** without auditable publication or local-observation evidence
for the target and any required quality evidence. Neither `t+2h` nor the
Gold snapshot's `generated_at` is a verified publication time.

The target is undefined (null, never zero-filled) if either candle is
missing, the two opens are not exactly one hour apart, either candle is
incomplete at a fixed analysis boundary, or either close is non-finite or
non-positive. Invalid Silver source values are an input-quality failure,
not permission to repair them. The final observed hour cannot have a target
without an observed, fully closed next candle; no future observation is
invented. The target's direct numeric dependencies are `close` at `t` and
`t+1h`. Its quality/provenance dependencies include both complete candles
and their documented anomaly records.

## 4. Feature–target temporal alignment

| Element | UTC time or dependency | Interpretation |
| --- | --- | --- |
| Feature-row key | `t` | Open of the last candle allowed in the seven feature calculations. |
| Feature information | Candle opens `<= t` only | Exact lookbacks and null rules remain those of QNT-002B; no target data enters a feature. |
| Theoretical feature decision boundary | No earlier than `t+1h` | Candle `t` has closed in theory; this is not verified publication or a trading decision time. |
| Target information | Closes `C_t` and `C_(t+1h)` | The next candle is an outcome, never a feature input at row `t`. |
| Theoretical target observation boundary | No earlier than `t+2h` | The next candle has closed in theory; actual publication/observation latency remains unknown. |

Mathematical look-ahead prevention means the numeric feature formula and
its continuity checks use no candle later than `t`. Verified point-in-time
availability is a different, stronger claim: it needs evidence that the
exact source revision, feature snapshot, and quality interpretation existed
by the proposed decision time. Satisfying the first does **not** satisfy the
second. Chronological ordering alone cannot recover historical as-of source
states or establish when Binance published a candle.

The pinned QNT-002B Gold snapshot has `available_at=null` and
`decision_eligible=false` for every row because historical quality-manifest
availability is unverified. These fields must not be overwritten, backdated
to candle close, or reinterpreted as trading-ready. It cannot presently
support a point-in-time-valid historical backtest. Any future retrospective
statistical evaluation would need an explicit, separately approved policy
that distinguishes exploratory association from a verified historical
decision simulation; this document grants neither approval.

## 5. Gap, anomaly, and sample-quality policy

Maintain an explicit hourly UTC timeline. A target at `t` requires both
`t` and `t+1h` to be observed, validated, fully closed candles. There is no
forward fill, interpolation, synthetic OHLCV, or multi-hour return relabeled
as a one-hour target. Preserve QNT-002B's feature null reasons and strict
24/168-hour continuity; a valid target does not make a null feature valid,
and a valid feature row does not make a missing next-hour target valid.

Feature quality and target quality are separate audit dimensions:

- Feature-side flags and anomaly dependencies at row `t` come only from the
  approved QNT-002B feature dependency windows ending at or before `t`.
  Do not let the next candle's value or anomaly status enter a predictor.
- Target-side provenance examines the two endpoint candles at `t` and
  `t+1h` **after the outcome is observed**. A missing endpoint makes the
  target null. A documented `close` discrepancy at either endpoint makes a
  calculable target value-sensitive; a `volume` discrepancy is provenance
  only for this close-only formula. A shortened-close record at either
  endpoint makes the outcome potentially affected because candle
  completeness/field impact is unresolved. Keep the calculated value for
  research if both validated closes exist, but flag it; do not replace
  Silver values. In particular, the disputed 2021-04-23 01:00 UTC close
  can affect the targets indexed by both 00:00 and 01:00 UTC.
- The 19-record candidate manifest includes 14 missing-hour records, four
  shortened-close records, and one source discrepancy. Archive/local gap
  absence is documented, but retained raw REST evidence does not prove
  every gap-window absence; neither exchange-outage causes nor historical
  publication times are established. Keep those limitations visible.

A later sample accounting plan must report separate, explicit reasons such
as missing current or next candle, invalid/incomplete source, feature
warm-up or gap, zero-volume feature denominator, feature-side anomaly,
target-side anomaly, and unknown availability. Reasons may overlap: publish
counts by reason and define any precedence before computing a single
exclusive exclusion count. Do not silently remove anomalous observations.
The distinction between a mathematically calculable research row and a
decision-eligible row must remain intact. With the present Gold snapshot,
the latter count is zero.

## 6. Historical availability and non-goals

Silver's local `ingested_at` is an observation time, not proof of first
exchange publication. QNT-002B's `available_at` is null for the pinned
snapshot, and its retrospective manifest is unresolved. A target's later
close and retrospective anomaly review cannot be treated as information
available at the preceding decision boundary. This design does not infer
latency from candle duration or claim a point-in-time-safe dataset.

QNT-003A performs **documentation only**. It does not construct target
data, calculate feature–target relationships, execute baselines, select or
train models, produce predictive metrics, backtest, create trading signals,
place orders, ingest data, or modify Bronze, Silver, or Gold. It makes no
claim of predictability, profitability, or future trading suitability.

## 7. Open decisions for QNT-003B design review

1. Define the simple statistical baselines and the exact metric(s) without
   running them. Clarify whether the later question is descriptive
   association only or an explicitly authorized predictive experiment.
2. Specify chronological train/validation/test boundaries, window stability
   checks, and how to prevent overlap or selection leakage. This must not
   imply historical point-in-time availability has been verified.
3. Define the sample inclusion matrix for nullable features, warm-up,
   missing targets, anomaly-affected values, and overlapping exclusion
   reasons. Decide whether anomaly sensitivity analyses are permitted and
   how they would be reported without silent record removal.
4. Decide what auditable publication/as-of source and manifest evidence, or
   what explicit research-only limitations, are required before any future
   evaluation. Current `decision_eligible=false` is not an overrideable
   convenience flag; backtesting requires separate authorization and a
   defensible point-in-time data policy.
5. Specify future target-artifact versioning and source/manifest provenance
   if implementation is later approved. No target artifact is created here.

## 8. Acceptance criteria for owner review

- The primary and four secondary questions are framed as hypotheses, with
  no reported results or performance claims.
- Scope is limited to the existing Binance Spot BTC/USDT 1h Silver/Gold
  definitions and seven approved features.
- `target_next_1h_log_return` uses exactly consecutive closes `C_t` and
  `C_(t+1h)`, is aligned to feature row `t`, and cannot be observed before
  the next candle's theoretical close at `t+2h`.
- Feature dependencies end at `t`; target dependencies include `t+1h`;
  mathematical leakage prevention is not confused with proven historical
  publication availability.
- Missing/invalid candles and source anomalies remain explicit, with
  feature quality separate from target quality; no values are filled or
  silently corrected.
- The existing null `available_at`, zero decision-eligible rows, and
  research-only/backtesting restriction are preserved.
- QNT-003B open decisions are identified without implementing them, and
  owner approval is required before any later execution.
