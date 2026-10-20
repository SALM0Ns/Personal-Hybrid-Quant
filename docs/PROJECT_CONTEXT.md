# Project Context

## Confirmed requirements

- **Project:** Personal Hybrid Quant Trading System.
- **Approach:** hybrid statistical and machine-learning research.
- **Assets:** stocks, ETFs, foreign exchange, and crypto assets.
- **Primary research timeframe:** 1-hour (`1H`) candles.
- **Trading mode:** semi-automated.
- **Signal vocabulary:** `BUY`, `SELL`, `HOLD`, and `NO SIGNAL`.
- **Execution:** manual only.
- **Initial development focus:** historical market-data engineering.

## Objective

Build a maintainable research foundation that can produce validated historical
datasets for multi-asset quantitative analysis without compromising temporal
integrity or introducing automated execution.

## Current scope

This initialization establishes documentation, package boundaries, data-layer
directories, dependency declarations, linting, and smoke tests.

## Out of scope

- Market-data ingestion or downloads.
- Trading strategy implementation.
- ML-model training.
- Broker-account connectivity.
- Automated order execution or live-trading functionality.

## Operating limitations

All timestamps must be timezone-aware UTC. Research and downstream signals must
exclude incomplete candles and prevent look-ahead bias or data leakage. Data
must be validated before use.
