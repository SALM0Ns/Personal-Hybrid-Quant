# Decisions

## Confirmed decisions

| Decision | Value |
| --- | --- |
| Quantitative approach | Hybrid Quant: statistical plus machine learning |
| Asset coverage | Multi-Asset: stocks, ETFs, forex, crypto |
| Operating mode | Semi-Automated |
| Primary timeframe | 1H |
| Trade execution | Manual only |
| Initial market | Crypto Spot |
| Initial provider | Binance via CCXT |
| Historical storage and query | Parquet + DuckDB |
| Initial instruments | BTC/USDT, ETH/USDT, SOL/USDT |
| Historical start | 2021-01-01 00:00 UTC |
| Historical end | Latest fully closed candle available at execution time |
| Coverage evidence policy | First returned API candle does not establish listing date; per-symbol availability starts require documented evidence |

## Proposals awaiting approval

| Proposal | Rationale |
| --- | --- |
| LightGBM / XGBoost | Candidate model families for later research. |
| Streamlit | Candidate research/dashboard interface. |

## Decision protocol

Confirmed decisions constrain implementation. Proposals are not authorization to
implement: record project-owner approval here before adopting or replacing them.
