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
| Market Data | Obtain historical data from approved sources. | Proposed |
| Bronze | Preserve source-oriented, minimally altered records. | Proposed |
| Silver | Validate, normalize, deduplicate, and standardize UTC records. | Proposed |
| Gold | Create curated, analysis-ready datasets and features. | Proposed |
| Statistical / ML Research | Evaluate hypotheses and candidate models. | Proposed |
| Signal Generation | Produce `BUY`, `SELL`, `HOLD`, or `NO SIGNAL` outputs from complete data. | Proposed |
| Risk Assessment | Assess exposure and constraints before manual action. | Proposed |
| Dashboard | Present research, signals, and risk information. | Proposed |
| Manual Trading | Human reviews and manually executes any decision. | Confirmed boundary |

## Implemented components

Only repository boundaries are implemented: the `quant` package namespaces,
local Bronze/Silver/Gold data directories, documentation, and development
configuration. No operational data pipeline or research component exists yet.

## Data boundaries

- Data moves forward through layers; downstream outputs must be reproducible
  from versioned code and recorded inputs.
- Silver and Gold datasets must use timezone-aware UTC timestamps.
- Completeness checks must prevent unfinished candles from entering signals.
- Validation precedes consumption by feature, strategy, model, and backtesting
  work.
- No architecture component may submit orders; the final step is manual trading.
