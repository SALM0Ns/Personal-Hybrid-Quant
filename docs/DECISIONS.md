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
| Next stage at QNT-002B closure | QNT-003 statistical research design only; this historical entry did not authorize implementation, signals, backtesting, or ML. |

## QNT-003 research design closure — approved protocol only

| Item | Confirmed status or policy |
| --- | --- |
| Milestone and protocol | QNT-003A–D research design completed and owner-reviewed as `qnt-003d-design-v1`; `docs/QNT-003B_EVALUATION_PROTOCOL.md` is the proposed evaluation contract and `docs/QNT-003D_FINAL_RESEARCH_DESIGN.md` summarizes the audit resolutions. |
| Proposed comparison | Three statistical baselines—zero return, expanding historical mean, and AR(1)—and one Ridge comparator using exactly the seven existing BTC/USDT Gold features. These are design specifications, not executed models or findings. |
| Research lanes | Lane A contains separately reported valid-target and fixed-manifest retrospective samples; any statistical evaluation requires separate authorization. Lane B verified point-in-time research is blocked pending auditable historical availability and decision eligibility. |
| Execution boundary | No predictive evaluation has been performed. Trading backtesting remains blocked; this design approval does not authorize targets, model fitting, scoring, signals, or orders. |

## PQTA-003B architecture closure — design only

| Item | Confirmed status or policy |
| --- | --- |
| Milestone | Complete — Architecture Approved (Design Only). The Architect approved the research-only forecast-origin ledger, temporal boundaries, separate dataset/build/artifact identities, and proposed offline module boundaries documented in `docs/PQTA-003B_ML_ARCHITECTURE_DESIGN.md`. |
| Governing protocol | `qnt-003d-design-v1` remains unchanged. The architecture does not amend its target, splits, sample rules, methods, or scoring conventions. |
| Execution boundary | This approval does not authorize target construction, dataset publication, baseline execution, Ridge training or evaluation, dependency installation, Lane A or Lane B execution, backtesting, inference, signals, or trading. |

## PQTA-003C implementation record — research dataset only

The Project Owner separately authorized construction of the
`pqta-003b-origin-ledger-v1` retrospective origin ledger from the pinned
BTC/USDT Silver, Gold, and candidate-manifest inputs. The local acceptance
run and immutable artifacts are documented in
`docs/PQTA-003C_DATASET_IMPLEMENTATION.md`. This execution authorization
does not amend `qnt-003d-design-v1`, establish historical point-in-time
availability, or approve the ledger for model training, Lane A/B evaluation,
backtesting, inference, signals, or trading. No baseline or model was run.

### PQTA-003C final Architect approval

PQTA-003C research-only dataset implementation is Complete — Architecture
Approved (Research Dataset Only). The approved dataset contract is
`pqta-003b-origin-ledger-v1`, governed by `qnt-003d-design-v1`. Historical
point-in-time availability remains unverified. Lane A evaluation is not
authorized, and Lane B remains blocked. This approval grants no training,
forecasting, scoring, backtesting, signals, or trading authorization.

## PQTA-003D-1 synthetic protocol implementation record

PQTA-003D-1 — Synthetic Evaluation Protocol Implemented; Architect Review Pending.
The owner authorized pure protocol helpers and synthetic validation only,
preserving `qnt-003d-design-v1` and `pqta-003b-origin-ledger-v1`.
The implementation reuses the approved split and forecast-field contracts;
82 new synthetic tests and all 166 existing regression tests passed.
No models were implemented, forecasts generated, predictive metrics
calculated, or Lane A evaluation executed. Lane B remains blocked;
trading/backtesting and dependency installation are not authorized.

## PQTA-003D-2 synthetic baseline implementation record

PQTA-003D-2 — Synthetic Statistical Baselines Implemented; Architect Review Pending.
The owner authorized synthetic-first Zero Return, expanding Mean, and AR(1)
components under unchanged `qnt-003d-design-v1` and
`pqta-003b-origin-ledger-v1`. Existing protocol helpers govern label closure,
samples, 720-history minima, and midnight AR scheduling. The implementation
uses standard-library arithmetic and explicit abstention/failure results;
no dependency or statistical convention was changed. Synthetic testing
does not authorize historical execution, Lane A evaluation, predictive
scoring, Lane B, trading, or backtesting. Ridge remains unimplemented.

## Proposals awaiting approval

| Proposal | Rationale |
| --- | --- |
| LightGBM / XGBoost | Candidate model families for later research. |
| Streamlit | Candidate research/dashboard interface. |

## Decision protocol

Confirmed decisions constrain implementation. Proposals are not authorization to
implement: record project-owner approval here before adopting or replacing them.
