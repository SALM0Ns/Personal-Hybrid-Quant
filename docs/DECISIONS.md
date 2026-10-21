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

### QNT-002B Feature Contract v1 — approved

| Decision | Approved policy |
| --- | --- |
| Availability evidence | `timestamp` is the UTC candle open and `candle_end_at` is one hour later; `available_at` is null without actual publication or observation evidence. Candle closure alone is not verified publication. |
| Anomaly provenance | Use a versioned manifest separate from Silver with timestamp, type, affected fields, source evidence, severity, review status, and version; do not change historical OHLCV. |
| Feature set | Exactly the seven features in `docs/QNT-002B_FEATURE_CONTRACT.md`; rolling volatility uses sample standard deviation (`ddof=1`) and multi-candle calculations require strict hourly continuity. |
| Formula alignment | `momentum_24h = C_t / C_(t-24h) - 1`; `momentum_168h = C_t / C_(t-168h) - 1`; `normalized_range_1h = (H_t - L_t) / C_t`. |
| Preserve and flag | Retain calculable research values and propagate quality metadata. `decision_eligible` is false for anomaly-affected rows or unknown availability; no silent repair or nulling of valid values. |
| Snapshot provenance | Record `feature_version`, `source_snapshot_sha256`, and `generated_at`; processing time is distinct from historical data availability. |

This design approval alone did not authorize implementation or a Gold build;
those proceeded under separate project-owner approvals. It does not authorize
backtesting, signals, models, or automated execution.

## QNT-002B closure and regression gate

| Item | Confirmed status or policy |
| --- | --- |
| Milestone | QNT-002B's seven-feature offline engine, versioned candidate anomaly manifest, synthetic validation, and local research-only Gold snapshot are complete. |
| Regression gate | A complete clean GitHub Actions pytest run and Ruff lint/format checks tied to the exact commit SHA are required for QNT-002B closure; a partial local test subset is not equivalent. |
| Verified evidence | GitHub Actions run `39575760185` succeeded for commit `aa5ac8d6511eb7ea9b26ef6df47308ab338ea6ef`: 84 tests passed, Ruff lint passed, and Ruff format passed. |
| Research boundary | The candidate manifest has unresolved evidence limitations and unknown historical publication availability. The pinned Gold snapshot has zero decision-eligible rows and is not approved for trading or backtesting. |
| Next stage | QNT-003 statistical research design only; this entry does not authorize implementation, signals, backtesting, or ML. |

## Proposals awaiting approval

| Proposal | Rationale |
| --- | --- |
| LightGBM / XGBoost | Candidate model families for later research. |
| Streamlit | Candidate research/dashboard interface. |

## Decision protocol

Confirmed decisions constrain implementation. Proposals are not authorization to
implement: record project-owner approval here before adopting or replacing them.
