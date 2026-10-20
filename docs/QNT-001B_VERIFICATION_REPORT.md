# QNT-001B Binance Historical Archive Verification

Verified on 2026-10-20 UTC against Binance Public Historical Data. This is a
read-only comparison with the existing canonical Silver Parquet files; no
Bronze or Silver data was changed, and no gap filling was performed.

## Sources and local provenance

Binance [documents](https://github.com/binance/binance-public-data/blob/master/README.md)
monthly Spot kline ZIPs, their `/api/v3/klines` origin, and companion
`.CHECKSUM` files. All files below use the Spot `1h` interval. The precise
source URL, archive and checksum retrieval timestamps, archive filename,
symbol, covered month, SHA-256 value, and validation result for **each** file
are in the ignored local artifact `data/verification/qnt-001b/verification.json`.
The timestamps reflect local file creation on retrieval, not when Binance
originally published the files. The 18 ZIPs and their 18 checksum companions
are retained in `data/verification/qnt-001b/archives/`; Git ignores all of
`data/verification/`.

| Covered month | BTCUSDT archive | ETHUSDT archive | SOLUSDT archive | SHA-256 |
| --- | --- | --- | --- | --- |
| 2021-02 | [BTCUSDT-1h-2021-02.zip](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2021-02.zip) | [ETHUSDT-1h-2021-02.zip](https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2021-02.zip) | [SOLUSDT-1h-2021-02.zip](https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1h/SOLUSDT-1h-2021-02.zip) | 3/3 verified |
| 2021-03 | [BTCUSDT-1h-2021-03.zip](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2021-03.zip) | [ETHUSDT-1h-2021-03.zip](https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2021-03.zip) | [SOLUSDT-1h-2021-03.zip](https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1h/SOLUSDT-1h-2021-03.zip) | 3/3 verified |
| 2021-04 | [BTCUSDT-1h-2021-04.zip](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2021-04.zip) | [ETHUSDT-1h-2021-04.zip](https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2021-04.zip) | [SOLUSDT-1h-2021-04.zip](https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1h/SOLUSDT-1h-2021-04.zip) | 3/3 verified |
| 2021-08 | [BTCUSDT-1h-2021-08.zip](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2021-08.zip) | [ETHUSDT-1h-2021-08.zip](https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2021-08.zip) | [SOLUSDT-1h-2021-08.zip](https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1h/SOLUSDT-1h-2021-08.zip) | 3/3 verified |
| 2021-09 | [BTCUSDT-1h-2021-09.zip](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2021-09.zip) | [ETHUSDT-1h-2021-09.zip](https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2021-09.zip) | [SOLUSDT-1h-2021-09.zip](https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1h/SOLUSDT-1h-2021-09.zip) | 3/3 verified |
| 2023-03 | [BTCUSDT-1h-2023-03.zip](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2023-03.zip) | [ETHUSDT-1h-2023-03.zip](https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2023-03.zip) | [SOLUSDT-1h-2023-03.zip](https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1h/SOLUSDT-1h-2023-03.zip) | 3/3 verified |

All 18 published `.CHECKSUM` digests match their ZIP bytes. ZIP member names,
CRC, CSV shape, UTC hour alignment, month membership, unique candle opens,
OHLCV consistency, and close-time bounds also passed. The archives contain
12,990 rows in total: 4,330 for each symbol.

## Gap classification

`A` means **absent from a checksum-verified archive**. Every listed hour is
also absent from local Silver; none is classified as archive unavailable or
verification failed. The archive contains the observed hours immediately
before and after each of the seven gap periods for all three symbols, and
their OHLCV values agree with Silver. For adjacent missing hours, the
immediate neighbor is itself absent; the comparison uses the observed period
boundaries rather than treating those interior neighbors as verified candles.

| Missing candle open (UTC) | BTC/USDT | ETH/USDT | SOL/USDT |
| --- | --- | --- | --- |
| 2021-02-11 04:00 | A | A | A |
| 2021-03-06 02:00 | A | A | A |
| 2021-04-20 02:00 | A | A | A |
| 2021-04-20 03:00 | A | A | A |
| 2021-04-25 05:00 | A | A | A |
| 2021-04-25 06:00 | A | A | A |
| 2021-04-25 07:00 | A | A | A |
| 2021-08-13 02:00 | A | A | A |
| 2021-08-13 03:00 | A | A | A |
| 2021-08-13 04:00 | A | A | A |
| 2021-08-13 05:00 | A | A | A |
| 2021-09-29 07:00 | A | A | A |
| 2021-09-29 08:00 | A | A | A |
| 2023-03-24 13:00 | A | A | A |

Across the six months, every archive timestamp has a matching Silver key and
vice versa. Of 12,990 overlapping rows, 12,987 have identical OHLCV. The
three exceptions are all at **2021-04-23 01:00 UTC**, outside the requested
gaps. Open, high, and low agree; close and base-asset volume differ:

| Symbol | Archive close / volume | Silver close / volume |
| --- | --- | --- |
| BTC/USDT | 51080.59 / 11667.632162 | 51048.59 / 11815.248082 |
| ETH/USDT | 2325.82 / 187368.61418 | 2321.44 / 188766.41365 |
| SOL/USDT | 37.4715 / 1123737.3 | 37.4654 / 1131056.29 |

The archives also contain 12 rows (four per symbol) whose recorded close
times precede the usual `open + 1 hour - 1 ms` boundary. All four timestamps
per symbol are retained in local Silver and their OHLCV matches the archive:

| Candle open (UTC) | Recorded close-time observation |
| --- | --- |
| 2021-02-11 03:00 | 03:40:54.773–03:40:57.968 UTC across symbols |
| 2021-04-25 04:00 | 04:00:58.146–04:01:01.539 UTC across symbols |
| 2021-08-13 01:00 | 01:59:59.000 UTC for all symbols (999 ms early) |
| 2023-03-24 12:00 | 12:39:41.646–12:39:46.948 UTC across symbols |

The exact per-symbol close times are in the local verification artifact. These
rows require a separate downstream data-quality decision; matching OHLCV
does not prove that each row represents a full uninterrupted hour.

## Interpretation, limitations, and next actions

- The 14 hours are absent from both the previously queried Binance Spot REST
  endpoint and the retrieved Binance public monthly archives. This supports
  **archive-confirmed absence**, not an inferred exchange outage or a
  replacement candle. The current per-symbol availability starts remain
  unverified, so the QNT-001 coverage policy should not automatically be
  changed to claim verified listing dates or historical completeness.
- The April 23 OHLCV differences could reflect a source revision or another
  data discrepancy; this comparison does not establish the cause. Binance's
  [public-data documentation](https://github.com/binance/binance-public-data/blob/master/README.md#updates)
  notes that archives can be updated. Preserve both observations and review
  provenance before deciding which, if either, is canonical.
- Review how shortened archive close times should be represented and whether
  those 12 Silver rows should be excluded from any future research using only
  complete hourly candles. This task does not alter them.
- Retain the downloaded archives and checksum artifacts as a retrieval-time
  snapshot. Future archive checks should compare hashes, because published
  archive contents can change. No other months or providers were checked.

## Validation of this verification run

- The three new offline archive-parser tests passed; Ruff passed for the
  repository. All 18 published SHA-256 checksums passed independently with
  `shasum -a 256 -c` as well as in the verifier.
- The six Bronze/Silver Parquet SHA-256 hashes were identical before and
  after this task. The archive files and generated verification JSON are
  ignored by Git; no commit or push was made during the initial verification.
- A full virtual-environment pytest run was attempted but interrupted while
  loading a local dependency binary, before the suite completed. It is not
  counted as a passing full-suite run. The new targeted tests ran with the
  available system Python and DuckDB installation.

## QNT-001C: data-integrity follow-up (2026-10-20 UTC)

This follow-up made read-only, bounded public Binance Spot
[`GET /api/v3/klines`](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klines)
requests. For the disputed hour, the window was `[2021-04-23 00:00,
2021-04-23 04:00)` UTC (`limit=4`) for
[BTCUSDT](https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime=1619136000000&endTime=1619150399999&limit=4),
[ETHUSDT](https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime=1619136000000&endTime=1619150399999&limit=4),
and [SOLUSDT](https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1h&startTime=1619136000000&endTime=1619150399999&limit=4).
The raw responses, retrieved at 14:55:04–14:55:05 UTC, remain only under
`data/verification/qnt-001c/rest/`. Twelve additional single-candle requests
for the close-time anomalies were retrieved at 14:55:54–14:55:56 UTC and are
stored in the same ignored directory. These are Binance observations at the
retrieval time, not proof of the values available at the historical time.

### Exact 2021-04-23 01:00 UTC OHLCV comparison

| Symbol | Source | Open | High | Low | Close | Base volume |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USDT | REST and Silver | 51524.76 | 51725.74 | 49722.22 | 51048.59 | 11815.248082 |
| BTC/USDT | Verified archive | 51524.76 | 51725.74 | 49722.22 | 51080.59 | 11667.632162 |
| ETH/USDT | REST and Silver | 2373.86 | 2392.59 | 2250.00 | 2321.44 | 188766.413650 |
| ETH/USDT | Verified archive | 2373.86 | 2392.59 | 2250.00 | 2325.82 | 187368.614180 |
| SOL/USDT | REST and Silver | 37.5946 | 38.4000 | 35.0000 | 37.4654 | 1131056.29 |
| SOL/USDT | Verified archive | 37.5946 | 38.4000 | 35.0000 | 37.4715 | 1123737.30 |

Absolute difference is `|REST − archive|`; relative difference is that
absolute value divided by `|archive|`, multiplied by 100. Silver equals REST
for all five fields at the displayed precision. Only **close and volume**
differ; REST/Silver close is lower and volume is higher for all three symbols.

| Symbol | Δ open | Δ high | Δ low | Δ close | Δ volume | Relative Δ close | Relative Δ volume |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USDT | 0 | 0 | 0 | 32.000000 | 147.615920 | 0.062646% | 1.265175% |
| ETH/USDT | 0 | 0 | 0 | 4.380000 | 1397.799470 | 0.188321% | 0.746016% |
| SOL/USDT | 0 | 0 | 0 | 0.006100 | 7318.990000 | 0.016279% | 0.651308% |

Relative differences for open, high, and low are 0% for every symbol; the
REST-to-Silver absolute and relative differences are 0 for all five fields.
The disputed candle has the normal close timestamp `01:59:59.999` UTC in
both REST and archive. The immediate neighbors at 00:00 and 02:00 UTC, plus
03:00 UTC, are present and match across all three sources for **all five**
OHLCV fields. For a compact check, their close and volume are:

| Symbol | 00:00 close / volume | 02:00 close / volume |
| --- | --- | --- |
| BTC/USDT | 51524.09 / 5265.798449 | 49999.99 / 15482.244353 |
| ETH/USDT | 2373.86 / 109457.107060 | 2250.58 / 302372.460060 |
| SOL/USDT | 37.5946 / 1360411.79 | 36.8890 / 1157021.21 |

### Exact shortened close times

For every row below, archive, current REST, and Silver **OHLCV agree**; REST
also reports the same shortened close timestamp as the archive. Silver does
not store source close time, so its agreement is OHLCV-only. The difference is
`expected close − recorded close` in milliseconds. Every row immediately
precedes the indicated known gap. This is an association, not evidence of an
exchange outage or its cause.

| Symbol | Open (UTC) | Archive and REST close (UTC) | Expected close (UTC) | Early by ms | Next known gap begins (UTC) |
| --- | --- | --- | --- | ---: | --- |
| BTC/USDT | 2021-02-11 03:00 | 03:40:54.773 | 03:59:59.999 | 1,145,226 | 2021-02-11 04:00 |
| ETH/USDT | 2021-02-11 03:00 | 03:40:55.829 | 03:59:59.999 | 1,144,170 | 2021-02-11 04:00 |
| SOL/USDT | 2021-02-11 03:00 | 03:40:57.968 | 03:59:59.999 | 1,142,031 | 2021-02-11 04:00 |
| BTC/USDT | 2021-04-25 04:00 | 04:00:58.146 | 04:59:59.999 | 3,541,853 | 2021-04-25 05:00 |
| ETH/USDT | 2021-04-25 04:00 | 04:00:59.271 | 04:59:59.999 | 3,540,728 | 2021-04-25 05:00 |
| SOL/USDT | 2021-04-25 04:00 | 04:01:01.539 | 04:59:59.999 | 3,538,460 | 2021-04-25 05:00 |
| BTC/USDT | 2021-08-13 01:00 | 01:59:59.000 | 01:59:59.999 | 999 | 2021-08-13 02:00 |
| ETH/USDT | 2021-08-13 01:00 | 01:59:59.000 | 01:59:59.999 | 999 | 2021-08-13 02:00 |
| SOL/USDT | 2021-08-13 01:00 | 01:59:59.000 | 01:59:59.999 | 999 | 2021-08-13 02:00 |
| BTC/USDT | 2023-03-24 12:00 | 12:39:41.646 | 12:59:59.999 | 1,218,353 | 2023-03-24 13:00 |
| ETH/USDT | 2023-03-24 12:00 | 12:39:43.061 | 12:59:59.999 | 1,216,938 | 2023-03-24 13:00 |
| SOL/USDT | 2023-03-24 12:00 | 12:39:46.948 | 12:59:59.999 | 1,213,051 | 2023-03-24 13:00 |

The August rows are 999 ms short; the other nine rows end substantially
earlier. The close-time field alone cannot determine why this happened or
whether the 999 ms deviation reflects timestamp precision rather than a
materially shortened trading interval. Four of the seven known gap periods
have these immediately preceding anomalies; three do not.

### Regression-test diagnosis and handling recommendation

- A direct `.venv` DuckDB import completed in 0.126 seconds after its binary
  became locally available. A direct Polars import exceeded a 20-second
  timeout. Import timing showed individual Polars modules taking roughly
  1–1.5 seconds, and macOS marked many installed Polars files
  `hidden,compressed,dataless` (`304/434` before the probes, `287/434` after).
  The evidence points to on-demand materialization of offloaded environment
  files, not a test assertion or trading-code failure; the precise external
  storage/service behavior was not independently verified.
- Bounded `.venv` `pytest --collect-only -q` timed out after 45 seconds with
  no completed collection result. Bounded full `.venv` `pytest -q` timed out
  after 90 seconds with no test result. The issue occurs during dependency
  import/test collection, **before test execution**. Neither timeout is a
  passing full-suite result. The three targeted offline archive tests passed
  in the project `.venv` (`3 passed in 0.11s`); Ruff and both Git diff checks
  passed.
- No dependency was upgraded or replaced. At that stage, the next action was
  to make existing environment files locally available and rerun the **full**
  suite; that action and its result are recorded in the closure below. Owner
  approval remains required before rebuilding or replacing the environment.
- For EDA, retain explicit masks for all 14 absent hours, flag the 12
  shortened-close rows and the three archive/REST discrepancies, and avoid
  treating them as ordinary complete, reconciled hourly observations. Limited
  descriptive inspection is possible with these caveats; unrestricted
  feature, signal, or backtest use is **not ready**. No Silver rewrite or
  synthetic gap fill is authorized here.

## QNT-001 verification closure (2026-10-20 UTC)

The earlier timeout findings above describe the state **before** local file
materialization. The project `.venv/bin/python` is a symlink to the existing
Anaconda Python 3.12 installation and uses `.venv/lib/python3.12/site-packages`.
Many installed package files had nonzero logical sizes but zero allocated
blocks and macOS `dataless` flags. Reading one such Polars file caused it to
become locally available (zero to 208 allocated blocks) without changing its
contents. A bounded, read-only warm-up then accessed 288 offloaded Polars and
runtime files and 1,355 offloaded CCXT files, with no read errors. No package
was installed, upgraded, downgraded, replaced, or removed; `.venv` was not
recreated. The specific external file-storage mechanism remains unverified.

After the Polars warm-up, a direct Polars import completed in 0.24 seconds.
The first full-suite retry still timed out after 180 seconds during collection;
a separate CCXT import timed out after 45 seconds. After the CCXT warm-up, a
direct CCXT import completed in 0.40 seconds and the fresh full test suite
completed: **36 passed in 17.16 seconds** using
`PYTHONPATH=src .venv/bin/python -m pytest -q`. A bare `.venv/bin/pytest -q`
then collected promptly but failed with `ModuleNotFoundError: quant`, because
the `src` package was not installed in this environment. Adding pytest's
`pythonpath = ["src"]` setting to `pyproject.toml` resolved this without a
package installation: the requested bare command completed with **36 passed
in 0.66 seconds**. Ruff and Git diff checks passed. The prior timeout was
an environment-availability issue, while the bare-command failure was a
separate test-path configuration issue. A future recurrence should be
diagnosed without reinstalling dependencies or deleting the environment
without owner approval.

All 18 checksum-verified archives, 14 absent hourly candles per symbol, three
April 23 REST/archive OHLCV discrepancies, and 12 shortened-close observations
remain findings, not corrections. Root causes of the market-data anomalies are
unknown. Bronze and Silver remain unchanged; all archive, checksum, REST, and
verification JSON artifacts remain ignored local files. BTC/USDT is the first
research-phase asset; existing ETH/USDT and SOL/USDT datasets are preserved.
Future descriptive EDA should carry explicit gap and anomaly flags and source
provenance, with no synthetic filling or assumption that the flagged candles
represent complete, reconciled hourly observations.
