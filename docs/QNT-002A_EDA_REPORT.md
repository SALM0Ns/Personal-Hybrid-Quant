# QNT-002A — Gap-Aware BTC/USDT Exploratory Data Analysis

This is read-only, descriptive research on the existing Binance Spot BTC/USDT
Silver 1-hour dataset. It does not create trading signals, train a model, or
change Bronze/Silver. All derived rows and charts are local-only.

## Dataset identity and coverage

- Source: `data/silver/binance/1h/BTC-USDT.parquet`.
- Input SHA-256: `edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3`.
- Identity: `binance` Spot, `BTC/USDT`, `1h`.
- First and last observed candle opens (UTC): `2021-01-01T00:00:00Z` to `2026-10-20T12:00:00Z`.
- End-exclusive boundary: `2026-10-20T13:00:00Z`.
- Expected hourly opens: 50,845; observed: 50,831; missing: 14.
- Dataset audit: 0 duplicates, 0 out of order, 0 misaligned, 0 OHLC invalid, 0 nonpositive prices, 0 negative volumes. All source timestamps are timezone-aware UTC.

Silver schema:

| Field | Silver type |
| --- | --- |
| exchange | String |
| symbol | String |
| timeframe | String |
| timestamp | Datetime(time_unit='us', time_zone='UTC') |
| open | Float64 |
| high | Float64 |
| low | Float64 |
| close | Float64 |
| volume | Float64 |
| ingested_at | Datetime(time_unit='us', time_zone='UTC') |

The local `data/gold/qnt-002a/btc_usdt_1h/timeline.parquet` contains every expected hour in this
observed interval. Missing hours have null OHLCV; none is forward-filled or
interpolated. No first-observed candle is treated as proof of listing date.

## Data quality findings

Documented absent hours still missing: 14;
unexpected missing hours: 0;
documented gaps now observed: 0.
The missing hours form 7 gap periods.
Exact missing opens (UTC):

- `2021-02-11T04:00:00Z`
- `2021-03-06T02:00:00Z`
- `2021-04-20T02:00:00Z`
- `2021-04-20T03:00:00Z`
- `2021-04-25T05:00:00Z`
- `2021-04-25T06:00:00Z`
- `2021-04-25T07:00:00Z`
- `2021-08-13T02:00:00Z`
- `2021-08-13T03:00:00Z`
- `2021-08-13T04:00:00Z`
- `2021-08-13T05:00:00Z`
- `2021-09-29T07:00:00Z`
- `2021-09-29T08:00:00Z`
- `2023-03-24T13:00:00Z`

The documented BTC archive/REST discrepancy at 2021-04-23 01:00 UTC is flagged
on 1 observed candle.
The four BTC shortened-close candles are flagged on
4 observations. These
flags come from `docs/QNT-001B_VERIFICATION_REPORT.md`, not from a close-time field in
Silver. Their causes remain unknown. Returns touching flagged candles and
rolling windows containing those returns retain explicit anomaly indicators.
Because the disputed 01:00 candle's **close** enters two adjacent ratios, the
valid returns ending at 2021-04-23 01:00 and 02:00 UTC are both flagged. Each
shortened-close candle immediately precedes a documented gap: its ending
return is flagged, the next hour has no return, and the first observed candle
after the gap has an invalid return. No historical value is replaced.

## Gap-aware returns and distribution

A return is valid only when both observed candle opens are exactly one hour
apart. Valid returns: 50,823; invalid among observed
candles: 8; invalid across all
timeline hours: 22. Of valid
returns, 6 touch a flagged candle
and 50,817 do not. The primary descriptive tables
include all continuity-valid returns and report the clean subset separately.

| Series | Count | Mean | Median | Std | Min | Max | Skew | Excess kurtosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| simple_return | 50,823 | 3.8877e-05 | 3.50492e-05 | 0.00618764 | -0.0895447 | 0.123159 | -0.0241546 | 16.8262 |
| log_return | 50,823 | 1.97255e-05 | 3.50486e-05 | 0.00618997 | -0.0938105 | 0.116145 | -0.196943 | 16.5384 |
| clean_log_return | 50,817 | 2.01359e-05 | 3.51302e-05 | 0.00618941 | -0.0938105 | 0.116145 | -0.196449 | 16.5451 |

Quantiles use linear interpolation (Hyndman–Fan type 7):

| Series | 1% | 5% | 25% | 75% | 95% | 99% |
| --- | --- | --- | --- | --- | --- | --- |
| simple_return | -0.0185901 | -0.00870197 | -0.00225216 | 0.0023772 | 0.00877001 | 0.0183972 |
| log_return | -0.018765 | -0.00874006 | -0.0022547 | 0.00237438 | 0.00873177 | 0.01823 |
| clean_log_return | -0.0187476 | -0.00873941 | -0.00225465 | 0.00237442 | 0.00873219 | 0.0182309 |

Standard deviation uses the sample `n-1` denominator. Skewness is the third
central moment divided by the second central moment to the 3/2 power;
excess kurtosis is the fourth divided by the squared second minus 3, with
`n` denominators for moments. For log returns, the fraction beyond three
sample standard deviations from the mean is
0.0198926, versus
0.0026998 for a matched normal
benchmark. This and excess kurtosis are descriptive heavy-tail comparisons,
not tests of significance or distributional proof.

## Volatility analysis

Rolling values are **raw hourly** sample standard deviations of 24 or 168
consecutive valid one-hour log returns (requiring 25 or 169 consecutive
observed candle opens). They are not annualized. Gaps reset each window;
no window crosses an absent hour.

| Returns/window | Valid windows | Flagged windows | Clean windows | Median std | Maximum std |
| --- | --- | --- | --- | --- | --- |
| 24 | 50,639 | 29 | 50,610 | 0.0046007 | 0.0344916 |
| 168 | 49,534 | 3 | 49,531 | 0.00494751 | 0.020875 |

The 168-hour volatility distribution and its time variation describe episodes
of higher and lower variability. Positive absolute-return autocorrelation in
the table below is consistent with volatility clustering descriptively, but
does not establish predictability or a causal mechanism.

## Autocorrelation

Pairs are separated by the stated number of actual elapsed UTC hours, have
valid returns at both endpoints, and stay in the same uninterrupted segment;
thus no missing observation lies between paired returns. Correlations are
pairwise Pearson coefficients: each endpoint series is centered on its own
mean over that lag's eligible pairs, then the cross-product sum is divided by
the geometric mean of the two centered square sums. This is not a fixed-mean
full-series ACF estimator. Clean-endpoint pair counts exclude flagged
endpoint returns; they do not replace the primary counts.

| Lag (h) | Valid pairs | Log-return ACF | Abs log-return ACF | Clean-endpoint pairs |
| --- | --- | --- | --- | --- |
| 1 | 50,815 | -0.00549019 | 0.287593 | 50,808 |
| 2 | 50,807 | -0.011627 | 0.236424 | 50,799 |
| 6 | 50,775 | 0.00752697 | 0.19833 | 50,767 |
| 12 | 50,727 | 0.0121658 | 0.17895 | 50,719 |
| 24 | 50,631 | -0.0261412 | 0.193959 | 50,623 |
| 48 | 50,439 | -0.0112533 | 0.161633 | 50,431 |
| 168 | 49,527 | 0.00695588 | 0.164164 | 49,524 |

These are descriptive associations, not evidence of tradable predictability.

## UTC seasonality

Only valid one-hour log returns enter each group. `Flagged` counts returns
touching documented anomalous candles; Monday is weekday 0.

### UTC hour of day

| Group | Count | Mean log r | Median log r | Std log r | Mean abs(log r) | Flagged |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 2,118 | 7.20936e-05 | -0.000100681 | 0.00665299 | 0.00425774 | 0 |
| 1 | 2,119 | -0.000105746 | -6.41097e-05 | 0.00658262 | 0.00409332 | 2 |
| 2 | 2,116 | -0.000194916 | -7.68865e-05 | 0.00560503 | 0.00355371 | 1 |
| 3 | 2,116 | -0.000109625 | 3.04677e-05 | 0.00555659 | 0.00329823 | 1 |
| 4 | 2,116 | 4.04085e-05 | 6.83053e-05 | 0.00463505 | 0.0028858 | 1 |
| 5 | 2,116 | 9.22083e-05 | 6.12223e-05 | 0.00485043 | 0.00300399 | 0 |
| 6 | 2,117 | 2.76939e-05 | 2.21659e-05 | 0.00543795 | 0.00316226 | 0 |
| 7 | 2,117 | 4.84731e-05 | -8.52767e-06 | 0.00529084 | 0.00331938 | 0 |
| 8 | 2,117 | 0.000172374 | 5.05504e-05 | 0.00634574 | 0.00359708 | 0 |
| 9 | 2,118 | -1.14919e-05 | 8.40585e-05 | 0.00523452 | 0.00330791 | 0 |
| 10 | 2,119 | 0.000109716 | 4.34945e-05 | 0.00509775 | 0.00310535 | 0 |
| 11 | 2,119 | 8.42861e-05 | 0.000176698 | 0.00506847 | 0.00324732 | 0 |
| 12 | 2,119 | 1.76029e-05 | -4.79711e-05 | 0.00685445 | 0.00387149 | 1 |
| 13 | 2,117 | -3.46235e-05 | -0.000195936 | 0.00706533 | 0.00464921 | 0 |
| 14 | 2,117 | -0.000187464 | -2.43685e-05 | 0.00853784 | 0.00556571 | 0 |
| 15 | 2,118 | 0.000101123 | 0.000125175 | 0.00770952 | 0.00511017 | 0 |
| 16 | 2,118 | -8.1046e-05 | -0.000218089 | 0.00661487 | 0.00429581 | 0 |
| 17 | 2,118 | -5.27083e-06 | 0.000202942 | 0.00646591 | 0.00426258 | 0 |
| 18 | 2,118 | -2.2719e-06 | 0.000110339 | 0.00634919 | 0.00405914 | 0 |
| 19 | 2,118 | -0.000122131 | 0.000119279 | 0.00643061 | 0.00404806 | 0 |
| 20 | 2,118 | 0.00014953 | 0.000156851 | 0.00677801 | 0.0040966 | 0 |
| 21 | 2,118 | 0.000303385 | 0.000263044 | 0.0061721 | 0.00383273 | 0 |
| 22 | 2,118 | 0.000264281 | 0.000113146 | 0.00583164 | 0.00375665 | 0 |
| 23 | 2,118 | -0.000155461 | 1.04781e-05 | 0.0057671 | 0.00355836 | 0 |

### UTC weekday (Monday=0)

| Group | Count | Mean log r | Median log r | Std log r | Mean abs(log r) | Flagged |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 7,272 | 8.82988e-05 | 2.72127e-05 | 0.00698662 | 0.00440244 | 0 |
| 1 | 7,258 | -3.34439e-05 | 2.53467e-05 | 0.00657333 | 0.00423185 | 0 |
| 2 | 7,245 | 0.000125435 | 0.000100106 | 0.00688301 | 0.00428741 | 0 |
| 3 | 7,246 | -0.000108328 | -3.99671e-05 | 0.0062314 | 0.00405357 | 1 |
| 4 | 7,264 | 1.39873e-05 | 9.18902e-05 | 0.00665829 | 0.00420292 | 4 |
| 5 | 7,270 | 4.31926e-07 | 2.99896e-05 | 0.00452517 | 0.00258622 | 0 |
| 6 | 7,268 | 5.1536e-05 | 5.25899e-05 | 0.00502061 | 0.00305433 | 1 |

Group differences are exploratory. No trading rule was optimized or evaluated.

## Descriptive market regimes

Low/medium/high labels are assigned only to **anomaly-free** 168-return
windows. Thresholds are the empirical 1/3 and 2/3 quantiles of all eligible
windows in this **full analysis sample**: 0.00421531
and 0.00586811 raw hourly standard deviation.
This is retrospective classification using future sample information; labels
are **not point-in-time trading signals** and must not be used for training
or backtesting.

- Low: 16,511; medium: 16,510; high: 16,510.
- Unclassified timeline hours (warm-up, gaps, or flagged windows): 1,314.

| UTC year | Low | Medium | High |
| --- | --- | --- | --- |
| 2021 | 0 | 1,233 | 6,383 |
| 2022 | 1,273 | 3,113 | 4,374 |
| 2023 | 4,621 | 3,012 | 957 |
| 2024 | 1,787 | 4,386 | 2,611 |
| 2025 | 4,691 | 2,872 | 1,197 |
| 2026 | 4,139 | 1,894 | 988 |

## Local artifacts and reproducibility

Run `PYTHONPATH=src .venv/bin/python -m quant.research` from the repository
root. It reads only the approved BTC Silver file and regenerates the local
`data/gold/qnt-002a/btc_usdt_1h/results.json`, `timeline.parquet`, CSV tables, SVG charts, and
this report. Outputs omit
run timestamps and machine-specific paths. The local artifacts are ignored by
Git; this report contains aggregates, not the market dataset.

Tables:

- `data/gold/qnt-002a/btc_usdt_1h/tables/autocorrelation.csv`
- `data/gold/qnt-002a/btc_usdt_1h/tables/missing_hours.csv`
- `data/gold/qnt-002a/btc_usdt_1h/tables/regime_yearly_counts.csv`
- `data/gold/qnt-002a/btc_usdt_1h/tables/return_distribution.csv`
- `data/gold/qnt-002a/btc_usdt_1h/tables/utc_hour_seasonality.csv`
- `data/gold/qnt-002a/btc_usdt_1h/tables/utc_weekday_seasonality.csv`
- `data/gold/qnt-002a/btc_usdt_1h/tables/volatility.csv`

Charts:

- `data/gold/qnt-002a/btc_usdt_1h/charts/autocorrelation.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/regime_yearly_distribution.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/return_distribution_over_time.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/return_histogram.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/return_quantiles.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/rolling_volatility.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/utc_hour_seasonality.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/utc_weekday_seasonality.svg`
- `data/gold/qnt-002a/btc_usdt_1h/charts/volatility_distribution.svg`

The return histogram and volatility histogram display only the central
0.1–99.9% range for legibility, with omitted tail counts in their axis labels;
all statistical calculations use the full eligible samples. Monthly return
quantiles and daily median rolling volatilities are display aggregations,
not replacements for the hourly timeline.

## Methodological limitations and future questions

- Four shortened-close observations may not represent complete uninterrupted
  hours; Silver lacks source close-time metadata. The 999 ms case may reflect
  precision rather than materially shortened trading. No cause is inferred.
- The April 2021 REST/archive discrepancy is unresolved. Both source values
  remain in provenance artifacts; Silver is unchanged. Descriptive statistics
  include continuity-valid flagged returns, with a clean-return sensitivity
  summary, rather than silently correcting or discarding them.
- The 14 missing hours are absent from both checked Binance sources, but no
  exchange-outage or listing-date claim follows. Other months and providers
  were not independently reconciled here.
- The sample ends at the last locally observed complete candle, not a claimed
  all-history endpoint. Group differences and heavy-tail comparisons are
  descriptive; no significance tests, causal claims, strategy optimization,
  model training, or backtesting were performed.
- Future research can ask whether tail and volatility descriptions are stable
  across years and anomaly-exclusion choices, whether UTC seasonal patterns
  survive uncertainty-aware testing, and whether archive revisions change
  results. Such work needs separate approval and point-in-time safeguards.
