# Hybrid Quant Terminal — personal Demo guide

## Open and close

Keep your Exness Demo MT5 terminal open and connected. Its existing read-only bridge must be attached and exporting; the application does not log in for you. If MT5 was restarted, confirm the bridge is attached and working. Do not enable Algo Trading or enter credentials into this dashboard.

In Terminal on your Mac, run:

```bash
cd "$HOME/Developer/mt5-market-data"
.venv/bin/python tools/devctl.py start
```

Open **http://127.0.0.1:5173/** in your browser. To check or stop the local services, run from the same directory:

```bash
.venv/bin/python tools/devctl.py status
.venv/bin/python tools/devctl.py stop
```

A repeated start reuses the healthy project services. A conflict or partial startup is reported instead of creating a second consumer. Stop does not close MT5 or change its account. Use only this Developer copy, not the retired Documents copy.

## Read the dashboard

Choose **MT5 Live — Exness Demo**, EURUSDm or XAUUSDm, and M15, H1 or H4. The chart may show retained candles even when the feed is **UNVERIFIED**. Latest-bar labels use the broker clock; its timezone is not verified. A LIVE label means the software observed its required feed-health evidence, not that the broker's terms, execution or a trade are verified. Open **Feed details** for the reason a feed is blocked.

An analytical BUY or SELL describes the existing chart calculation, not an order. Neutral market context is not proof of an entry. WAIT means no current eligible analysis is available or action remains blocked. **OVERALL ACTION: WAIT / BLOCKED UNVERIFIED** is the controlling execution-readiness display. Do not treat a direction label or chart pattern as a proven profitable recommendation.

When available, Entry, Stop Loss and Take Profit are **reference levels**, not broker quotes or order records. The page shows pattern detection/confirmation and latest candle time. Its entry uses a pattern neckline; stop and target use the latest snapshot ATR and can change. Stale, historical, invalidated and unverified states must not be treated as a current executable setup. If none is available, no level is invented.

In **Broker Risk**, enter an illustrative USD risk budget. It is a hypothetical amount, not a verified account balance or position size. The calculator shows only values supported by its inputs; unavailable lot size, margin, commission, spread, slippage or financing is not zero. Current broker specifications and execution remain unverified, so do not treat the result as an executable position.

## If data stops updating

1. Check that MT5 is open, connected to the intended Demo server, and that its read-only bridge is running.
2. In the dashboard check the feed status and expand **Feed details**. A revision, unknown gap, insufficient contiguous bars or stale data may require WAIT. Switching instruments does not repair missing evidence.
3. Run the `status` command above. If a local service has stopped, run `stop` followed by `start`; read its printed diagnostic if it cannot start. Do not delete lock files, checkpoints, revision ledgers or handoff files.
4. If MT5 is connected but a conflict or missing broker information remains, leave it unverified and seek review of the source evidence. Do not use the old Documents checkpoint to recover newer data.

The application does not send orders, change the account or automate trading. Any action in MT5 remains your independent manual decision.
