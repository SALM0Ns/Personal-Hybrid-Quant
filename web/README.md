# PQTA-001 local candlestick preview

This is a local, read-only chart of the existing Binance Spot BTC/USDT 1-hour
Silver Parquet snapshot. It is a **historical preview, not live market data**.
`Analyze Now` rereads the same local snapshot; it does not contact Binance,
calculate features, run a model, or produce a trading recommendation. Signal
status is always `NO SIGNAL`.

## Installation

From the repository root, with the `pqta` Conda environment already created
as described in the [root README](../README.md), and Node/npm available:

```bash
eval "$(conda shell.zsh hook)"  # initialize this shell; no config change
conda activate pqta
python -m pip install -e '.[dev]'     # omit if already installed
npm ci --prefix web --ignore-scripts
```

## Start and open the chart

From the repository root:

```bash
python -m quant.app
```

Open <http://127.0.0.1:8765>. Stop with Ctrl-C. The server binds only to
`127.0.0.1`; `--port` changes the port and `--limit` changes the maximum
displayed candle count (default 500, maximum 2000). `--data-root` defaults to
`data` relative to the directory from which the command is run. The expected
file is `data/silver/binance/1h/BTC-USDT.parquet`. Python dependencies come
from the existing `pyproject.toml`; the only new frontend dependency is pinned
TradingView Lightweight Charts in `web/package-lock.json`. Its runtime files
are installed locally under ignored `web/node_modules/`, so the page has no CDN
requirement. No global Python or npm installation is performed.

## Analyze Now

The page loads a bounded historical window on opening. Clicking `Analyze Now`
rereads the same local Silver file and refreshes the chart, latest candle time,
data-source status, and gap status. It does not ingest fresh data, calculate
features, run ML inference, or generate a recommendation. The signal remains
`NO SIGNAL`, including after an error.

## Troubleshooting

- If activation fails, run `eval "$(conda shell.zsh hook)"` in that zsh session
  before `conda activate pqta`; check `python --version` after activation.
- If the server reports a missing frontend dependency, run
  `npm ci --prefix web --ignore-scripts` from the repository root.
- If the page reports a missing Silver dataset, verify
  `data/silver/binance/1h/BTC-USDT.parquet` exists locally or pass the correct
  `--data-root`. The app does not download it.
- If port 8765 is busy, start with `python -m quant.app --port 8766` and open
  the corresponding localhost URL. Malformed OHLCV or an incomplete candle
  produces a visible error rather than an invented chart value.

## Current limitations

The backend selects 500 recent matching Silver observations by default (up to
2,000 with `--limit`), checks
timestamp alignment, completed candles, OHLCV validity, duplicates, and gaps,
then emits sorted chart data. A gap is reported rather than filled. A malformed
or missing dataset produces a visible error and no chart candles. The chart
uses UTC timestamps, but neither theoretical closure nor the local snapshot's
`ingested_at` establishes historical publication availability. The source
Gold snapshot remains research-only with unknown `available_at` and zero
decision-eligible rows. This application does not use Gold or QNT-003 research
protocols for decisions. Future ML integration requires separate approval and
a shared, point-in-time-safe feature and eligibility interface.

This chart library is produced by TradingView; see the attribution in the
page footer and <https://www.tradingview.com/>. No BUY/SELL markers, live API
fetching, order submission, or automated execution are implemented.
