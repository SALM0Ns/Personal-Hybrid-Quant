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
| Gold | Create curated, analysis-ready datasets and features. | BTC/USDT gap-aware EDA and research-only seven-feature snapshot implemented; other Gold work proposed |
| Statistical / ML Research | Evaluate hypotheses and candidate models. | Descriptive BTC/USDT EDA implemented; QNT-003 statistical evaluation designed but not executed; ML remains proposed |
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

QNT-002A adds a read-only BTC/USDT exploratory workflow. It derives a complete
hourly timeline with null OHLCV at gaps, continuity-valid returns, raw hourly
rolling volatility, and retrospective descriptive labels. Its local-only Gold
Parquet, aggregate tables, JSON, and SVG charts are under
`data/gold/qnt-002a/btc_usdt_1h/`. These are research artifacts, not trading
signals or changes to Bronze/Silver. The report is
`docs/QNT-002A_EDA_REPORT.md`.

QNT-002B reads the existing BTC/USDT Silver Parquet offline and constructs an
explicit UTC hourly Gold timeline. Missing hours remain null; the seven
contracted features require their exact source-candle dependencies and strict
continuity. A versioned candidate anomaly manifest under `configs/` is
separate from Silver and carries evidence for missing hours, shortened closes,
and the REST/archive discrepancy without correcting OHLCV. The local-only
feature snapshot is under `data/gold/qnt-002b/btc_usdt_1h/candidate_v1/`.
Each row records feature and manifest versions, source and manifest SHA-256
digests, and `generated_at` processing time. See the
`docs/QNT-002B_FEATURE_CONTRACT.md` and
`docs/QNT-002B_MANIFEST_AUDIT.md`.

`timestamp` is the UTC candle open and `candle_end_at` is its theoretical close,
not proof of exchange publication. Historical publication availability and
the candidate manifest's version availability remain unverified; the pinned
Gold snapshot therefore has null `available_at` and zero decision-eligible
rows. Anomaly-affected rows also fail the row-level eligibility policy. The
snapshot is for descriptive research, not trading signals or historical
backtesting. Its real-data findings are in
`docs/QNT-002B_REAL_DATA_AUDIT.md`.

`.github/workflows/python-tests.yml` runs the complete offline pytest suite
and Ruff lint/format checks on a clean GitHub Actions runner. Run
`39575760185` passed 84 tests and both Ruff checks for QNT-002B commit
`aa5ac8d6511eb7ea9b26ef6df47308ab338ea6ef`. CI validates the code's
regression behavior; it does not fetch market data, resolve source anomalies,
or establish historical point-in-time availability.

QNT-003 is a completed **research design**, not an implemented evaluation.
Protocol `qnt-003d-design-v1` defines the next-hour BTC/USDT target, three
statistical baselines (zero return, expanding mean, AR(1)), one seven-feature
Ridge comparator, chronological validation, and forecast/score accounting.
Its Lane A is retrospective and needs separate authorization before any
statistical evaluation. Lane B requires verified historical point-in-time
source, feature, and manifest availability and is currently blocked. Trading
backtesting remains blocked. No QNT-003 target, model, prediction, or metric
has been generated. See `docs/QNT-003D_FINAL_RESEARCH_DESIGN.md`.

## Data boundaries

- Data moves forward through layers; downstream outputs must be reproducible
  from versioned code and recorded inputs.
- Silver and Gold datasets must use timezone-aware UTC timestamps.
- Completeness checks must prevent unfinished candles from entering signals.
- Validation precedes consumption by feature, strategy, model, and backtesting
  work.
- No architecture component may submit orders; the final step is manual trading.
