# Broker-aware risk prototype

This prototype provides **research-only estimates**, not trading instructions.
The existing feed-quality and decision gates remain in force. Broker specification
and execution eligibility remain unverified; a snapshot, its hash, or its own
status fields do not authenticate the broker or prove that a trade is executable.
There is no order placement or trade-management interface.

## Evidence and read-only snapshot

No actual EURUSDm or XAUUSDm instrument specification has been verified by this
prototype. Contract sizes, conversions, commissions, margin, financing and
sessions must not be inferred from illustrative values. MetaQuotes documents
separate profit and loss tick values and instrument-specific volume limits:
[Symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants).
Its [SymbolInfoDouble documentation](https://www.mql5.com/en/docs/marketinformation/symbolinfodouble)
explains how unavailable symbol properties are reported and recommends
`SymbolInfoTick` for quotes. Exness explains that overnight financing and its
schedule vary: [About swap](https://get.exness.help/hc/en-us/articles/360014709151-About-swap).
These references explain properties; they do not verify the connected account.

`mql5/BrokerSpecificationSnapshot.mq5` is a separate, read-only, manual helper.
After independent review, compile
it with the installed MetaEditor, then run it manually only on the intended
connected Exness demo terminal. It records selected properties in a new CSV in
that terminal's `MQL5/Files` sandbox; it does not read account identifiers,
credentials, balances or positions. It reports failed property reads explicitly,
and labels the broker clock as timezone-unverified and the source as
self-reported. The helper neither verifies currency conversion nor retrieves a
complete commission schedule, available margin, or complete session rules.
Exported snapshots are not automatically authenticated, consumed as execution
truth, or sufficient to mark a result VERIFIED.

## Calculations and limitations

The risk engine supports a synthetic, explicitly selected linear tick-value
convention for testing: stop distance divided by tick size times the loss-side
tick value gives estimated gross loss per lot; target distance uses the
profit-side value. This approximation is not a claim that a live broker's tick
value, currency conversion, or calculation mode is valid at all prices.
The strategy’s price-distance reward/risk ratio is distinct from the synthetic
gross monetary reward/risk ratio when profit and loss tick values differ.
Volume is rounded down to the broker step; a minimum lot that exceeds the risk
budget is infeasible. Missing inputs are not treated as zero. Costs and margin
remain unavailable unless separately established; gross estimates are not net
risk. A broker-native, appropriately authenticated calculation and current
account-specific feasibility checks remain future work.

The local read-only API exposes `/api/broker-risk` independently of market
feed and analytical setup health. `/api/broker-specification` reads only the
explicit project file `runtime/broker_spec_snapshot.csv`, when present. Copying
the manual export there does not authenticate it or make it a calculation input. An unverified snapshot or missing conversion,
cost, margin, staleness or feed evidence continues to block verification.
No UI value should be interpreted as permission to place an order.

## v0.3 reliability

Some existing Python dependency files were marked `dataless` and imports blocked
before collection. Targeted requests to restore only application and dependency
files were temporary: offloading recurred. The exact cloud offloading mechanism
is not established. A full regression was therefore also attempted using
existing locally installed Python components; see the delivery report for the
precise environment and results. No dependency versions were changed.

The earlier v0.3 assessment remained partial: one of six feeds was LIVE at its
last recorded observation; the other five were unverified, including the
EURUSDm M15 source-revision quarantine. The 34 historical UNKNOWN gaps were
not reclassified. Those historical observations are not a live health check.

## v0.4-B/C operator workflow and verification boundary

The two project sources `mql5/BrokerSpecificationSnapshot.mq5` and
`mql5/BrokerNativeRiskProbe.mq5` are separate read-only scripts, not Expert
Advisors. The second uses `OrderCalcProfit` and `OrderCalcMargin` only for
hypothetical minimum-volume BUY and SELL cases, with stop and target distances
of 100 and 200 tick sizes. BUY reference opens use the observed ask; SELL
reference opens use the observed bid. These inputs are invented probe scenarios,
not signals or orders. Both scripts require an Exness Demo terminal and write
CSV files under its `MQL5/Files` sandbox. Each writes a `.partial` file and
publishes the final name only after writes close successfully; no guarantee is
made about crash durability. Broker quote timestamps remain in the unverified
broker clock. Failed calls and missing values remain unavailable.

Compile both scripts in the active terminal's `MQL5/Scripts` folder using
MetaEditor; verify its actual compilation log and generated `.ex5` files.
Refresh Navigator → Scripts, then run each once on the intended Demo terminal.
Do not enable algorithmic trading or change account settings. The owner must
verify the terminal and source/build identity. When present, preserve original
output bytes in a separately named project-local evidence directory before
copying a chosen snapshot and probe respectively to
`runtime/broker_spec_snapshot.csv` and `runtime/broker_native_probe.csv`.
The fixed-path endpoints `/api/broker-specification` and
`/api/broker-native-comparison` consume those local files without source
attestation. A SHA-256 digest identifies bytes only. The comparison uses an
explicit linear tick-value hypothesis and reports absolute/relative differences;
it cannot prove matching quote times, tick-value currency, source authenticity,
margin feasibility, costs, or execution eligibility. An empty or malformed input
remains unverified.

MetaQuotes describes [OrderCalcProfit](https://www.mql5.com/en/docs/trading/ordercalcprofit)
as a current-environment hypothetical estimate in account currency. Its
[OrderCalcMargin documentation](https://www.mql5.com/en/book/automation/experts/experts_ordercalcmargin)
states that the estimate does not consider existing positions or pending orders.
Neither API places an order, and neither guarantees future execution.

## Current operation

Use the [runtime workflow](RUNTIME_CUTOVER_V04E.md) and [user guide](USER_GUIDE_V1.md). Snapshot and probe output files, account details and local runtime evidence remain private. A historic native comparison covers only its recorded hypothetical cases; it does not establish future execution eligibility or verified position sizing.
