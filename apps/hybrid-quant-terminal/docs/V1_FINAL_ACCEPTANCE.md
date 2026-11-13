# v1.0 final acceptance — personal Demo

**V1.0 CONDITIONAL — LIMITED DEMO USE**. Use the [personal guide](USER_GUIDE_V1.md) and [release checklist](V1_RELEASE_CHECKLIST.md). Do not use these results as evidence of profitability or as verified execution instructions.

## What was checked

On 2026-11-13 the existing Developer API and Vite services were stopped and restarted using the project launcher. The original MT5 terminal was left running. The open browser changed to UNVERIFIED / WAIT and hid current levels while the API was unavailable, then recovered when the feed's new heartbeat and quote progression were observed. Repeated launcher start reused the healthy project-owned services. API and Vite bound to 127.0.0.1; there is no order-submission API.

A synthetic USD 1 illustrative budget was entered in the actual local browser and returned by the live API as user-provided, while position volume, margin, costs and execution eligibility remained unverified. All six live symbol/timeframe selectors were exercised, including EURUSDm H1 and XAUUSDm M15. The latter remained UNVERIFIED with its chart available and no current setup. The EURUSDm H1 historical chart also loaded and was labeled offline. The current setup interface displays the broker-clock reference close, elapsed completed bars, absence of age-based expiry and the fact that ATR-derived levels can change.

The authoritative checkpoint and revision ledger were preserved across the local restart, without duplicate cached timestamps at that check. Two EURUSDm M15 source revisions remained unresolved. A local backup was verified. Normal later ingestion can advance the checkpoint; never restore an older backup over newer accepted data.

At inspection EURUSDm H1 was LIVE and the other five feeds were UNVERIFIED. Unknown gaps remain unknown; the 50-consecutive-bar rule was not lowered. Broker specifications and margin/cost/financing evidence remain unverified. The existing pattern strategy has no age expiry; a shown direction or reference is not an executable recommendation. MT5 broker-clock timezone and publication latency remain unknown.

## Tests

- Full offline Python suite: **326 passed**, two deprecation warnings.
- Focused bridge, ownership, launcher, risk and API suite: **165 passed**, two warnings.
- Frontend: **25 passed**; TypeScript and Vite production build passed.
- Ruff lint and format passed; pip check reported no broken requirements.
- An initial frontend test invocation from the project root failed because that directory has no package.json; the correctly located rerun and final suite passed.

These tests are not a profitability, execution or complete historical-data validation. MT5 connection and read-only bridge attachment remain manual platform prerequisites. Browser console and a full responsive-device audit were not completed, and current MT5 Algo Trading state was not independently inspected. No order, credential or account change was made.

The product can be frozen at this conditional Demo scope. A confirmed safety or data-integrity defect would require correction; unresolved external evidence remains explicitly unverified rather than being filled or assumed.
