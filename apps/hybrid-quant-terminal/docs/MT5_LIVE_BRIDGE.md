# Read-only MT5 bridge (v0.3)

**Status: partially verified with a real MT5 Demo feed. Compilation, ingestion, API delivery and an automatic Vite dashboard rollover have been observed for XAUUSDm M15; other feed limitations remain.** MT5 must remain running and connected for new data. This bridge does not place orders, modify positions, read credentials, or connect Python to a trading API. Its server and demo-mode checks are terminal attestations, not cryptographic authentication. It does not combine the runtime feed with the existing immutable historical snapshots.

## Manual first-time setup on macOS / Wine

1. Review `mql5/ReadOnlyMarketBridge.mq5`. In the existing connected **Exness Demo** terminal, choose **File → Open Data Folder**. Verify the terminal and server yourself. Use the terminal-provided folder for the actual installation.
2. Manually copy the source into that folder's `MQL5/Experts/`, open it in MetaEditor and compile it. Check and resolve compiler errors. Verify compilation after any source changes.
3. Refresh Navigator and attach `ReadOnlyMarketBridge` to one chart. Review its inputs: the defaults are a 15-second timer and 256-bar bounded recovery. Keep **Algo Trading** disabled; do not enable DLL imports or trading permissions. MetaTrader's [documentation](https://www.metatrader5.com/en/terminal/help/algotrading/trade_robots_indicators) states Expert Advisors can run with trading prohibited, but verify the timer actually runs in your terminal. The exporter is designed to reject non-demo mode and non-Exness server names as reported by MT5.
4. The exporter uses the local MT5 file sandbox, not `FILE_COMMON`: `<MT5 data folder>/MQL5/Files/mt5_bridge/incoming/`. Python reads this directory without changing its files. The exact mapping of Windows/Wine paths must be confirmed using **Open Data Folder**.
5. Start and inspect the existing local services from the authoritative Developer project:

```bash
cd "$HOME/Developer/mt5-market-data"
.venv/bin/python tools/devctl.py start
.venv/bin/python tools/devctl.py status
```

Open `http://127.0.0.1:5173/` and select **MT5 Live — Exness Demo**.
Use `.venv/bin/python tools/devctl.py stop` to stop the local services. Leave
the existing MT5 producer and handoff unchanged. The Documents project is a
retired reference; do not start its API or ingestion. See the
[current cutover workflow](RUNTIME_CUTOVER_V04E.md).

## Handoff and recovery

The producer uses completed `CopyRates` bars starting at shift 1 after synchronization. A batch consists of a UTF-8 CSV payload and an `mt5-live-v1` field/value manifest recording source, server, market, row count, broker-clock cutoff, shift, recovery counts and SHA-256. The content-derived batch identity binds the payload hash to server, symbol and timeframe. Separate `mt5-heartbeat-v1` files report connection, synchronization and per-symbol tick evidence. Hashes detect mismatches; they do not authenticate the source.

Payload and manifest are closed before publication; Python verifies schema, exact identity, size, count, hash, ordering, OHLC and closure before accepting a batch. Wine/MQL5 file-move atomicity is not assumed. Identical replay is idempotent; a conflicting candle or malformed batch is rejected, with no partial checkpoint update. Accepted state is persisted separately in `runtime/mt5_bridge/state/` and survives a backend restart. The EA uses bounded overlap on each polling cycle; gaps or a truncated recovery remain unknown and are not filled. A single backend consumer is supported. The immutable Bronze/Silver datasets and baseline reports are never modified.

The exporter does not delete handoff files. An orphan payload without a completed manifest is reported and conservatively blocks feed health until it is resolved; the producer may publish its matching manifest on a later cycle. Do not delete or alter an unresolved handoff without reviewing it. Over long periods the directory and runtime checkpoint grow; this version does not provide automatic archival or pruning. All broker times remain unzoned broker-clock readings; do not interpret them as UTC without independent evidence.

## Health and restrictions

The UI distinguishes exporter heartbeat, last ingestion, target-symbol quote progression, connection status, latest accepted bar, warm-up and unknown gaps. `LIVE` requires fresh observed producer and target-symbol progress plus synchronized, connected and sufficiently current validated bars, including at least 50 consecutive bars in the latest segment. Older unknown gaps remain visible and do not prove a market closure; indicators restart at each gap. A heartbeat alone never proves fresh quotes. `STALE` denotes expired observations or bars; `OFFLINE` is used for an explicitly reported disconnect; `UNVERIFIED` covers insufficient evidence. `MARKET_CLOSED` is never asserted without a verified session calendar. A gap is not called a broker outage or scheduled closure. A process restart requires fresh heartbeat and target-quote progress again.

A healthy feed does not verify spread, contract size, margin, broker execution or profitability. The terminal keeps overall action `WAIT` and execution eligibility `BLOCKED_UNVERIFIED`. Unknown continuity and insufficient consecutive bars can prevent current setups even when a chart is visible.

## First real integration test — owner-run

After manually compiling and attaching the EA, verify in MT5's **Experts** log that it starts on the intended demo server, and confirm files appear in the handoff folder. Start the backend and frontend as above. For each symbol and timeframe, check source labels, broker-clock times, ingestion and heartbeat details, and whether status changes only when target quotes and completed bars advance. Test stopping the EA or disconnecting MT5 and confirm the terminal reports stale/offline or unverified rather than live. Record exact outcomes before treating the bridge as operational. Do not place an order to test it.
