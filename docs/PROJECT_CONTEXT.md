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

The first historical pipeline supports Binance Spot 1-hour OHLCV ingestion for
BTC/USDT, ETH/USDT, and SOL/USDT from 2021-01-01 UTC through the latest fully
closed candle. It stores provider observations in Bronze, validated canonical
candles in Silver, and a machine-readable coverage report.
Coverage reporting distinguishes explicitly verified instrument availability
from observed candles and unknown history. A first returned candle alone does
not establish when an instrument became available.

Later BTC/USDT work added a local historical chart, research-only Gold
features, and a separate PQTA-003C retrospective forecast-origin audit ledger.
PQTA-003C is Complete — Architecture Approved (Research Dataset Only).
The ledger contains a next-hour target for research accounting but no model,
forecast, score, signal, or verified historical decision-availability claim.
The application still displays `NO SIGNAL`; its chart reads Silver history.

## Out of scope

- Trading strategy implementation.
- ML-model training.
- Broker-account connectivity.
- Automated order execution or live-trading functionality.

## Operating limitations

All timestamps must be timezone-aware UTC. Research and downstream signals must
exclude incomplete candles and prevent look-ahead bias or data leakage. Data
must be validated before use.
