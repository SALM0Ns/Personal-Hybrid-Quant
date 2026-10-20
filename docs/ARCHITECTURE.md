# Architecture

## Proposed logical architecture

```text
Market Data
  → Bronze
  → Silver
  → Gold
  → Statistical / ML Research
  → Signal Generation
  → Risk Assessment
  → Dashboard
  → Manual Trading
```

| Component | Responsibility | Status |
| --- | --- | --- |
| Market Data | Obtain Binance Spot historical 1h OHLCV through CCXT. | Implemented for three symbols |
| Bronze | Preserve distinct raw source observations and retrieval metadata. | Implemented |
| Silver | Validate, normalize, deduplicate, and standardize UTC records. | Implemented for hourly crypto OHLCV |
| Gold | Create curated, analysis-ready datasets and features. | Proposed |
| Statistical / ML Research | Evaluate hypotheses and candidate models. | Proposed |
| Signal Generation | Produce `BUY`, `SELL`, `HOLD`, or `NO SIGNAL` outputs from complete data. | Proposed |
| Risk Assessment | Assess exposure and constraints before manual action. | Proposed |
| Dashboard | Present research, signals, and risk information. | Proposed |
| Manual Trading | Human reviews and manually executes any decision. | Confirmed boundary |

## Implemented components

Bronze and Silver use one Parquet snapshot per symbol under
`data/{bronze,silver}/binance/1h/BTC-USDT.parquet` (and similarly for ETH and
SOL). The symbol file is the partition and is atomically replaced after a
complete write. Bronze is committed before Silver, so a rerun can rebuild
Silver after an interrupted write. Reports are JSON under `data/reports/`.

Bronze retains timestamped change events and raw CCXT arrays; repeated
observations of the current value are deduplicated. If a provider changes a
candle and later restores an earlier value, all three events remain in Bronze.
Silver selects the valid observation with the latest `observed_at` per candle
key. A candle can enter Silver only when the provider was observed after that
candle closed; re-fetching an identical value after close creates a new event.
Re-fetch overlap is configurable. Coverage is checked against every expected
hour in the requested half-open interval `[start,end)`; the legacy inclusive
end CLI option remains available. The optional per-symbol availability file
requires an explicit UTC start and evidence. Without it, unobserved hours are
`unknown`, never inferred to be before listing from a first returned candle.
With a verified start, pre-availability hours and missing hours within verified
coverage are counted separately. All unobserved requested hours retain the
legacy `missing_candle_count`, and `ingestion_status` remains `incomplete`.
An empty provider page is not treated as proof of completion.
DuckDB can directly query Silver Parquet; no database service is required.

## Data boundaries

- Data moves forward through layers; downstream outputs must be reproducible
  from versioned code and recorded inputs.
- Silver and Gold datasets must use timezone-aware UTC timestamps.
- Completeness checks must prevent unfinished candles from entering signals.
- Validation precedes consumption by feature, strategy, model, and backtesting
  work.
- No architecture component may submit orders; the final step is manual trading.
