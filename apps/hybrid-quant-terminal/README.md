# Hybrid Quant Terminal

A local, personal quantitative decision-support terminal using read-only Exness Demo MT5 market data, Python analytics and a React/TypeScript dashboard.

**Status: v1.0 Conditional — Limited Demo Use.** The application does not place orders or guarantee profitability. Broker timing, costs, execution and real-money readiness remain unverified. The v1.0 label describes acceptance status; the current package manifests independently declare their own versions.

## Capabilities

- **Market data:** read-only MT5 completed-candle file handoff for EURUSDm and XAUUSDm on M15, H1 and H4; manifests, SHA-256 checks, incremental checkpoint and feed-health reporting. Broker-clock timezone, source authentication and complete coverage remain unverified.
- **Analytics:** EMA, ATR, ADX, confirmed swings, support/resistance and Double Top/Bottom patterns. BUY/SELL are analytical directions; neutral describes trend context; WAIT denotes unavailable or blocked action. Entry, stop and target are changing reference levels, not orders.
- **Broker risk:** read-only specification observations, limited native hypothetical comparisons and an illustrative risk-budget input. Actual position sizing, monetary reward/risk and margin remain unavailable when required evidence is unverified. Fixture-only gross risk calculations are not broker execution. Unknown costs are not zero.
- **Dashboard and reliability:** TradingView Lightweight Charts, six feed views, polling, diagnostics, a localhost launcher, cooperative single-consumer locking, revision-ledger persistence and offline regression tests.

## Set up a new checkout

From the repository root, install the terminal's dependencies in its own environment. Python 3.12 or newer and Node.js with npm are required; this environment is separate from the original PQTA project.

```bash
cd apps/hybrid-quant-terminal
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cd frontend
npm ci
cd ..
```

These commands install dependencies from the configured package sources. The project also contains a platform-specific macOS arm64/Python 3.12 hash lock; see the [runtime workflow](docs/RUNTIME_CUTOVER_V04E.md) for its limits. A new checkout contains no market data, local runtime receipt or checkpoint. Installing dependencies does not configure a live MT5 bridge or establish broker authenticity.

The checkout's launcher intentionally fails closed without its own valid, locally provisioned runtime and cutover receipt. Do not fabricate a receipt, copy an existing checkpoint, or attach a second consumer to the active MT5 handoff. Any live migration or new runtime setup requires a separately reviewed procedure. The existing terminal has not been migrated to this checkout.

## Existing local terminal

With the existing Demo terminal and read-only bridge already running and local runtime configuration established, the owner's current Mac installation uses:

```bash
cd "$HOME/Developer/mt5-market-data"
.venv/bin/python tools/devctl.py start
```

Open [the local dashboard](http://127.0.0.1:5173/). Use `.venv/bin/python tools/devctl.py status` to inspect it and `.venv/bin/python tools/devctl.py stop` to stop it. See the [user guide](docs/USER_GUIDE_V1.md) and [runtime workflow](docs/RUNTIME_CUTOVER_V04E.md).

The existing ignored local cutover receipt supplies the registered MT5 handoff and historical-reference paths. Optional `MT5_BRIDGE_HANDOFF` and `MT5_HISTORICAL_ROOT` environment values must match that receipt. Missing, malformed or conflicting configuration fails closed; do not publish the receipt or invent a replacement checkpoint.

## Data and safety

The dashboard shows unverified historical bars as display-only. Do not interpret broker-clock timestamps as UTC, assume unknown gaps are market closures, or use historical snapshots as proven point-in-time trading inputs. A LIVE feed does not verify broker specifications or trading eligibility. No automatic trading or order endpoint is provided.

At the earlier acceptance check, one feed was LIVE and five were UNVERIFIED; two EURUSDm M15 revisions and 34 unclassified historical gap periods remained. These are past observations, not guarantees of current status.

## Documentation

- [Personal Demo guide](docs/USER_GUIDE_V1.md)
- [Release checklist](docs/V1_RELEASE_CHECKLIST.md) and [final acceptance](docs/V1_FINAL_ACCEPTANCE.md)
- [Read-only MT5 bridge](docs/MT5_LIVE_BRIDGE.md) and [broker-risk boundaries](docs/BROKER_RISK_V04.md)
- [Analytics contract](docs/ANALYTICS_CONTRACT_V05.md) and [runtime workflow](docs/RUNTIME_CUTOVER_V04E.md)

## Validation

Use the isolated project environment and disable the live bridge for offline tests:

```bash
mkdir -p .test-tmp
MT5_DISABLE_LIVE_BRIDGE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp .test-tmp/tests
.venv/bin/ruff check --no-cache src tests tools
.venv/bin/ruff format --check --no-cache src tests tools
.venv/bin/python -m pip check
cd frontend
npm test
npm run build
```

Tests use synthetic fixtures; passing them does not prove profitability or broker execution readiness.
