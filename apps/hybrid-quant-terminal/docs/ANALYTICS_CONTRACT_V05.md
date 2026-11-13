# v0.5 analytics and decision-support contract

## Runtime and source boundaries

`~/Developer/mt5-market-data` is authoritative. The local API, chart and checkpoint use the existing read-only MT5 file handoff; the Documents project is a retired reference, with optional historical snapshots read only. Use [the runtime workflow](RUNTIME_CUTOVER_V04E.md) for startup, ownership, recovery and the macOS-specific dependency lock. An advisory consumer lease prevents cooperating duplicate writers; it is not protection against deliberately modified or uncooperative programs.

MT5 bar timestamps are unzoned broker-clock candle opens. Theoretical close is open plus the nominal timeframe and is not an authenticated publication time. The producer supplies completed bars, and the bridge verifies the handoff and source identity, but its demo/server claims and broker timezone are not authenticated. Historical source coverage and availability also remain unverified. Never convert broker-clock times to UTC without independent evidence.

## Indicators and continuity

`indicators.py` implements EMA(20), EMA(50), ATR(14), and ADX(14); `terminal_analysis.analyze_bars` consumes strictly increasing, unique, valid OHLC rows. It is a calculation interface over caller-supplied completed bars, not itself proof of feed publication or source authenticity. The first EMA is the arithmetic mean of its period; subsequent values use alpha `2/(period+1)`. True range starts with high minus low after a reset, then is the maximum of high minus low and the absolute changes from previous close. ATR seeds with 14 true ranges and then uses Wilder's recursion. ADX uses strict positive/negative directional-movement dominance, Wilder-smoothed sums, zero for zero-denominator DI/DX, and seeds its first value with 14 DX values after the initial prior bar (first ADX on bar 28). Nonfinite indicator input or arithmetic fails validation; API analysis errors are reported as validation failures.

Every unverified interval resets indicator warm-up and pivot state. No missing prices are filled; this includes possible session closures until a calendar and broker-clock mapping are verified. The dashboard currently analyzes a single selected timeframe. The separate historical simulator uses only higher-timeframe bars whose theoretical closes are at or before its as-of boundary; this is not evidence of historical publication availability.

## Patterns, swings and levels

A swing needs strictly higher/lower values than its configured left and right neighbours; ties do not form pivots. The pivot appears retrospectively at its earlier candle, but its separate confirmation timestamp is the theoretical close of the last required right-hand candle. The engine builds Double Top and Double Bottom candidates from confirmed same-kind pivots with an opposite pivot between them, subject to configured separation and ATR-based tolerance. A strict neckline close confirms, and an anchor-plus-tolerance breach invalidates. An unknown gap ends tracking without declaring invalidation. `tracking_ended_at_timestamp` means the theoretical close of the first observed post-gap candle, not the gap start or an authenticated publication instant.

Support/resistance zones cluster nearby confirmed pivots using an ATR tolerance. Their latest geometry cannot be treated as known before `last_updated_at_timestamp`. Zone geometry and historical pattern state are snapshots; drawings at pivot time are not point-in-time trading events. Prefix fixtures verify event timestamps for synthetic sequences, not all possible historical revisions or a non-repainting claim.

The latest still-confirmed pattern in the current segment may supply an analytical direction; no independent pattern-age expiry is implemented. Its entry reference is the pattern neckline. Stop uses its anchors and the latest snapshot ATR, and target uses the resulting distance and configured reward/risk ratio. Stop and target can therefore change with a later snapshot; they are not stored executed levels. A target already reached is labeled stale in the presentation. Analytical BUY/SELL describes the pattern calculation, not an execution instruction.

The engine fails closed to WAIT without reference prices if stop or target geometry is invalid, including when floating-point rounding collapses the target to entry. The frontend matches the selected source, symbol, timeframe, snapshot and analysis settings before displaying results; it hides current references while loading or on a failed request. When displayed precision rounds distinct prices to the same value, it warns and hides the chart's setup lines; the display precision does not establish broker tick size. When eligible lines are displayed, chart autoscaling includes entry, stop and target even if a level is outside the candle price range. These safeguards do not turn the reference levels into verified broker prices or orders.

## Health, provenance and decision states

Observations, indicators, pattern state, setup references, feed health and broker-risk evidence are distinct. MT5 analytical responses bind feed health and continuity to their returned snapshot; current setup visibility requires `LIVE`, a valid snapshot identity, zero unresolved revisions, and at least 50 contiguous bars in a consistent history count. Older UNKNOWN gaps remain visible and do not become verified closures. Any unverified feed or invalid/insufficient indicators makes current analysis WAIT and removes current reference levels. The policy does not establish point-in-time availability, broker authenticity or executability.

Analysis responses identify symbol, timeframe, snapshot, settings, response-observation time and, when available, reference provenance. The observation clock is not a source publication timestamp. The current implementation has no separately versioned indicator algorithm identity; source revision plus settings must be recorded when reproducibility across code changes matters. Broker evidence remains `OBSERVED_UNAUTHENTICATED` / `UNVERIFIED`; the recorded native test scenarios cover only their specific inputs. Price-distance reward/risk, possible monetary outcomes, costs, margin and execution eligibility are separate. Unavailable costs are not zero. Overall action remains `WAIT` with `BLOCKED_UNVERIFIED`; no order endpoint is provided.

## Verification and limitations

Run offline tests with the real bridge disabled:

```bash
cd "$HOME/Developer/mt5-market-data"
MT5_DISABLE_LIVE_BRIDGE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp .test-tmp/analytics-tests
.venv/bin/ruff check --no-cache src tests tools
.venv/bin/ruff format --check --no-cache src tests tools
.venv/bin/python -m pip check
cd frontend
npm test
npm run build
```

The fixtures are synthetic and make no claim about live performance. The two EURUSDm M15 revisions and unclassified historic gaps must remain visible; neither a healthy process nor a LIVE feed verifies trading costs or execution. Existing APIs are local decision support, not a backtest, probabilistic forecast or evidence of profitability.
