# QNT-002B — BTC/USDT 1h Feature Contract v1

**Status:** five design decisions approved by the project owner; Stage 1
offline engine and synthetic tests implemented and validated. A first local,
research-only Stage 2B Gold snapshot was produced under separate owner
authorization and is audited in `docs/QNT-002B_REAL_DATA_AUDIT.md`. This
contract does not authorize signals, backtesting, model training, automated
execution, or changes to Bronze, Silver, or QNT-002A.

## 1. Scope and source of truth

- Market identity: `binance` Spot, `BTC/USDT`, `1h` only.
- Numeric source: the existing canonical Silver Parquet at
  `data/silver/binance/1h/BTC-USDT.parquet`. Its relevant columns are
  timezone-aware UTC `timestamp` and `ingested_at`, plus Float64 `open`,
  `high`, `low`, `close`, and `volume`. In Silver, `ingested_at` is the local
  `observed_at` of the selected canonical observation, **not** an exchange
  publication timestamp; see `src/quant/validation/ohlcv.py`.
- Quality evidence: the documented BTC findings in
  `docs/QNT-001B_VERIFICATION_REPORT.md`, with exact local verification
  artifacts under ignored `data/verification/`. A future implementation must
  use a versioned, machine-readable anomaly manifest separate from Silver;
  it must not infer anomaly facts from a first API candle or silently
  substitute another provider.
- Designed output: one deterministic, local-only Gold snapshot. No network
  fetch, exchange call, or new dependency is part of feature computation.

### Approved decisions

1. `timestamp` is the UTC candle open; `candle_end_at = timestamp + 1h`.
   `available_at` is null without actual publication or observation evidence.
   Candle closure alone is never verified publication.
2. A versioned anomaly manifest, separate from Silver, carries source
   evidence without changing historical OHLCV.
3. Exactly the seven features in §4 are approved, with sample rolling
   standard deviation (`ddof=1`) and strict hourly continuity.
4. Preserve calculated research values and propagate quality metadata;
   anomaly-affected rows and rows with unknown availability have
   `decision_eligible = false`.
5. Pin `feature_version` and `source_snapshot_sha256`, and record
   `generated_at` separately from historical availability.

## 2. Time and point-in-time semantics

Let `t` denote the **UTC candle open** for a one-hour interval `[t, t+1h)`.
All timestamps are timezone-aware UTC, hour-aligned, and stored at microsecond
precision. `timestamp = t` is the Gold row's identity, not its decision time.
For an observed candle, its theoretical closure boundary is
`candle_end_at = t + 1h`. This is a lower bound even when a recorded
source close time is shortened; a shortened close does **not** permit earlier
use. A missing candle has a theoretical boundary but no observed value.
The build must use a fixed UTC `analysis_as_of` boundary and reject any
source candle with `t + 1h > analysis_as_of` or `ingested_at < t + 1h`;
incomplete candles never enter a feature row.

`available_at` is the earliest **evidence-supported availability time for the
complete quality-aware row**. It is not the theoretical close, the processing
time, or by itself permission to make a decision. For a row with an observed
current candle and at least one non-null feature, define `D_f(t)` as the
complete source-candle dependency set in §5. Then:

```text
required_sources(t) = union(D_f(t) for each non-null feature f)
available_at(t) = max(
    candle_end_at(t),
    ingested_at(s) for every s in required_sources(t),
    quality_evidence_available_at(t)
)
```

`quality_evidence_available_at(t)` is the later of the pinned manifest
version's own verified availability and the evidence times of any manifest
records involved at `t`; it is unknown if any required time is unknown.
The formula applies only when all required source-observation times and the
manifest/quality-evidence availability time are established. Otherwise
`available_at = null`, including a missing current candle or no non-null
feature. `ingested_at` supports **local observation by that time**, not
exchange publication at that time. An independently verified publication
time could provide stronger evidence in a future contract, but must never be
invented. An anomaly does not itself null `available_at`: its veto is carried
by `decision_eligible`. A future decision consumer needs non-null
`available_at <= decision_time`, `decision_eligible = true`, and an actually
materialized snapshot by decision time. Unknown availability fails closed.

Binance may publish or revise a candle after the theoretical close. Silver
does not record the first public publication time. The selected Silver value
is only proven locally observed by `ingested_at`, which may be years after
`t` for a backfill or later revision. Likewise, QNT-001B/C archive findings
were verified retrospectively. Including that quality registry makes the
complete quality-aware row no earlier than its evidence time. Thus a
2021 `timestamp` is **not** a claim of 2021 decision availability. A future
backtest cannot use rows with null `available_at` or simulate decisions
before it; it also needs as-of source and anomaly-manifest snapshots so later
revisions and retrospective classifications do not leak backward. The
current selected Silver snapshot does not reconstruct historical as-of
states. Historical features remain computable for descriptive research,
even where retrospective decision eligibility is false. Do not backdate
`available_at` to `t + 1h` or substitute `generated_at` for availability.

For each numeric feature at `t`, only candles with opens `s <= t` may enter
its formula or continuity check. Feature definitions contain no future
window, full-sample threshold, or QNT-002A retrospective regime label.
`available_at` and anomaly metadata may reflect later *evidence*, but that
evidence moves the availability time forward; it never grants earlier use.
`generated_at` records when the Gold snapshot was processed and can be years
later than the source candle. The feature snapshot pins source and manifest
digests so a canonical revision cannot silently replace the prior state.

## 3. Common mathematical and numeric rules

Write `O_t`, `H_t`, `L_t`, `C_t`, and `V_t` for open, high, low, close, and
base-asset volume of the candle opening at `t`. The source validation contract
requires finite positive prices, `H_t >= max(O_t, C_t, L_t)`,
`L_t <= min(O_t, C_t, H_t)`, and finite `V_t >= 0`. A breach is an input-audit
failure, not a value to repair. Feature outputs are nullable Float64; no
NaN or infinity may be written. Implementations may evaluate log ratios as
`ln(a) - ln(b)` for numeric stability, preserving the defined formula.

The approved 24h and 168h windows are **trailing elapsed UTC hours**, not
row counts after dropping gaps. Rolling volatility uses the sample standard
deviation (`ddof=1`, denominator `k-1`) of exactly `k` one-hour log returns.
No annualization or scale multiplier is applied. A complete window means
every expected hourly candle open is observed and valid. A documented anomaly
does not silently change a numeric formula; it is explicitly flagged as
described below.

Let `s` be the first observed open of the dataset or of a newly contiguous
segment after a gap. “Earliest eligible open” below refers to **that segment's
warm-up**, not an inferred listing date. At every eligible open `t`, the
theoretical minimum availability is `t + 1h`; actual evidence-supported
`available_at` may be much later or unknown.

## 4. Feature definitions

### `log_return_1h`

- **Formula:** `r_t = ln(C_t / C_(t-1h))`.
- **Source columns:** `close` at `t-1h` and `t`; their `timestamp` and
  `ingested_at` for continuity and availability.
- **Lookback/minimum:** one elapsed hour; exactly two consecutive observed
  candles. Earliest eligible open: `s + 1h`.
- **Alignment:** stored on the row opening at `t`; it is the return ending
  with candle `t`, not a return available when candle `t` opens.
- **Null/gap:** null at segment start, a missing `t`, or the first observed
  candle after any gap. Never use a multi-hour close change as one-hour return.
- **Numeric edge:** both closes must be finite and strictly positive;
  equality yields `0`. Invalid inputs fail the source audit; non-finite
  computed results fail the build. **Dtype:** nullable Float64.

### `volatility_24h`

- **Formula:** with `k=24`,
  `r_i = ln(C_i/C_(i-1h))` for `i=t-23h,...,t`,
  `mean = (1/k) sum(r_i)`, and
  `volatility_24h(t) = sqrt(sum((r_i-mean)^2)/(k-1))`.
- **Source columns:** `close`, `timestamp`, `ingested_at` for every candle
  from `t-24h` through `t`, inclusive.
- **Lookback/minimum:** 24 consecutive one-hour returns, requiring exactly
  25 consecutive observed candles. Earliest eligible open: `s + 24h`.
- **Alignment:** trailing window ends at `t`; earliest theoretical use is
  `t + 1h`, then subject to the row's `available_at`.
- **Null/gap:** null until warm-up completes; any missing candle in
  `[t-24h,t]` makes it null. Invalid source data aborts the build. Restart
  the full 24-return count after a gap; no partial window or minimum-period
  relaxation.
- **Numeric edge:** a constant-return window yields `0`; finite outputs
  only. Raw hourly, not annualized. **Dtype:** nullable Float64.

### `volatility_168h`

- **Formula:** the same sample-standard-deviation formula with `k=168` and
  `r_i` for `i=t-167h,...,t`.
- **Source columns:** `close`, `timestamp`, `ingested_at` for every candle
  from `t-168h` through `t`, inclusive.
- **Lookback/minimum:** exactly 168 consecutive returns and 169 consecutive
  observed candles. Earliest eligible open: `s + 168h`.
- **Alignment:** trailing window ends at `t`; theoretical minimum use is
  `t + 1h`, subject to `available_at`.
- **Null/gap:** null during warm-up or if any required hour is missing.
  Invalid source data aborts the build. A gap resets all 168 returns; no
  interpolation or partial window.
- **Numeric edge:** constant returns yield `0`; finite, raw hourly sample
  standard deviation only. **Dtype:** nullable Float64.

### `momentum_24h`

- **Formula:** `momentum_24h(t) = C_t / C_(t-24h) - 1`, equivalently
  `exp(sum of the 24 consecutive one-hour log returns) - 1`.
- **Source columns:** endpoint `close` values; `timestamp`, `close`, and
  `ingested_at` of every intervening candle for strict continuity and
  availability.
- **Lookback/minimum:** exactly 25 consecutive observed hourly candles
  spanning 24 elapsed hours. Earliest eligible open: `s + 24h`.
- **Alignment:** value belongs to row `t` and uses no candle later than `t`.
  The theoretical minimum is `t + 1h`; actual use requires
  `decision_time >= available_at` with non-null `available_at`.
- **Null/gap:** null if either endpoint or any intervening hour is absent;
  invalid source data aborts the build. Do not calculate a 24h endpoint
  ratio across a gap.
- **Numeric edge:** both endpoint closes must be positive and finite;
  identical endpoint closes yield `0`, and a finite result is strictly
  greater than `-1`. **Dtype:** nullable Float64.

### `momentum_168h`

- **Formula:** `momentum_168h(t) = C_t / C_(t-168h) - 1`, equivalently
  `exp(sum of the 168 consecutive one-hour log returns) - 1`.
- **Source columns:** endpoint `close` values plus `timestamp`, `close`, and
  `ingested_at` of every intervening candle for continuity and availability.
- **Lookback/minimum:** exactly 169 consecutive observed hourly candles
  spanning 168 elapsed hours. Earliest eligible open: `s + 168h`.
- **Alignment:** trailing value at `t`; theoretical minimum use is
  `t + 1h`, subject to the later evidence-supported `available_at`.
- **Null/gap:** null during warm-up or if any hour in `[t-168h,t]` is
  missing. Invalid source data aborts the build. Restart from a new
  contiguous segment after a gap.
- **Numeric edge:** positive, finite endpoints required; equal endpoints
  yield `0`, and a finite result is strictly greater than `-1`.
  **Dtype:** nullable Float64.

### `volume_change_1h`

- **Formula:** `volume_change_1h(t) = V_t / V_(t-1h) - 1`.
- **Source columns:** `volume` at `t-1h` and `t`, with both timestamps and
  `ingested_at` values.
- **Lookback/minimum:** exactly two consecutive observed hourly candles;
  earliest eligible open is `s + 1h`.
- **Alignment:** belongs to row `t`; theoretical minimum use is `t + 1h`,
  subject to `available_at`.
- **Null/gap:** null at segment start, missing `t`, first candle after a
  gap, or when `V_(t-1h) = 0`. Do not substitute an epsilon or carry volume.
- **Numeric edge:** if prior volume is positive and current volume is zero,
  the result is valid `-1`; if both are zero or only prior is zero, the
  result is null (`zero_denominator`). Negative/non-finite source volume is
  an audit failure; overflow is not serialized. **Dtype:** nullable Float64.

### `normalized_range_1h`

- **Formula:** `normalized_range_1h(t) = (H_t - L_t) / C_t`.
- **Source columns:** `high`, `low`, `close`, `timestamp`, and `ingested_at`
  at `t` only.
- **Lookback/minimum:** current observed candle only; earliest eligible
  open is `s`. A gap immediately before `t` does not invalidate this
  single-candle feature.
- **Alignment:** belongs to row `t`; theoretical minimum use is `t + 1h`,
  subject to `available_at`.
- **Null/gap:** null if candle `t` is missing; a failed source audit aborts
  the build. No forward fill. It does not require a preceding hour.
- **Numeric edge:** `C_t > 0` is required; `H_t = L_t` gives `0`; output
  must be finite and nonnegative. **Dtype:** nullable Float64.

## 5. Continuity, nulls, and anomaly propagation

The designed Gold timeline has one row for every expected UTC hour between
the first and last observed Silver candle opens, inclusive. Missing hours
remain explicit rows with all seven feature values null. Outside this
observed interval, coverage is **unknown** unless separately evidenced;
no pre-listing or exchange-outage inference is made. `source_present` is
false on a missing hour. The first observed candle after a gap can have a
valid `normalized_range_1h`, but the two one-hour change features are null,
and both rolling/momentum windows restart their full warm-up.

Every null feature has a deterministic `null_reason__<feature>` from the
closed vocabulary `missing_candle`, `insufficient_history`, `gap_in_window`,
or `zero_denominator`. A non-null feature has a null reason field of null.
`insufficient_history` means the required lookback precedes the dataset's
first observed open; `gap_in_window` means an absent hour lies within its
observed interval. Source validation or computed non-finite failures stop
the build rather than quietly producing a feature table. If several null
causes coexist, the priority is `missing_candle`, then `gap_in_window`, then
`insufficient_history`, then `zero_denominator`.
No forward fill, interpolation, synthetic gap fill, or row dropping is
allowed. Null is not numeric zero.

The versioned anomaly manifest is an input separate from Silver, not a
correction layer. Each record must contain `timestamp` (UTC candle open),
`anomaly_type`, sorted `affected_fields`, `source_evidence` (source URI or
local artifact reference plus checksum and observation/verification time),
`severity`, `review_status`, and `manifest_version`. A missing-hour record
uses `affected_fields = ["candle"]` and retains the verified-coverage basis;
absence alone is not an outage classification. For a shortened close,
record the verified source close timestamp and its source format/precision.
For a missing hour, record coverage evidence and distinguish absence from
unknown coverage. The manifest must have a stable digest, deterministic
ordering, a documented version change for revisions, and an evidence time
for when the quality-aware assertion became available. An unknown evidence
time makes `quality_evidence_available_at` unknown. No manifest record may
rewrite `open`, `high`, `low`, `close`, or `volume` in Silver.

The first manifest version must preserve the following BTC findings from
QNT-001B/C, with references to the verified REST/archive evidence:

| UTC candle open | Known issue | Field-level evidence |
| --- | --- | --- |
| 2021-04-23 01:00 | REST/Silver versus verified archive disagreement | `close`, `volume` differ; `open`, `high`, `low` agree |
| 2021-02-11 03:00 | Shortened source close | Recorded close `03:40:54.773` UTC; next hour missing |
| 2021-04-25 04:00 | Shortened source close | Recorded close `04:00:58.146` UTC; next hour missing |
| 2021-08-13 01:00 | Close-time precision/shortening unresolved | Recorded close `01:59:59.000` UTC, 999 ms before usual; next hour missing |
| 2023-03-24 12:00 | Shortened source close | Recorded close `12:39:41.646` UTC; next hour missing |

All 14 missing BTC hourly opens remain explicit missing-hour rows; their
full list and seven gap periods are in QNT-001B/C. The manifest must not
silently mark an undocumented hour as a verified outage.
Silver itself has no source close-time column, so shortened-close metadata
must come from the checksum-verified local evidence, never be invented from
Silver OHLCV. The August 999 ms case remains uncertain, not declared an
exchange interruption.

For every feature, `D_f(t)` includes **all** nominal candles needed for its
numeric formula or continuity check, even when the eventual value is null.
A documented anomaly at open `a` propagates to
`anomaly_involved_features` at `t` exactly when `a in D_f(t)`. A missing
hour in `D_f(t)` makes the feature null with the appropriate gap reason;
it also contributes a `missing_hour_in_window` quality flag. This is
provenance, not an assertion that a numeric value changed.
`value_sensitive_features` applies only to non-null values and is narrower: a
documented disputed field must be a direct numeric input, or a shortened
close makes a formula-input candle potentially partial. Unknown affected fields
are conservatively value-sensitive. Both lists are ordered by the fixed
seven-feature order, may be empty, and never alter numeric values.
`involved_anomalies` retains the contributing manifest records' timestamp,
type, affected fields, severity, review status, and evidence reference;
sort by timestamp, type, then stable evidence reference. The Gold row's
`quality_flags` is a sorted set from `missing_hour`,
`missing_hour_in_window`, `insufficient_history`, `zero_denominator`,
`source_discrepancy`, `shortened_close`, `anomaly_in_window`, and
`unknown_availability`, as applicable. A false source flag means no
documented finding in the pinned manifest, not proof of absence.

| Feature | Exact dependency set `D_f(t)` | Documented disputed `close` at `a` | Documented disputed `volume` at `a` | Shortened-close at `a` |
| --- | --- | --- | --- | --- |
| `log_return_1h` | `{t-1h,t}` | Value-sensitive if `a` is either endpoint | Provenance only if `a` is in set | Value-sensitive if `a` is in set |
| `volatility_24h` | Every hourly candle in `[t-24h,t]` | Value-sensitive if `a` is in set, as a return endpoint | Provenance only if `a` is in set | Value-sensitive if `a` is in set |
| `volatility_168h` | Every hourly candle in `[t-168h,t]` | Value-sensitive if `a` is in set, as a return endpoint | Provenance only if `a` is in set | Value-sensitive if `a` is in set |
| `momentum_24h` | Every hourly candle in `[t-24h,t]` | Value-sensitive only if `a=t-24h` or `a=t`; otherwise provenance only | Provenance only if `a` is in set | Value-sensitive at an endpoint; interior candle is provenance-only for the endpoint formula |
| `momentum_168h` | Every hourly candle in `[t-168h,t]` | Value-sensitive only if `a=t-168h` or `a=t`; otherwise provenance only | Provenance only if `a` is in set | Value-sensitive at an endpoint; interior candle is provenance-only for the endpoint formula |
| `volume_change_1h` | `{t-1h,t}` | Provenance only if `a` is in set | Value-sensitive if `a` is either endpoint | Value-sensitive if `a` is in set |
| `normalized_range_1h` | `{t}` | Value-sensitive if `a=t`, because `close` is the denominator | Provenance only; `volume` is not an input | Value-sensitive if `a=t` |

The disputed `close` at 2021-04-23 01:00 therefore affects the return
ending at 01:00 and the return ending at 02:00; the disputed `volume`
similarly affects both adjacent volume changes. `normalized_range_1h` at
01:00 is value-sensitive to the disputed `close` denominator, even though
its `high` and `low` agree between checked sources.
For volatility, a disputed close may influence the two adjacent constituent
returns when both fall in the window. Momentum's interior candles are
retained for continuity even though an interior close cancels from the
endpoint formula. A shortened-close candle's own features and otherwise
valid windows including it receive provenance flags; numeric sensitivity
follows the field-level rules above. The next known missing hour makes
cross-gap windows null. All four shortened-close observations are treated
conservatively, including the unresolved 999 ms case.

### Row-level eligibility

`decision_eligible` is one **row-level Boolean**, not seven implicit
per-feature approvals. It is true only when the current candle is present,
all seven features are non-null, `available_at` is non-null, the manifest
and its quality evidence are available, no documented anomaly is involved
in any of the seven dependency windows, and source/feature validation
passed. Any failure makes it false. Absence of a manifest flag is not proof
that the market data is anomaly-free. Thus a warm-up row, a gap-affected row, a
zero-denominator row, an anomaly-affected row, or a row with unknown
availability is false even if some feature values remain useful for
research. Per-feature anomaly and null metadata still explain the cause.
This conservative gate is a research data-quality property, **not** a
trading signal or a claim that a later backtest is point-in-time safe.
Anomaly flags do not prove an exchange outage, select archive values, or
authorize use of an as-of-2021 decision with a retrospectively verified
2026 quality flag.

## 6. Gold feature schema, versioning, and provenance

This is the approved design for one Parquet snapshot under local `data/gold/`.
The separately authorized Stage 2B artifact and validation are documented in
`docs/QNT-002B_REAL_DATA_AUDIT.md`.

| Column or column family | Dtype | Nullability / meaning |
| --- | --- | --- |
| `exchange`, `symbol`, `timeframe` | Utf8 | Non-null constants `binance`, `BTC/USDT`, `1h` |
| `timestamp` | `Datetime(us, UTC)` | Non-null, unique UTC candle open |
| `candle_end_at` | `Datetime(us, UTC)` | Non-null `timestamp + 1h`; not publication evidence |
| `available_at` | `Datetime(us, UTC)` | Nullable evidence-supported row availability defined in §2; null means unverified, not a guessed closure time |
| Seven feature columns named in §4 | Float64 | Nullable; never NaN/Inf |
| `null_reason__<feature>` for each of seven features | Utf8 enum | Null exactly when its numeric feature is non-null |
| `source_present`, `missing_hour` | Boolean | Non-null complements; missing row has all features null |
| `source_discrepancy_at_t`, `shortened_close_at_t` | Boolean | Non-null documented positive flags at row `t`; false means *not documented*, not proven absent |
| `source_discrepancy_fields` | `List(Utf8)` | Sorted affected source fields, empty if not documented |
| `recorded_source_close_at` | `Datetime(us, UTC)` | Nullable verified source close timestamp, not taken from Silver |
| `anomaly_involved_features`, `value_sensitive_features` | `List(Utf8)` | Non-null, deterministic ordered feature-name lists as defined in §5 |
| `involved_anomalies` | `List(Struct)` | Non-null sorted manifest references with timestamp, type, affected fields, severity, review status, and evidence reference |
| `quality_flags` | `List(Utf8)` | Non-null, sorted closed-vocabulary flags defined in §5 |
| `decision_eligible` | Boolean | Non-null row-level conjunction in §5; no trading instruction |
| `max_source_ingested_at`, `quality_evidence_available_at` | `Datetime(us, UTC)` | Nullable evidence inputs to `available_at` |
| `availability_basis` | Utf8 enum | `local_observation_plus_quality_evidence` or `unverified`; not a claim of exchange publication |
| `feature_version`, `manifest_version` | Utf8 | Non-null contract/calculation and anomaly-interpretation versions |
| `source_snapshot_sha256`, `anomaly_manifest_sha256` | Utf8 | Non-null SHA-256 digests of exact Silver source bytes and exact manifest bytes |
| `generated_at` | `Datetime(us, UTC)` | Non-null Gold processing timestamp; not historical market-data availability |

Primary key within a snapshot: `(exchange, symbol, timeframe, timestamp)`.
Exactly one row per expected hour, sorted ascending, with no duplicate keys;
`timestamp` advances by exactly one hour. A source revision yields a **new
input snapshot identity** and recomputed Gold snapshot, not a second key in
the same snapshot or a silent correction to a prior result. The full
snapshot identity comprises `feature_version`, `source_snapshot_sha256`,
`manifest_version`, and `anomaly_manifest_sha256`; `generated_at` is run
provenance, not a source-availability input. Feature values, flags, reasons,
and row order must be deterministic for pinned inputs and a fixed
`analysis_as_of`. Byte-for-byte artifact reproduction additionally requires
the same injected `generated_at`, serializer, and metadata settings; a real
new run timestamp may change file bytes without changing feature values.
All files remain ignored local data. When non-null,
`available_at >= candle_end_at`, `max_source_ingested_at <= available_at`, and
`quality_evidence_available_at <= available_at`. A null `available_at`
always implies `decision_eligible = false`.

## 7. Offline validation plan (design only)

Use small synthetic UTC fixtures only; no exchange calls or downloaded data.
Exact-value tests should cover hand-calculated log return, sample rolling
standard deviation, simple-return momentum (both endpoint ratio and
`exp(sum of consecutive log returns) - 1`), volume ratio, and
high-low/close range. The Stage 1 synthetic suite tests:

1. `timestamp` is candle open, `candle_end_at=t+1h`, and verified
   `available_at` is no earlier than closure. Late `ingested_at` or later
   quality evidence delays it. Unknown publication/observation or manifest
   evidence time leaves `available_at` null and `decision_eligible=false`;
   `generated_at` cannot fill that gap.
2. Prefix invariance: adding candles after `t` cannot change any feature
   value on or before `t` for the same pinned source revision. A feature's
   dependency timestamps never exceed its row timestamp. Later revisions
   have a new snapshot identity and later availability, not retroactive
   point-in-time values.
3. One- and multi-hour internal gaps produce explicit null rows; first
   post-gap change features are null, a single-candle range can resume,
   24/168 volatility and momentum remain null until their full contiguous
   warm-up completes. No lag or rolling pair crosses a gap.
4. Two and three identical closes give zero one-hour log returns; fixtures
   with 25 and 169 identical closes give zero volatility only after each
   full window exists. Non-constant fixtures verify the `k-1` denominator.
   No partial window is accepted.
5. Prior volume zero (including `0 -> 0`) yields null with
   `zero_denominator`; positive prior volume to current zero yields `-1`.
   Equal positive volumes yield `0`.
6. At synthetic anomaly open `a`, assert the exact §5 dependency sets for
   all seven features: both adjacent one-hour changes, each valid rolling
   window containing `a`, endpoint-only close sensitivity for momentum,
   and single-candle range sensitivity to disputed `close` but not `volume`.
   A shortened close and following gap propagate provenance to every
   dependent feature, including null crossing windows; those windows remain
   null, not backfilled. Set the row-level
   eligibility false while retaining calculable values.
7. Duplicate, non-UTC, misaligned, invalid-OHLC, negative-volume, incomplete
   relative to fixed `analysis_as_of`, non-finite, and unexpected-identity
   inputs fail before Gold publication.
8. Manifest fixtures assert required evidence fields, deterministic version
   and digest changes, and retention of source OHLCV. Assert that a complete,
   anomaly-free, evidenced row can be eligible and that warm-up, gaps,
   zero-denominator, unknown availability, and any involved anomaly cannot.
9. Repeated runs with pinned inputs, versions, `analysis_as_of`, and fixed
   evidence timestamps produce identical feature values, schema, rows, null
   reasons, and ordered flags. Artifact hashes match when `generated_at` and
   serialization settings are also fixed. DuckDB and Polars read Parquet
   identically; uniqueness and all availability inequalities are asserted.

The Stage 1 implementation uses synthetic fixtures only; this plan does not
authorize production Gold dataset generation.

## 8. Remaining implementation considerations

- Review the local candidate at
  `configs/qnt-002b-btc-anomalies.candidate.v1.json`: it contains the 14
  verified missing hours, four shortened closes, and one field-level source
  discrepancy for BTC/USDT, with evidence references and checksums.
  `severity=unrated`, `review_status=unresolved`, and
  `version_available_at=null` intentionally prevent the candidate from
  claiming reviewed availability. The unresolved 999 ms shortened close
  remains anomaly-affected. Do not infer root causes or exchange publication
  times from this manifest.
- Define stable feature and manifest version identifiers before the first
  Gold build; pin exact input bytes, a fixed `analysis_as_of`, deterministic
  ordering, and an injectable `generated_at`. A code or anomaly-policy
  change must produce a new feature/manifest version as appropriate.
- Derive `quality_evidence_available_at` from auditable evidence. If it or
  any required local-observation time cannot be established, leave
  `available_at` null. Do not infer a historical Binance publication time
  from a retrospective download or candle closure.
- Future backtesting would require separately approved as-of source and
  anomaly snapshots and a decision-time gate; this design alone cannot make
  a 2021 historical decision point-in-time verified. Existing QNT-002A
  descriptive calculations and retrospective regime labels are neither
  inputs to these seven features nor modified by this contract.

Stage 1 stops after offline implementation and review. No production Gold
dataset generation or commit is authorized by this contract alone.
