# v1.0 personal Demo release checklist

Verdict: **V1.0 CONDITIONAL — LIMITED DEMO USE**. These are observations from the 2026-11-13 local verification, not ongoing guarantees.

| ID | Requirement | Result | Evidence and user impact |
|---|---|---|---|
| R1 | Start/stop | PASS | Owned services stopped and restarted on localhost; a repeated start reused them. A conflicting or partially running service requires operator review. |
| R2 | Market selection | PASS | All six MT5 symbol/timeframe views displayed their corresponding cached candles and quality status. Unverified feeds are chart-only for current setup purposes. The EURUSDm H1 historical view also loaded and was separately labeled offline. |
| R3 | Analysis | PARTIAL | EURUSDm H1 showed analytical direction and WAIT/BLOCKED; unverified XAUUSDm M15 showed WAIT. Other directions and neutral behavior have synthetic coverage but were not all observed live. |
| R4 | Setup references | PASS | The browser showed a reference timestamp, elapsed completed bars, ATR-recalculation notice and non-executable status; unavailable and stale handling have tests. No automatic age-based expiry is implemented, so inspect age rather than treating an active reference as an order. |
| R5 | Risk | PARTIAL | A user-entered USD 1 illustrative budget appeared in the live H1 panel. Invalid amounts returned 422. Volume, margin and costs remain unavailable because broker evidence is unverified. |
| R6 | Data quality | PASS | EURUSDm M15's revisions remained quarantined; UNVERIFIED feeds kept levels blocked. UNKNOWN gaps and the 50-bar requirement were preserved. |
| R7 | UI | PARTIAL | The local browser displayed the chart, six live selections, warnings and risk-budget form. A complete responsive-device and browser-console audit was not performed. |
| R8 | Recovery | PASS | During a real local stop the browser showed UNVERIFIED/WAIT and hid levels; it recovered automatically after restart. Checkpoint and ledger were preserved without duplicate cached timestamps; fault cases also use synthetic fixtures. |
| R9 | Daily usability | PARTIAL | Startup, market selection and budget entry were exercised. MT5 login/bridge attachment remain manual prerequisites, and unverified feeds cannot provide current setups. |
| R10 | Safety | PARTIAL | API/Vite listened only on localhost; no order route was found. No account or trading settings were changed. Current MT5 Algo Trading state was not independently inspected in this check. |

The terminal remains local and read-only. A LIVE feed does not authenticate broker terms or authorize an order. The owner may use verified display/analysis for Demo observation while recognizing that position size, margin, costs and execution remain unverified.
