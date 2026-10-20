# QNT-001 Historical Backfill Report

Executed 2026-10-20 UTC against Binance Spot through CCXT. The fixed requested
window for every symbol was `[2021-01-01 00:00, 2026-10-20 13:00)` UTC. The
last included hour was 2026-10-20 12:00 UTC, fully closed when execution began.
No alternate data source or gap filling was used.

| Symbol | First / last observed hour (UTC) | Expected | Silver | Bronze | Unobserved | Verified missing | Unknown | Pre-availability | Duplicates | Rejected | Conflicts | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| BTC/USDT | 2021-01-01 00:00 / 2026-10-20 12:00 | 50,845 | 50,831 | 50,831 | 14 | 0 | 14 | 0 | 14 | 0 | 0 | unknown |
| ETH/USDT | 2021-01-01 00:00 / 2026-10-20 12:00 | 50,845 | 50,831 | 50,831 | 14 | 0 | 14 | 0 | 14 | 0 | 0 | unknown |
| SOL/USDT | 2021-01-01 00:00 / 2026-10-20 12:00 | 50,845 | 50,831 | 50,831 | 14 | 0 | 14 | 0 | 14 | 0 | 0 | unknown |

Total stored: 152,493 canonical Silver candles and 152,493 Bronze observation
events. Each symbol used 51 bounded pages with a maximum of 1,000 candles per
request. The 14 duplicate observations in each fetch did not create duplicate
Silver keys. Independent JSON reports are in `data/reports/binance/1h/`.

## Exact unobserved candle opens

All three symbols have the same 14 unobserved UTC hours:

```text
2021-02-11 04:00
2021-03-06 02:00
2021-04-20 02:00, 03:00
2021-04-25 05:00, 06:00, 07:00
2021-08-13 02:00, 03:00, 04:00, 05:00
2021-09-29 07:00, 08:00
2023-03-24 13:00
```

Direct, bounded Binance rechecks of all seven gap periods for each symbol
returned zero candles inside those periods. The first returned row began at
the next available hour. The endpoint did not establish why these candles
are absent. They remain `unknown_coverage`, not proven pre-availability or
verified missing hours, because no independent availability start is recorded
for any symbol. The full 2021-to-2026 range is therefore **not complete**.

## Validation and preservation

- Polars read all six Parquet files. Bronze `observed_at` and Silver
  `timestamp`/`ingested_at` have UTC timezone types.
- Every Silver key `(exchange, symbol, timeframe, timestamp)` is unique.
  All timestamps align to the hour, precede the requested end, and were
  observed after their candle closed.
- All Silver OHLCV values are finite; prices are positive, volume is
  nonnegative, and OHLC relationships hold.
- DuckDB returned 50,831 rows and 50,831 distinct timestamps per symbol,
  from 2021-01-01 00:00 through 2026-10-20 12:00 UTC.
- The prior 168-candle BTC/USDT smoke window lost zero Silver keys, changed
  zero OHLCV values, and lost zero Bronze observations.
- Repeating the same three-symbol backfill fetched the same window and added
  zero Bronze events. All six Parquet SHA-256 hashes remained unchanged.
- Offline validation: 33 pytest tests passed; Ruff and `git diff --check`
  passed.

The JSON `missing_timestamps` field lists only gaps within *verified*
availability. Here it is empty because availability starts are unknown. The
14 exact absent hours are in each report's `unobserved_timestamps`; the legacy
`missing_candle_count` is 14. No listing date was inferred from the first
returned candle.
