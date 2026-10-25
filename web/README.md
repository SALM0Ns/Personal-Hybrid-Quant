# PQTA local BTC 1H dashboard

PQTA displays completed Binance BTC/USDT Spot candles and an explainable,
deterministic `BUY` / `SELL` / `HOLD` assessment. Binance Spot is an analysis
reference; it is not an Exness BTC CFD execution quote. Every signal is
informational. Execution is manual, and no broker login or order API is used.
Position sizing, margin, broker costs and order placement are disabled.
ATR-based entry/SL/TP values are Binance Spot reference estimates only, not
verified Exness CFD execution prices.
No Exness configuration is needed for this version.

## Install and start

From the repository root, use the existing `pqta` Conda environment as described
in the [root README](../README.md). Node/npm is needed for the locally served
TradingView dependency:

```bash
eval "$(conda shell.zsh hook)"
conda activate pqta
python -m pip install -e '.[dev]'  # omit if already installed
npm ci --prefix web --ignore-scripts
python -m quant.app
```

Open <http://127.0.0.1:8765>. Stop with Ctrl-C. The server binds only to
loopback; use `--port 8766` if necessary. `--limit` controls the historical
preview only, and `--data-root` locates that local snapshot. Recent requests
use 200 completed hours in memory.
The chart dependency is pinned in `web/package-lock.json` and served from
ignored `web/node_modules`; no CDN is required.

## Use the dashboard

- The initial local view is labeled **HISTORICAL PREVIEW — NOT LIVE** and
  displays `NO SIGNAL`. It reads the existing Silver snapshot without modifying
  it. **Historical preview** returns to that view.
- **Load Recent Data** requests recent completed BTC/USDT 1H reference candles.
  It refreshes the chart, quality status, latest candle and freshness without
  generating an assessment.
- **Analyze Now** requests fresh completed candles and runs the deterministic
  baseline. It displays the decision, reasons, feature values, ATR(14), market
  timestamp and expiry. BUY/SELL also show reference entry/SL/TP and a 1:2
  risk/reward ratio. It does not train ML or execute historical research models.
- A pending, failed, invalid, stale or expired assessment clears any previous
  `BUY`/`SELL` to `HOLD`. Inspect the stated reason and request fresh analysis
  when ready. Do not interpret a missing result as an order instruction.

The interface does not expose trade buttons, order sizes or affordability
claims. Use Exness Demo independently if you choose to place a manual trade;
the software has not verified that its Binance reference signal is suitable
for that execution instrument.

## ATR reference estimates

True range is `max(high − low, abs(high − previous_close),
abs(low − previous_close))`. Wilder ATR(14) starts with the arithmetic mean
of 14 consecutive true ranges, requiring 15 candles, then updates as
`ATR = (13 × previous_ATR + current_true_range) / 14`. The current calculation
uses the completed candles in the bounded recent-data window; Wilder's
recursive result depends on that window's seed and history.

Entry is the latest completed Binance candle close. BUY uses
`SL = entry − 1.5 × ATR` and `TP = entry + 3 × ATR`; SELL reverses the signs.
HOLD has no entry/SL/TP recommendations. Pending, failed, historical and expired
views clear all previous levels; a valid HOLD may still display ATR(14).
These estimates do not account for Exness spread, commission, contract
specification or execution prices and do not establish an actionable order.

## Troubleshooting and limits

- If Conda activation fails, initialize the current zsh session with the `eval`
  command above and check `python --version`.
- If the chart library is missing, rerun `npm ci --prefix web --ignore-scripts`.
- If the historical preview is missing, check
  `data/silver/binance/1h/BTC-USDT.parquet` or pass `--data-root`. Recent-data
  requests are separate from that local preview.
- Recent-data loading needs connectivity to Binance. A provider failure is
  shown explicitly; another exchange is not silently substituted.
- Completed hourly candles are not streaming broker prices. Missing hours are
  never filled. A freshness or quality failure prevents a usable assessment.

No profitability, accuracy or model-confidence claim is made. Historical Gold
remains research-only with unknown publication availability and zero historical
decision-eligible rows. This dashboard does not modify those datasets or
authorize historical model evaluation, backtesting or automated execution.

TradingView Lightweight Charts is produced by TradingView; attribution appears
in the page footer and at <https://www.tradingview.com/>.
