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

PQTA-003D-1 — Synthetic Evaluation Protocol Implemented; Architect Review Pending.
Pure protocol helpers and synthetic tests now enforce theoretical time,
completed historical-label admission, sample and history eligibility,
refit scheduling, and forecast/score state invariants. That milestone did
not implement models or execute Lane A.

PQTA-003D-2 — Synthetic Statistical Baselines Implemented; Architect Review Pending.
Zero Return, hourly expanding Mean, and midnight AR(1) now have separate
in-memory history, fit, and prediction interfaces with synthetic-only
validation. No historical evaluation, historical forecast, score ledger,
or predictive metric has been produced. Historical publication remains
unverified, Lane B is blocked, and trading/backtesting are not authorized.

PQTA-003D-3 — Synthetic Ridge Implemented; Architect Review Pending.
The seven-feature comparator, training-only scaler, daily refit contract,
and fixed-2024 alpha-selection components are implemented with Python's
standard library and tested on synthetic inputs only. No historical
evaluation has been run. The product goal is a practical personal 1H
crypto BUY/SELL/HOLD assistant for small-capital decision support; the
research contracts remain safeguards against leakage and overstated data
availability. Current application behavior remains `NO SIGNAL` and
execution remains manual. Signals, trading, and backtesting are not
authorized by this milestone.

PQTA-003D-4A accounting/reporting is Architect approved (synthetic only).
PQTA-003D-4B now implements a synthetic-only chronological coordinator;
Architect review is pending. It connects explicit in-memory feature/target
fixtures to the existing four model APIs and 4A accounting/reporting,
without historical readers, publication, dashboard integration or orders.
Historical labels enter only after theoretical closure; this does not
verify publication time or decision eligibility. No historical model
evaluation has run. Lane B, trading and backtesting remain blocked.

## Out of scope

- Trading strategy implementation.
- ML-model training.
- Broker-account connectivity.
- Automated order execution or live-trading functionality.

## Operating limitations

All timestamps must be timezone-aware UTC. Research and downstream signals must
exclude incomplete candles and prevent look-ahead bias or data leakage. Data
must be validated before use.
