# PQTA BTC 1H — Mathematical Strategy

This document describes the current **Pure Mathematical / Rule-Based Quant
MVP**, as implemented in the working tree. It is a personal, informational
decision-support application using Binance BTC/USDT Spot reference data.
There is no machine learning, model fitting, automatic parameter selection,
confidence estimate, expected-return forecast, position sizing or order
execution in this application path. Existing historical research modules
remain separate; documenting them does not activate them.

The rule and its reference levels have not been shown to be profitable or
validated for Exness BTC CFD execution. A formula being mathematically defined
does not establish a predictive advantage.

## 1. Implementation sources and calculation roles

| Source | Implemented responsibility |
| --- | --- |
| [`analysis.py`](../src/quant/app/analysis.py), `fetch_recent_market` / `validate_market_rows` | Bounded public Spot retrieval and exact current, completed hourly window. |
| [`adapter.py`](../src/quant/features/adapter.py), `prepare_shared_features` | OHLCV/observation validation and reuse of the seven-feature engine. |
| [`engine.py`](../src/quant/features/engine.py), `_feature_value` | Returns, sample volatility, momentum, volume change and normalized range. |
| [`analysis.py`](../src/quant/app/analysis.py), `assess_direction` | Fixed BUY / SELL / HOLD rule. |
| [`analysis.py`](../src/quant/app/analysis.py), `calculate_atr` / `reference_levels` | Wilder ATR(14), reference entry, SL/TP and numeric guards. |
| [`server.py`](../src/quant/app/server.py), `make_handler` | Final current-hour check and explicit failure response. |
| [`app.js`](../web/app.js), `renderReferenceLevels` / `updateExpiry` | Reference-level display, precision checks, expiry and stale-display clearing. |

All seven shared features are calculated, displayed and required to be finite.
Only hourly return, 24h volatility, 24h momentum and 168h momentum directly
determine direction. The other three still participate in input validity:
for example, a null volume change rejects analysis rather than being ignored.
ATR is additional application metadata, not an eighth Gold feature and not
an input to the directional predicate.

## 2. Variables, units and fixed parameters

| Symbol | Definition |
| --- | --- |
| $h$ | One hour. All candle times are timezone-aware UTC. |
| $t$ | A candle's **open** timestamp; its theoretical close is $t+h$. |
| $t_0,t_1,\ldots,t_{N-1}$ | Validated consecutive candle opens, with $t_j=t_0+jh$. |
| $i,j$ | Integer indices with the bounds given in each sum or recurrence; $j=0$ is the first source candle. |
| $x$ | Any UTC timestamp passed to the hour-floor/latest-closed functions. |
| $N$ | Number of candles supplied in the bounded request; the dashboard uses 200. |
| $O_t,H_t,L_t,C_t$ | Open, high, low and close prices for candle $t$, in USDT per BTC. |
| $V_t$ | The candle's nonnegative provider-reported volume; volume ratios use identical source units. |
| $I_t$ | Local receipt timestamp (`ingested_at`) for candle $t$; equal to $R$ for the current live batch. Not an exchange publication timestamp. |
| $r_t$ | One-hour close-to-close natural log return, dimensionless. |
| $n$ | Feature lookback in hourly intervals: 24 or 168. |
| $\bar r_{n,t}$ | Arithmetic mean of the latest $n$ consecutive hourly log returns. |
| $\sigma_{n,t}$ | Sample standard deviation of those hourly returns, dimensionless. |
| $M_{n,t}$ | Simple close-to-close momentum over $n$ hours, dimensionless. |
| $\kappa$ | Fixed threshold multiplier, 0.5. |
| $b_t$ | Directional threshold $\kappa\sigma_{24,t}$, dimensionless. |
| $D_t$ | Directional assessment: BUY, SELL or HOLD, for a validated input. |
| $TR_j$ | True range of candle $t_j$, using candle $t_{j-1}$'s close; in price units. |
| $p$ | ATR smoothing period: 14 true ranges. On this chart these are hourly intervals, not days. |
| $A_j$ | Wilder-smoothed ATR after processing true range $TR_j$; in price units. |
| $E,SL,TP$ | Reference entry, stop loss and take profit; USDT per BTC. |
| $a,b$ | Stop-distance and target-distance multipliers: 1.5 and 3.0 respectively; $b$ here is distinct from the threshold $b_t$. |
| $d_{SL},d_{TP}$ | Absolute entry-to-stop and entry-to-target price distances. These are not account-currency loss/profit amounts. |
| $R$ | UTC observation time sampled after retrieval; stored as `observed_at` and the current payload's `generated_at`. |
| $Q$ | UTC time of the post-calculation HTTP freshness check. |
| $S,T$ | Binance server time and local request-time sample used for clock comparison. |
| $F(x)$ | UTC hour floor: timestamp $x$ rounded down to the start of its UTC hour. |
| $\ell(x)$ | Latest theoretically completed candle open at time $x$. |
| $X$ | Display expiry time. |

Current policy constants are: full feature window 169–500 candles, default
200; ATR helper minimum 15 candles; clock disagreement limit 60 seconds;
assessment lifetime at most 300 seconds; reference-distance relative numeric
tolerance $10^{-10}$. These are implementation choices, not fitted values.
There is no annualization factor or learned coefficient.

## 3. Return, volatility and momentum

### Hourly return

For two consecutive, completed candles:

$$
r_t=\ln(C_t)-\ln(C_{t-h})
    =\ln\left(\frac{C_t}{C_{t-h}}\right).
$$

The implementation subtracts logarithms. Both closes must be positive;
neither a missing hour nor an incomplete candle can be crossed.
`log_return_1h` is a log return, not a simple percentage change.

### Rolling hourly-return dispersion

For $n\in\{24,168\}$:

$$
\bar r_{n,t}=\frac{1}{n}\sum_{i=0}^{n-1}r_{t-ih},
\qquad
\sigma_{n,t}=
\sqrt{\frac{1}{n-1}\sum_{i=0}^{n-1}
       \left(r_{t-ih}-\bar r_{n,t}\right)^2}.
$$

These are `volatility_24h` and `volatility_168h`, calculated using sample
standard deviation (`ddof=1`, Python `statistics.stdev`). The suffix denotes
the estimation window: $\sigma_{24,t}$ is the dispersion of **24 hourly
returns**, not the volatility of a 24-hour cumulative return. The code does
not multiply it by $\sqrt{24}$, annualize it, or treat it as a forecast.
Exactly $n+1$ consecutive source candles are needed for $n$ returns.

### Momentum

$$
M_{24,t}=\frac{C_t}{C_{t-24h}}-1,
\qquad
M_{168,t}=\frac{C_t}{C_{t-168h}}-1.
$$

These are simple cumulative returns. They are not log momentum and are not
the untransformed sum of hourly log returns. Their mathematical relationship
on a complete span is:

$$
M_{n,t}=\exp\left(\sum_{i=0}^{n-1}r_{t-ih}\right)-1.
$$

The code computes the close ratio directly and requires the entire intervening
hourly sequence, even though only the endpoint closes occur in the formula.
The identity above explains the quantities; no extra exponential feature is
calculated. Numeric ratio underflow producing momentum $\leq-1$ is rejected.

### Other calculated and displayed features

$$
\mathrm{volume\_change\_1h}_t=\frac{V_t}{V_{t-h}}-1,
\qquad
\mathrm{normalized\_range\_1h}_t=\frac{H_t-L_t}{C_t}.
$$

A zero previous volume yields null (`zero_denominator`), not an infinite or
imputed ratio. This makes current analysis fail its all-seven-finite check,
even though volume is not a direct directional condition. Zero current volume
is permitted if the previous-volume denominator is positive. The range uses
**close**, not open, as denominator.

| Feature | Minimum consecutive candles | Direct directional input? |
| --- | --- | --- |
| `log_return_1h` | 2 | Yes |
| `volatility_24h` | 25 | Yes |
| `volatility_168h` | 169 | No; displayed and validated |
| `momentum_24h` | 25 | Yes |
| `momentum_168h` | 169 | Yes |
| `volume_change_1h` | 2 | No; displayed and validated |
| `normalized_range_1h` | 1 | No; displayed and validated |

## 4. The project's BUY / SELL / HOLD rule

First calculate:

$$
b_t=\kappa\sigma_{24,t},\qquad\kappa=0.5.
$$

On valid, finite inputs the implemented rule is:

$$
D_t=
\begin{cases}
\mathrm{HOLD}, & b_t=0,\\
\mathrm{BUY}, & M_{24,t}>b_t\ \land\ M_{168,t}>0\ \land\ r_t>0,\\
\mathrm{SELL}, & M_{24,t}<-b_t\ \land\ M_{168,t}<0\ \land\ r_t<0,\\
\mathrm{HOLD}, & \text{otherwise}.
\end{cases}
$$

Every inequality is strict. Equality to the threshold, zero weekly momentum,
zero latest hourly return, conflicting signs, or a zero threshold yields HOLD.
ATR does not enter this rule. There is no ranking, learned weight, ML model,
probability, parameter search, or expected-return calculation.

The comparison between 24-hour simple momentum and half an hourly-return
dispersion estimate is **our fixed heuristic across different horizons**.
It is not a z-score, significance test, horizon-matched risk measure or
calibration derived from the papers below. The 24/168-hour windows, sign
agreement and 0.5 coefficient are project parameter choices.

This predicate is distinct from the full request's validity. Invalid features,
unusable ATR, or nonrepresentable levels reject the request; the API/UI then
reports HOLD with an error and no usable setup. This is different from a valid
HOLD where no directional condition is met.

## 5. True range and exact ATR(14) smoothing

For $j=1,\ldots,N-1$:

$$
TR_j=\max\left(
H_{t_j}-L_{t_j},
\left|H_{t_j}-C_{t_{j-1}}\right|,
\left|L_{t_j}-C_{t_{j-1}}\right|
\right).
$$

The previous close detects a price jump between adjacent observed hours.
A price jump is not a missing timestamp: missing hourly candles are rejected,
not bridged by true range. The first candle supplies only the previous close;
the implementation does not invent a prior close or use its range as a seed.

With $p=14$, initialize at the fifteenth source candle:

$$
A_{14}=\frac{1}{14}\sum_{j=1}^{14}TR_j.
$$

Then apply Wilder's RMA recurrence for $j=15,\ldots,N-1$:

$$
A_j=\frac{13A_{j-1}+TR_j}{14}
   =\frac{13}{14}A_{j-1}+\frac{1}{14}TR_j.
$$

The reported `atr_14` is $A_{N-1}$. It is **not** a rolling simple average
of the last 14 true ranges, nor an EMA with coefficient $2/(14+1)$.
The current 200-candle request supplies 199 true ranges: 14 seed values and
185 subsequent updates. Each request seeds from its own bounded window; it
does not persist an indefinitely smoothed historical ATR. Consequently a
chart initialized with a different history need not match exactly.

Implementation arithmetic uses `math.fsum(TR / 14)` for the seed and
`math.fsum((previous_ATR * (13 / 14), TR / 14))` for updates. This is
algebraically the mean/recurrence above and avoids an unnecessary large
intermediate sum. Finite floating-point rounding remains possible. ATR must
be finite and strictly positive; zero, missing, invalid, stale or insufficient
ATR data rejects analysis. A valid HOLD may display ATR but has no levels.

Wilder [1] is the classical bibliographic background. The official indicator
reference [4] verifies the true-range/RMA convention; our 15-candle seed
boundary and bounded-history implementation are specified by the code above.

## 6. Reference entry, stop loss, take profit and risk/reward

Only when $D_t$ is BUY or SELL:

$$
E=C_t,\qquad A=A_{N-1}.
$$

Here $A$ denotes the latest ATR, and $t=t_{N-1}$. The reference entry is
the latest **completed candle close**, not a current bid/ask, executable quote
or assumption about the next fill.

For BUY:

$$
SL=E-aA=E-1.5A,\qquad TP=E+bA=E+3A.
$$

For SELL:

$$
SL=E+aA=E+1.5A,\qquad TP=E-bA=E-3A.
$$

For either direction:

$$
d_{SL}=|E-SL|=1.5A,\qquad d_{TP}=|TP-E|=3A,
\qquad d_{SL}:d_{TP}=1:2.
$$

This is a **gross price-distance ratio**, not a win probability, expected
profit, account risk budget or cost-adjusted payoff. The 1.5 and 3.0
multipliers are project choices, not empirically validated BTC parameters
from Wilder [1], Moskowitz et al. [2], or Moreira and Muir [3]. No dollar
loss/profit, lot size, margin, commission, spread or slippage is calculated.

Entry, ATR and levels must be finite and positive; BUY requires
$SL<E<TP$, SELL requires $TP<E<SL$. The backend checks the 1.5/3.0
distances and doubled reward using `math.isclose` with relative tolerance
$10^{-10}$ and zero absolute tolerance. The frontend repeats ATR-relative
distance checks. If floating-point cancellation cannot preserve the ratio,
the request fails closed. Levels are not repaired or rounded to broker ticks.
The UI's two-decimal price formatting is display rounding only.

HOLD has `reference_levels=null` and `entry_reference=null`, with no entry,
SL, TP or risk/reward recommendation. Historical preview, loading, failure
and expiry clear previous reference levels.

All prices are labeled **Binance Spot reference estimates — not verified
Exness CFD execution prices**. All application assessments retain
`actionable=false`; no order or broker validation is implied.

## 7. Completed candles, missing data and freshness

For any observation/check time $x$:

$$
\ell(x)=F(x)-h.
$$

The default source grid is exactly
$\ell(R)-199h,\ldots,\ell(R)$, or the candle-open interval
$[\ell(R)-199h,\ell(R)+h)$. Every candle used must satisfy
$t+h\le R$. Candle opens are UTC hour-aligned. No future candle value
enters a feature or ATR update.

The public fetch additionally requires:

$$
|S-T|\le60\ \text{seconds},\qquad F(S)=F(T).
$$

The local clock must not move backwards during retrieval; the latest-closed
hour must not change during that request. After calculation, the server
requires $Q\ge R$ and $\ell(Q)=t_{N-1}$, otherwise it rejects the
result rather than substituting older local Silver data or another provider.

Displayed candle age and assessment expiry are:

$$
\mathrm{age\_seconds}=R-(t_{N-1}+h),
\qquad X=\min\left(R+300\ \text{seconds},F(R)+h\right).
$$

The age is elapsed time since the latest candle's theoretical close, not the
age of an executable quote; the time difference is expressed in seconds.
The frontend checks expiry every second and clears
the assessment/levels when expired. Its request timeout is 45 seconds;
the client has an 8,000 ms request timeout and at most one OHLCV retry.
These are software bounds, not promises of exchange publication latency.

Missing/duplicate/unexpected hours, malformed/nonfinite values, incomplete
candles or a stale latest candle reject the full live request. Prices must
be positive, volume nonnegative, high no lower than any other OHLC price and
low no higher than any other OHLC price. Observation timestamps satisfy
$t+h\le I_t\le R$, inclusive at theoretical closure. Nothing is
forward-filled, interpolated or fabricated.

The shared research engine can represent gaps and warm-up nulls, but this
application refuses a nonconsecutive live window and any null latest feature.
With 200 valid candles all 168-hour dependencies are available. An isolated
ATR calculation needs at least 15 candles; full analysis still needs at least
169. A zero denominator, unavailable feature, nonpositive ATR or unusable
reference price rejects the request. Error HOLD and valid no-condition HOLD
remain distinguishable through quality status and explanation.

The current empty application anomaly manifest is not proof that source
anomalies are absent. Feature `available_at` stays null and feature
`decision_eligible` stays false under the shared contract. Local receipt now
does not establish earliest exchange publication or verified historical PIT
availability. Existing historical Gold, source anomalies and research
restrictions remain unchanged. No historical evaluation is performed here.

## 8. Definitions, research and project choices

| Category | What it establishes | What it does not establish |
| --- | --- | --- |
| Mathematical definitions | Natural log return, simple cumulative return, sample dispersion, ratios and the stated arithmetic identities are reproducible quantities. | That a particular combination predicts BTC returns or yields profitable orders. |
| Classical indicator convention [1, 4] | Background for true range and Wilder-style ATR/RMA. | That 14 hourly periods, a 200-candle seed, or our SL/TP multipliers are optimal or exact replicas of every charting implementation. |
| Published momentum research [2] | Research on an instrument's own past returns, in futures/forwards and longer-horizon settings. | Validation of Binance BTC hourly sign agreement or the 0.5 dispersion threshold. |
| Published volatility research [3] | Research on exposure management using prior realized variance. | Implementation of volatility-managed position sizing here, or evidence for our ATR levels. |
| Our rule and parameters | An explicit, fixed, inspectable heuristic with 24/168-hour windows, a 0.5 threshold multiplier, 14-period ATR, 1.5/3.0 distances and display safeguards. | Fitted/optimal parameters, model confidence, expected returns, an empirical edge or verified Exness execution. |

Moskowitz, Ooi and Pedersen [2] and Moreira and Muir [3] are contextual
research references, not claimed empirical foundations for this exact
implementation. This document reports no new study results or performance
measurements. Risk/reward geometry alone does not demonstrate profitability.

## 9. Documentation reconciliation

Source inspection found the following documentation issues, without requiring
any strategy or code changes:

- Some status text still described fresh chart/adapter integration and the
  dashboard/signals as unavailable. README and the architecture status text
  now distinguish the implemented informational MVP from historical-only
  milestone descriptions and future model evaluation.
- Existing short ATR descriptions matched the code. This document adds exact
  initialization, bounded-history effects, units, numeric guards and HOLD
  behavior rather than replacing the implemented method.
- The short strategy overview lacked the full volatility definition and the
  distinction between seven required features and four directional inputs.
  It did not establish that the threshold was a z-score or research-calibrated.
- Earlier QNT/PQTA model and design documents describe separate historical
  research scopes. They are not a description of ML running inside this MVP
  and have not been rewritten by this documentation task.

## 10. References

Bibliographic details and linked source descriptions were checked on
2026-10-25. No unverified DOI, page-specific Wilder attribution or empirical
result is supplied.

1. **Wilder, J. Welles, Jr. (1978).** *New Concepts in Technical Trading
   Systems*. Greensboro, North Carolina: Trend Research.
   ISBN 0-89459-027-8 / 978-0-89459-027-6.
   [National Agricultural Library catalog record via FAO AGRIS](https://agris.fao.org/search/en/providers/122535/records/65ddeef14c5aef494fd794ab).
   The title, author, year, publisher and ISBN were verified bibliographically;
   the complete original book text was not reviewed in this task. Listed as
   classical background, not evidence for the project's parameter choices.

2. **Moskowitz, Tobias J., Yao Hua Ooi, and Lasse Heje Pedersen (2012).**
   “Time series momentum.” *Journal of Financial Economics*, **104**(2),
   228–250. [DOI: 10.1016/j.jfineco.2011.11.003](https://doi.org/10.1016/j.jfineco.2011.11.003).
   [Author-hosted published article](https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf);
   [author's publication listing](https://faculty.som.yale.edu/tobymoskowitz/research/).
   This is longer-horizon futures/forwards research, not a validation study of
   this BTC/USDT 1H strategy.

3. **Moreira, Alan, and Tyler Muir (2017).** “Volatility-Managed Portfolios.”
   *The Journal of Finance*, **72**(4), 1611–1644.
   [DOI: 10.1111/jofi.12513](https://doi.org/10.1111/jofi.12513).
   [American Finance Association issue record](https://afajof.org/issue/volume-72-issue-4/);
   [author-hosted article text](https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf).
   The issue record verifies final volume/pages; the author-hosted PDF has a
   prepagination header. Its monthly inverse-realized-variance exposure
   approach is not implemented here and does not establish our threshold or
   ATR multipliers.

4. **TradingView.** “Average True Range (ATR).” Official indicator
   documentation, accessed 2026-10-25.
   [Calculation and default RMA description](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/).
   Technical convention reference for true range/RMA, not peer-reviewed
   performance evidence or proof of bit-for-bit agreement with this app's
   bounded initialization.
