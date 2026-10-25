# Personal Hybrid Quant — Personal Quant Trading Assistant (PQTA)

## Project Overview

This repository contains a historical market-data and research foundation plus
the Personal Quant Trading Assistant (PQTA), a local **historical** candlestick
preview. The longer-term project is multi-asset and hybrid statistical/ML;
the implemented application is currently limited to Binance Spot BTC/USDT 1h
Silver data. It is not a live trading system.

## Project Objectives

- Build a practical personal 1H crypto BUY/SELL/HOLD assistant for
  small-capital decision support, with manual execution. Research protocols
  provide engineering safeguards against leakage; the current chart remains
  a historical preview displaying `NO SIGNAL`.
- Preserve and validate UTC hourly market history with explicit gap and source
  provenance.
- Support reproducible, gap-aware statistical research and a local visual
  inspection workflow without overstating point-in-time availability.
- Develop future analysis and decision support only after separate research,
  data-eligibility, and project-owner approvals. Any trading execution remains
  manual; automated exchange orders are outside the project boundary.

## Current Implementation Status

| Task ID | Task name | Current status | Brief description |
| --- | --- | --- | --- |
| QNT-000 | Repository foundation | Complete | Python package, documentation, and tests. |
| QNT-001 | Historical ingestion | Complete, with documented gaps | Binance Spot 1h BTC/USDT, ETH/USDT, and SOL/USDT Bronze/Silver pipeline. |
| QNT-001B | Archive verification | Complete | Published Binance monthly archives checked against local history. |
| QNT-001C | Anomaly investigation | Complete; causes unresolved | REST/archive discrepancy and shortened-close observations documented. |
| QNT-002A | Gap-aware EDA | Complete | Descriptive BTC/USDT research artifacts in local Gold. |
| QNT-002B | Feature engineering | Complete; research-only | Seven-feature engine, candidate anomaly manifest, and audited local Gold snapshot. |
| QNT-003A–D | Statistical research design | Complete; no evaluation run | Protocol `qnt-003d-design-v1` defines, but has not executed, baseline/Ridge comparisons. |
| PQTA-001 | Local candlestick preview | Complete and regression-tested | Read-only chart with `Analyze Now` refresh and constant `NO SIGNAL`. |
| PQTA-001A/B/C | Environment diagnosis and recovery | Complete and regression-verified | Dedicated arm64 Python 3.12 Conda environment; full 99-test regression passed. |
| PQTA-002A | Shared feature inspection | Complete; design only | Identified the QNT-002B engine as the single formula source and approved adapter boundaries. |
| PQTA-002B | Shared feature adapter | Complete; architecture-approved and pushed to main | Validates supplied in-memory BTC/USDT candles and reuses the offline engine; no fresh-data fetch or application integration. |
| PQTA-002 | Shared Feature Pipeline | Partial; not operational in the chart | Offline adapter complete; fresh-data sourcing, chart integration, and inference remain future work. |
| PQTA-003A | ML research and dataset inspection | Complete; read-only | Reviewed the governing protocol and local source/feature metadata; no target or evaluation was produced. |
| PQTA-003B | Research dataset and ML architecture | Complete — Architecture Approved (Design Only) | Proposed research-only origin, forecast, and score contracts; no implementation or evaluation. |
| PQTA-003C | Research-only origin dataset | Complete — Architecture Approved (Research Dataset Only) | Pinned Silver/Gold/manifest audit, next-hour target, split and quality masks, and immutable local origin ledger; no forecasts or evaluation. |
| PQTA-003D-1 | Synthetic evaluation protocol | Synthetic Evaluation Protocol Implemented; Architect Review Pending | Pure time, historical-label admission, sample/history, refit scheduling, and status checks; synthetic validation only. |
| PQTA-003D-2 | Statistical baseline components | Synthetic Statistical Baselines Implemented; Architect Review Pending | In-memory Zero Return, hourly Mean, and midnight AR(1); synthetic validation only, no historical evaluation. |
| PQTA-003D-3 | Seven-feature Ridge comparator | Synthetic Ridge Implemented; Architect Review Pending | Dependency-free augmented QR, training-only scaling, and fixed 2024 alpha-selection components; synthetic validation only. |
| PQTA-003D-4 | Model evaluation architecture and data contract | Reporting design approved; historical execution not authorized | Accounting/metric contracts and future provenance, GitHub summaries and read-only panel; historical runner/UI unimplemented. |
| PQTA-003D-4A | Synthetic evaluation accounting and reporting | Complete — Architect Approved (Synthetic Only) | Pure in-memory accounting, metrics, scored-set intersections and evidence-linked schema validation; synthetic fixtures only. |
| PQTA-003D-4B | Synthetic chronological evaluation coordinator | Implemented; Architect review pending | Connects supplied synthetic features/closed targets, existing models and 4A reporting; no historical reader or artifact publication. |
| PQTA-003D-5A | Read-only historical adapter and readiness audit | Implemented; Architect review pending | Verifies pinned source/artifact identities and preserves lossless historical features, targets and anomaly associations in memory; no execution bridge or historical fitting. |
| PQTA-003D-5B | Historical projection policy | Approved Design — Not Implemented | Policy `pqta-003d-5b-projection-v1`: target-endpoint-only Quality and strict fail-closed handling; policy approval alone grants no execution authorization. |
| PQTA-003D-5C | Historical projection compatibility layer | Implemented; Architect review pending | Source-bound, lossless in-memory compatibility plans and audit; unsupported required fields block the requested scope. No historical evaluation bridge. |
| PQTA-003D-5D | Unsupported anomaly representation architecture | Approved Design | Separate native metadata vocabulary over the lossless envelope; existing 4A and Strict Fail-Closed v1 contracts unchanged. |
| PQTA-003D-5E | Native historical anomaly representation | Implemented; Architect Review Pending | Audit-side literal/association preservation, authenticated source binding and versioned native representability audit; no historical execution or scoring interface. |
| PQTA-003D-6A | Native scoring/accounting types and validation | Implemented; awaiting Architect review | Immutable data-only records, strict validators, canonical serialization, and non-authoritative identities; no historical execution, scoring kernel, reconciliation kernel, or capability issuer. |
| PQTA-003D-6B | Synthetic native scoring kernel | Implemented; awaiting Architect review | Pure classification of supplied closed synthetic forecast/outcome pairs; exact parent binding and existing sample/reason rules; no historical execution or authority issuance. |
| PQTA-003 | ML Training & Evaluation | Synthetic comparator components implemented; historical evaluation pending | The origin ledger is not an approved point-in-time training dataset; historical execution requires separate authorization. |
| PQTA-004 | Signal Decision Engine | Planned; not operational | Future decision policy; the chart currently reports `NO SIGNAL`. |
| PQTA-005 | Chart Signal Integration | Planned; not operational | Future chart markers; none are displayed today. |
| PQTA-006 | On-Demand Fresh Analysis | Planned; not operational | Future fresh-data analysis; `Analyze Now` currently refreshes local history only. |
| PQTA-007 | Paper Trading | Deferred; not operational | Future simulation subject to separate approval; no orders are placed. |

The seven implemented BTC/USDT features are `log_return_1h`,
`volatility_24h`, `volatility_168h`, `momentum_24h`, `momentum_168h`,
`volume_change_1h`, and `normalized_range_1h`. See the
[feature contract](docs/QNT-002B_FEATURE_CONTRACT.md) and
[real-data audit](docs/QNT-002B_REAL_DATA_AUDIT.md).
The [QNT-003 final research design](docs/QNT-003D_FINAL_RESEARCH_DESIGN.md)
specifies zero-return, expanding-mean, and AR(1) baselines plus a seven-feature
Ridge comparator; it reports no predictive evaluation or performance.
The [PQTA-003D-4 evaluation contract](docs/MODEL_EVALUATION.md) describes
implemented synthetic-only coordination/accounting/reporting and the future historical
runner, immutable publication and read-only evaluation panel.
The [publication index](docs/evaluations/README.md) contains no results.
The [PQTA-003D-5A adapter contract](docs/PQTA-003D-5A_HISTORICAL_ADAPTER.md)
documents the separate read-only historical representation and readiness
audit. It does not relabel history as synthetic inputs or authorize evaluation.
The [approved 5B policy](docs/PQTA-003D-5B_HISTORICAL_PROJECTION_POLICY.md)
now has a separate 5C compatibility implementation in
`src/quant/research/historical_projection.py`. It authenticates pinned source
bindings separately from synthetic fixtures, retains lossless audit evidence,
and checks strict 4A representability without connecting history to a model,
runner or reporting engine. Implementation does not imply execution approval.
The native module implements the
[approved 5D representation design](docs/PQTA-003D-5D_UNSUPPORTED_ANOMALY_REPRESENTATION.md)
as audit-side metadata only; its exact API is documented in the
[5E implementation contract](docs/PQTA-003D-5E_IMPLEMENTATION_CONTRACT.md).
Native representability, legacy 4A compatibility,
source authentication, association resolution, evidence completeness and
temporal closure are independent dimensions, not one "clean" or executable
status. Native acceptance does not remove any legacy projection block.
Approved reporting boundaries are: training-history accounting only;
Ridge validation candidate tuning diagnostics only; test comparisons use
a frozen alpha. Research metrics are not trading confidence.
Historical Lane A evaluation still needs separate authorization; Lane B and
trading backtesting remain blocked. Inspecting a model will not select it
for trading, and `Analyze Now` continues refreshing local history only.

## System Architecture

Solid arrows below represent implemented historical/offline paths. Dotted
arrows and every component in the Planned group represent future work only.

```mermaid
flowchart LR
  subgraph implemented["Implemented — historical and local"]
    source["Binance Spot historical OHLCV"] --> bronze["Bronze Parquet"]
    bronze --> silver["Silver Parquet"]
    silver --> eda["QNT-002A EDA"] --> goldeda["Gold research artifacts"]
    silver --> features["QNT-002B seven-feature engine"] --> goldfeatures["Gold research-only features"]
    manifest["Versioned candidate anomaly manifest"] --> features
    silver --> origins["PQTA-003C research-only origin ledger"]
    goldfeatures --> origins
    manifest --> origins
    silver --> historicalaudit["PQTA-003D-5A read-only historical adapter; no execution bridge"]
    goldfeatures --> historicalaudit
    manifest --> historicalaudit
    origins --> historicalaudit
    historicalaudit --> projection["PQTA-003D-5C in-memory projection compatibility; no execution bridge"]
    projection -->|"source binding; no row filtering"| nativeaudit["PQTA-003D-5E native metadata audit; no forecast or scoring API"]
    baselines["PQTA-003D-2 synthetic baseline components; no historical execution"]
    ridge["PQTA-003D-3 synthetic Ridge comparator; no historical execution"]
    accounting["PQTA-003D-4A synthetic accounting/reporting; no historical execution"]
    synthetic["Explicit in-memory synthetic feature/target fixtures"] --> coordinator["PQTA-003D-4B chronological coordinator; synthetic only"]
    coordinator --> baselines
    coordinator --> ridge
    coordinator --> accounting
    supplied["Supplied in-memory BTC/USDT OHLCV; no fetch"] --> adapter["PQTA-002B shared validation adapter"] --> features
    silver --> preview["Read-only historical preview backend"]
    preview --> http["Loopback HTTP application"] --> chart["TradingView Lightweight Charts frontend"]
  end
  subgraph planned["Planned — not operational"]
    approveddata["Future separately approved training dataset; not current Gold or origin ledger"] -.-> training["ML training and evaluation"]
    training -.-> savedmodel["Saved model"]
    ondemand["Future on-demand fresh analysis"] -.-> fresh["Fresh market data"]
    fresh -.-> validation["Fresh-data validation"]
    validation -.-> sharedfeatures["Shared feature engineering"]
    sharedfeatures -.-> inference["ML inference"]
    savedmodel -.-> inference
    inference -.-> decisions["Signal decision engine"]
    decisions -.-> markers["BUY/SELL chart markers"]
    decisions -.-> paper["Paper trading"]
  end
  origins -.-> approveddata
  chart -.-> ondemand
```

The implemented Silver-to-feature-engine path is historical and offline. Its
current Gold snapshot is **not** the future approved training dataset. The
new adapter calls that same engine on explicitly supplied, validated in-memory
candles; it is not connected to the chart or an exchange. The planned training
path requires separate dataset eligibility and authorization;
only its saved model would feed future inference. The current `Analyze Now`
action rereads Silver and does not retrain or run any model.

PQTA-003C constructs a separate local, research-only origin ledger from the
pinned Silver, Gold, and candidate manifest. It carries retrospective
next-hour target and quality audit fields, not a forecast or an approved
training dataset. Outcome-side fields are excluded from its allowlisted
forecast-side view. No historical baseline, Ridge fit, prediction, score,
or backtest ran.
See the [dataset implementation report](docs/PQTA-003C_DATASET_IMPLEMENTATION.md).

The QNT research architecture proposes eventual statistical/ML research,
signals, risk assessment, a dashboard, and **manual** trading. The local chart
does not implement that future decision path. See [ARCHITECTURE.md](docs/ARCHITECTURE.md)
and [DECISIONS.md](docs/DECISIONS.md) before changing it.

The longer-term proposed flow continues from market data through Bronze,
Silver, Gold, research, signal generation, risk assessment, a dashboard, and
manual trading.

## Technology Stack and Versions

Versions below were checked in the local `pqta` environment and frontend
installation; unpinned package versions can change on a future install.

| Component or layer | Technology | Installed or declared version | Purpose | Implementation status |
| --- | --- | --- | --- | --- |
| Environment | Anaconda / Conda | 24.11.3 installed | Isolated local development environment | Used for `pqta` |
| Runtime | Python | 3.12.15 installed; `>=3.12` declared | Backend, research, tests | Implemented; native macOS arm64 |
| Market ingestion | CCXT | 4.5.89 installed; unpinned declaration | Historical Binance Spot API access | Implemented historical ingestion; **not used by the chart** |
| Tabular processing | Polars | 2.0.0 installed; unpinned declaration | Bronze/Silver, feature, and research-ledger transformations | Implemented in QNT and PQTA-003C workflows |
| Query and preview | DuckDB | 1.5.6 installed and pinned | Parquet queries and read-only chart window | Implemented |
| Storage format | Parquet | Format; no separate package version | Local Bronze/Silver/Gold files | Implemented |
| Validation dependency | Pandera | 0.34.1 installed; unpinned declaration | Declared validation library | Installed but not imported by current source |
| Timezone dependency | pytz | 2026.5 installed; unpinned declaration | Declared timezone library | Installed but not imported; code uses UTC from Python stdlib |
| Local HTTP | Python standard library | Python 3.12.15 | Loopback-only preview server | Implemented |
| Frontend tooling | Node.js / npm | 22.13.1 / 10.9.2 installed locally | Install pinned chart asset | Used for local frontend setup; not Python dependencies |
| Chart frontend | TradingView Lightweight Charts | 5.2.1 declared and installed locally | Interactive dark-theme candlesticks | Implemented |
| Tests / lint | pytest / Ruff | 9.1.1 / 0.17.1 installed | Regression tests / lint and format | Implemented |
| Build backend | Hatchling | Declared without version pin; not installed in `pqta` runtime | Editable package build in isolated build environment | Build-time only |
| Ridge comparator | Python standard library, Householder QR | Existing Python runtime; no added package | Seven-feature Ridge and frozen validation-alpha selection | Implemented and tested on synthetic inputs only |
| Future modeling | LightGBM / XGBoost proposals | Not declared or installed in `pqta` | Possible later predictive research | **Planned only; no model execution** |
| Statistical baselines | Python standard library, `math.fsum` | Existing Python runtime; no added package | Zero Return, Mean, and AR(1) | Implemented and tested on synthetic inputs only |
| Synthetic coordination | Python standard library | Python 3.12.15; no new dependency | Closure/admission events, existing model calls, daily state, accounting and report validation | PQTA-003D-4B implemented; synthetic-only, Architect review pending |
| Historical compatibility | Python standard library and existing Polars | Existing declared runtime/dependencies; no added package | Authenticated source binding, closure-gated projection plans and canonical in-memory compatibility audit | PQTA-003D-5C implemented; Architect review pending, no execution bridge |
| Native historical representation | Python standard library and existing source/manifest contracts | Python 3.12.15; no added package | Lossless literal/occurrence retention, source-linked identities and independent native audit dimensions | PQTA-003D-5E implemented; Architect Review Pending, audit-side only |
| Future interface proposal | Streamlit | Not declared or installed in `pqta` | Earlier dashboard proposal | **Planned only; current chart does not use it** |

The Python declarations are in [pyproject.toml](pyproject.toml); the chart
version is pinned in [web/package.json](web/package.json) and
[web/package-lock.json](web/package-lock.json). No ML library is required to
run the current chart.

## Data Architecture

- **Bronze:** local Parquet preserves source observations and revisions from
  historical ingestion.
- **Silver:** validated, deduplicated canonical hourly candles with UTC
  timestamps. The current chart reads only the existing BTC/USDT Silver file,
  never writing it or fetching fresh candles.
- **Gold:** QNT-002A descriptive EDA artifacts and the QNT-002B seven-feature
  BTC/USDT snapshot. Both are local research outputs, not chart inputs.
- **Research ledger:** PQTA-003C joins the pinned Silver and Gold timelines by
  exact UTC candle open, preserving all seven features and Gold eligibility.
  Its local `data/research/pqta-003/` origin ledger includes a next-hour
  target and audit masks but no forecast, score, fit, or model artifact.
- **Historical audit representation:** PQTA-003D-5A reads the pinned Silver,
  Gold, manifest and immutable origin build without changing them. It retains
  source row/timestamp identity, nullable features, target validity/reasons,
  and separate target-endpoint and feature-window anomaly records. Original
  `candle` and `unknown` fields remain verbatim; the association helper keeps
  unsupported associations `unresolved`, while the reader rejects schema drift.
  This is not the synthetic 4A `Outcome` contract.
- **Historical compatibility:** PQTA-003D-5C retains the lossless audit
  envelope while deriving target-endpoint-only 4A Quality for supported,
  closed rows. Feature-window records remain separate; `feature_complete`
  and `ar_lag_valid` remain explicit. Unsupported `candle`/`unknown` fields,
  unresolved associations and unknown anomaly types fail closed. A blocked
  required row blocks the declared scope, not a conveniently reduced universe.
  All readiness, PIT and decision-eligibility flags remain false.
- **Native anomaly metadata:** PQTA-003D-5E retains the existing lossless
  envelope, literal `candle`/`unknown`, separate endpoint/window/unresolved
  roles, original occurrence positions, duplicates, nulls and reason order.
  Source and full manifest references remain attached only to audit-side
  contexts and closed envelopes, never forecast-only plans. Unknown or
  contradictory semantic linkage remains explicit, not guessed or repaired.
- **Quality evidence:** coverage reports distinguish verified gaps from
  unknown coverage; the versioned candidate anomaly manifest remains separate
  from Silver and does not repair OHLCV values.

The shared adapter accepts strictly ordered BTC/USDT 1h candle opens, local
observation times, and finite OHLCV, plus explicit analysis and expected-latest
boundaries and a versioned anomaly manifest. It rejects duplicates, out-of-order
or incomplete candles, invalid values, and a stale latest candle. It returns
the existing typed seven-feature Gold schema **in memory**, with explicit
internal missing hours, null reasons, and 24/168-hour warm-up after gaps. It
does not write a dataset. Its `source_snapshot_sha256` hashes canonical
in-memory observation bytes, **not** Silver Parquet bytes; adapter rows identify
this provenance with `feature_version=qnt-002b-v1+pqta-canonical-ohlcv-v1`.
The canonical UTF-8 JSON includes schema ID, fixed market identity, ordered
field names, and ascending rows; UTC times use six fractional digits and `Z`,
while numeric values use exact big-endian IEEE-754 Float64 hex bytes. JSON
keys are sorted, separators compact, and a final newline is included.
An empty anomaly list never proves complete quality; without verified manifest
availability, feature values can be inspected but `available_at` stays null
and `decision_eligible` is false. The adapter also rejects observation or
quality evidence later than `analysis_as_of`; the expected latest candle must
be the latest full hour closed at that boundary. Candle closure alone is not
publication evidence. Future fresh-data evidence and inference require
separate approval.

Historical Gold has unknown publication availability (`available_at=null`),
unresolved anomaly evidence, and zero `decision_eligible` rows. It does **not**
establish verified point-in-time trading eligibility and is not approved for
trading or backtesting. Data and generated reports remain local and ignored by
Git. See [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md).

The read-only adapter verifies pinned bytes before Parquet inspection and
checks schema, feature order, timestamps, period membership and audit masks.
`audit_pinned_history(root)` loads only approved local sources;
`audit_frames(silver, gold, ledger, manifest, *, identity)` supports typed,
in-memory validation and synthetic tests. Both return audit structures in
memory, not evaluation output files. A `ready_for_architect_review` finding
is not execution approval: `execution_ready=false` remains explicit. Projection
into 4A `Quality`/`Outcome` is deferred pending reviewed field/association
policy and separate execution authorization. Source-byte authentication does
not authenticate the manifest's referenced anomaly evidence or establish PIT
availability; the synthetic runner's availability remains caller-attested.

The native representation reuses the source-bound receipt verifier rather
than trusting caller flags or plausible hashes. Its schema is
`pqta-historical-anomaly-representation-v1`, policy is
`pqta-003d-5d-representation-v1`, and serializer is
`pqta-003d-5e-canonical-v1`. Canonical UTF-8 JSON preserves source-array order,
duplicates, absent versus null fields and signed zero; it rejects NaN and
infinity. Separate `representation_spec_id`, `representation_build_id` and
`payload_sha256` identify logical source/scope policy, implementation build
and canonical payload bytes. Existing source IDs, the 5C serializer and
comparison timestamp digests are unchanged. No representation file is written.

## Application Workflow

1. Start the local server from the repository root. It reads a bounded window
   from the existing Silver BTC/USDT Parquet in read-only mode.
2. The backend checks OHLCV, UTC hour alignment, duplicates, candle closure,
   and gaps, then returns chronological chart candles or an explicit error.
3. The browser displays a dark, interactive 1h chart, latest candle time,
   source and quality status, and `HISTORICAL PREVIEW — NOT LIVE`.
4. `Analyze Now` rereads that **same local history** and refreshes the chart.
   It does not run a model, request Binance data, or generate a signal.

The signal status is always `NO SIGNAL`; no BUY/SELL markers or order route
exist.

## Repository Structure

| Path | Role |
| --- | --- |
| `src/quant/ingestion/`, `src/quant/validation/` | Historical collection, canonicalization, archive and coverage checks. |
| `src/quant/research/`, `src/quant/features/` | BTC/USDT descriptive EDA and offline feature calculations. |
| `src/quant/app/`, `web/` | Read-only Python preview server and browser chart. |
| `tests/`, `.github/workflows/` | Offline regression tests and CI workflow. |
| `configs/`, `docs/` | Availability/anomaly configuration and research decisions/reports. |
| `data/bronze/`, `data/silver/`, `data/gold/`, `data/research/` | Ignored local datasets and research artifacts. |
| `notebooks/`, `scripts/` | Exploratory workspace and bounded research utilities. |

`src/quant/strategies/`, `src/quant/models/`, and
`src/quant/backtesting/` contain placeholders, not implemented trading or
model pipelines. Notebooks are exploratory; production logic belongs in
`src/quant/`.

## Installation and Environment Setup

From the repository root on macOS arm64, with Anaconda and Node/npm available,
create the environment **once** on verified local storage outside cloud-offloaded
folders (skip creation if `pqta` already exists):

```bash
conda create -n pqta python=3.12 pip
eval "$(conda shell.zsh hook)"  # initialize this shell; no config change
conda activate pqta
python -m pip install -e '.[dev]'
npm ci --prefix web --ignore-scripts
```

The project pins DuckDB 1.5.6 for verified regression compatibility. The
existing `.venv` and temporary PQTA-001B environment do not need removal.
The frontend package is installed under ignored `web/node_modules/`; there is
no CDN dependency. See [web/README.md](web/README.md) for practical usage.

## Running the Application

With `pqta` active, run from the repository root:

```bash
python -m quant.app
```

Open <http://127.0.0.1:8765> and stop with Ctrl-C. The default source is
`data/silver/binance/1h/BTC-USDT.parquet`; the server binds only to loopback.
Use `--data-root`, `--port`, or `--limit` when needed; `--limit` defaults to 500
and is capped at 2,000 candles. The preview does not create or modify data.

## Testing and Validation

With `pqta` active, run from the repository root:

```bash
python -m pytest -q
ruff check .
ruff format --check .
python -m pip check
```

The PQTA-001 environment verification passed 15 PQTA tests, 84 QNT tests,
and all 99 tests together. The current PQTA-002B local regression passed 122
tests, including the new synthetic adapter tests; Ruff lint/format and
`pip check` passed. PQTA-002B was architecture-approved and pushed to main.
PQTA-003C added 44 synthetic dataset tests; the full local suite passed 166
tests, Ruff lint/format and `pip check` passed. Its pinned historical ledger
passed acceptance and an identical rerun reused the same artifact bytes.
PQTA-003D-1 has 120 synthetic protocol tests after Architect-review
hardening; the full local suite passed 286 tests, with Ruff lint/format
and `pip check` passing. That milestone implemented protocol helpers only.
PQTA-003D-2 has 117 synthetic baseline tests after Architect-review
hardening; the full local suite passed 403 tests. Baseline history
preparation, fitting, and prediction interfaces
are implemented and exercised on synthetic inputs only. No historical
forecasts, predictive metrics, or Lane A evaluation were produced; Lane B
remains blocked and trading/backtesting are not authorized.
PQTA-003D-3 has 89 synthetic Ridge tests after Architect-review remediation;
the full local suite passed 492 tests, Ruff lint/format, and `pip check`.
Ridge is synthetic-first until
separately authorized historical validation. No historical forecasts,
metrics, signals, or trading-readiness claims follow from these tests.
PQTA-003D-4A has 158 synthetic accounting/reporting tests after Architect
remediation (26 added to the initial 132); the full local suite passed
650 tests. Ruff lint/format, `pip check`, and whitespace checks passed.
The HTTP regression test requires localhost socket binding; the full
suite ran with loopback permission. Reporting distinguishes blocked
comparisons from zero emissions and empty scored sets. Anomaly evidence
remains unverified/partial; valid SHA-256 syntax does not authenticate
artifact bytes. No historical evaluation or persisted result was created.
PQTA-003D-4B adds a pure chronological runner and synthetic integration
tests, including guarded outcome reads, exact training cutoffs, daily
refit failure, frozen alpha, and paired intersections. It has no CLI,
dataset loader, writer, network path or connection to the chart.
After Architect remediation, its 47 synthetic tests passed; the full suite
passed **697 tests** in 12.58 seconds in `pqta`, with loopback permission
for the HTTP preview test. Non-Test Ridge replay is prohibited, and empty
universes produce no admission, update, emission or scoring events.
Ruff lint/format, `pip check`, and Git whitespace checks passed. Protected
dataset, manifest and immutable origin-artifact hashes remained unchanged.
PQTA-003D-5A adds 62 synthetic read-only adapter tests. The full local suite
passed **759 tests** in 12.65 seconds; Ruff lint/format, `pip check`, and Git
whitespace checks passed. These checks do not execute historical models or
establish trading readiness. Historical audit reports remain in memory only.
PQTA-003D-5C compatibility tests are synthetic and can be run with `pqta`
active using `python -m pytest -q tests/test_historical_projection.py`.
They exercise source binding, strict projection, temporal isolation and
deterministic serialization without historical fitting or evaluation.
The 5C acceptance run passed **57 projection tests**, **387 relevant research
regression tests**, and **816 full-suite tests** in the `pqta` environment.
The full-suite rerun required localhost permission for the existing HTTP test;
the sandboxed attempt had 815 passes and one socket-permission failure.
The read-only compatibility audit retained 50,845 origins: 49,692 compatible,
1,152 blocked and one audit-only. These are representation counts, not model
results or permission to execute a reduced historical evaluation.
PQTA-003D-5E adds synthetic verification of native representation, source
binding, closure non-access and canonical identities. Acceptance passed **112
new tests and the full 928-test suite**, plus Ruff lint/format and dependency
checks. A read-only full-origin scan found 50,844 natively represented origins
and one uninspected audit-only origin; the independent legacy counts above
remain unchanged. A separate 39-origin canonical anchor audit repeated
byte-for-byte. These are metadata findings, not model results or execution
approval; [method and limitations](docs/MODEL_EVALUATION.md#read-only-acceptance-findings)
include the initial bounded-audit timeout.
Tests use synthetic data and local fixtures; the HTTP test
binds a temporary localhost
port. The prior QNT-002B CI run passed its then-current 84-test suite; it did
not validate the later PQTA application. Existing Bronze, Silver, and Gold
files were not regenerated by the environment verification.

## Current Limitations

- This is a historical Silver preview, not fresh or live Binance data. Its
  displayed candles are not verified point-in-time trading inputs.
- Known historical gaps and source discrepancies remain documented and
  unresolved; the chart reports gaps rather than filling them.
- Gold and the PQTA-003C origin ledger are research-only; historical feature
  availability and decision eligibility are not established for trading or
  backtesting. The ledger's target and anomaly masks are retrospective audit
  fields, not a point-in-time-verified training sample.
- `Analyze Now` refreshes the preview only. No ML predictions, BUY/SELL/HOLD
  recommendations, chart markers, paper trades, brokerage connection, or
  automated order execution are implemented.
- QNT-003 specifies a research protocol, not predictive findings. Lane A
  evaluation needs separate approval; verified point-in-time Lane B remains
  blocked. No model performance or profitability claim is made.
- PQTA-003D-4B accepts only explicitly marked in-memory synthetic fixtures.
  Synthetic feature availability, target validity and feature provenance
  are caller-attested. `feature_open_t` alignment does not independently
  prove causal feature construction. The synthetic runner does not
  authenticate historical sources; separate 5A/5C read-only verification
  does not provide a historical execution bridge. Nominal closure is not
  publication time.
  Synthetic fits and metrics establish neither BTC predictability nor
  trading profitability and are not live-trading evidence; historical
  execution remains unauthorized. Frozen-alpha Ridge replay occurs only
  in Test, never training-history accounting or validation diagnostics.
- PQTA-003D-5C implements compatibility only under
  `pqta-003d-5b-projection-v1`. Unsupported required metadata blocks the whole
  requested projection scope; blocks are not model abstentions. Source-byte
  verification does not verify anomaly evidence or historical publication.
  Historical execution/reporting remain unauthorized, PIT unverified and
  decision eligibility false; no generated compatibility files are written.
- PQTA-003D-5E represents historical anomaly metadata; it is not an executable
  historical `Outcome`, scorer, forecast API or reporting bridge. Native
  representability does not establish legacy 4A compatibility, anomaly-evidence
  verification, numeric/model eligibility or PIT availability. Raw unresolved
  associations stay unresolved. Historical scoring/accounting/reporting still
  require separately reviewed interfaces and explicit execution authorization;
  `execution_ready`, `point_in_time_verified` and `decision_eligible` stay false.

## Development Roadmap

PQTA-001 is the implemented, regression-tested local chart foundation.
PQTA-002A inspected the architecture and PQTA-002B completed the offline
shared adapter. PQTA-003A completed read-only inspection; PQTA-003B has a
[research dataset and ML architecture design](docs/PQTA-003B_ML_ARCHITECTURE_DESIGN.md).
Its status remains Complete — Architecture Approved (Design Only). PQTA-003C
implemented its research-only origin ledger and next-hour target; no approved
training dataset, historical fit, historical forecast, or score has been produced. Later
integrations remain non-operational:

- **PQTA-002 — Shared Feature Pipeline:** the adapter reuses the existing
  engine; fresh-data sourcing and chart/inference integration are not built.
- **PQTA-003 — ML Training & Evaluation:** future training on an approved
  dataset, with a saved model for separately authorized inference.
- **PQTA-004 — Signal Decision Engine:** future policy for model outputs.
- **PQTA-005 — Chart Signal Integration:** future BUY/SELL marker display.
- **PQTA-006 — On-Demand Fresh Analysis:** future fresh-data analysis initiated
  by the user; today's button only reloads historical Silver.
- **PQTA-007 — Paper Trading:** deferred simulation, with no live orders.

The manual-only execution boundary remains in force; this roadmap authorizes
none of those components. QNT-003 statistical evaluation also requires
separate approval.

For each future PQTA task, update this README when architecture changes,
dependencies or their versions change, task status changes, or setup commands
change. Keep implemented and planned functionality distinct and verify claims
against the repository and installed environment.

## Historical OHLCV ingestion

Review planned requests without fetching or writing anything:

```bash
python -m quant.ingestion --symbols BTC/USDT ETH/USDT SOL/USDT --backfill --dry-run
```

Run the approved backfill from 2021-01-01 UTC to the latest fully closed hour:

```bash
python -m quant.ingestion --symbols BTC/USDT ETH/USDT SOL/USDT --backfill
```

Resume from the latest stored Silver candle, rechecking the preceding 24 hours:

```bash
python -m quant.ingestion --symbols BTC/USDT ETH/USDT SOL/USDT --incremental --overlap-hours 24
```

`--start`, `--end`, and `--end-exclusive` accept UTC ISO 8601 timestamps on
hour boundaries. The existing `--end` denotes an **inclusive candle open**;
`--end-exclusive` uses `[start,end)` and is mutually exclusive with `--end`.
The last included candle must be fully closed. Only `1h` is supported.
`--page-size` (1 to 1000, default 1000) bounds each provider call. Exit status
2 means at least one requested window contains gaps; status 1 means a
fetch or storage failure. A dry run prints the intended window and page count,
without creating an exchange client or writing files.

Raw revision events are kept in `data/bronze/binance/1h/`; canonical
valid records are in `data/silver/binance/1h/`. Quality reports appear in
`data/reports/binance/1h/`. All data and reports are ignored by Git. Run from
the repository root or set `--data-root` explicitly. Bronze retains revisions
and value reversions; Silver chooses the latest observed valid revision. Empty
API pages and missing hours are reported as incomplete coverage, with no
forward filling.
Expected, observed, and legacy `missing_candle_count` cover the requested
window. The report also gives `requested_end_exclusive`, first and last valid
Silver candles, `unobserved_timestamps`, `missing_timestamps`, and separate
counts/periods for verified
gaps, pre-availability, and unknown coverage. `missing_candle_count` retains
its original meaning of **all unobserved requested hours** for compatibility;
`missing_timestamps` lists only gaps within verified availability.
`ingestion_status` remains `incomplete` whenever requested hours are
unobserved; `coverage_status` explains whether the gap is verified missing,
unknown, or before verified availability.

The per-symbol [availability file](configs/availability.json) starts with no
verified dates. A first API candle is not treated as a listing date. To enter
a verified first available hourly candle, record its UTC hour and a traceable
source in `verified_start_utc` and `evidence`. If listing occurred partway
through an hour, use the first *fully available* hourly candle. Without this
evidence, unobserved hours are classified as unknown. If data precedes the
recorded start, the report flags an availability conflict. You can select an
alternate evidence file using `--availability-config`.

For a bounded seven-day example, ending at the completed 2026-10-20 UTC day
boundary, use:

```bash
python -m quant.ingestion --symbols BTC/USDT --backfill \
  --start 2026-10-13T00:00:00Z --end-exclusive 2026-10-20T00:00:00Z \
  --page-size 48
```

The report records actual fetched page and observation counts. Duplicate,
revision, and rejected counts cover stored Bronze observations for the symbol
(plus exact repeats seen in the current fetch); the other coverage counts are
for the requested window.

Inspect Silver locally with DuckDB:

Set the DuckDB session timezone to UTC when displaying timestamp values;
the Parquet timestamp column has UTC timezone semantics.

```bash
python -c "import duckdb; db=duckdb.connect(); db.execute(\"SET TimeZone='UTC'\"); print(db.execute(\"SELECT min(timestamp), max(timestamp), count(*) FROM 'data/silver/binance/1h/BTC-USDT.parquet'\").fetchall())"
```

Offline tests use mocked exchange responses:

```bash
python -m pytest
ruff check .
```
