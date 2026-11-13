# Changelog

## Unreleased — repository consolidation

Changes since the previous published repository commit `93ce9ce`:

- Preserve the original Personal Hybrid Quant source, research documentation,
  data-engineering pipelines, tests and independent Python environment.
- Add the existing Hybrid Quant Terminal under `apps/hybrid-quant-terminal/`
  with its read-only MT5 bridge, analytics, local API, frontend, launcher,
  tests, configuration support and documentation. This imports an existing
  application; it does not claim these capabilities were newly developed here.
- Retain the terminal's previously implemented snapshot-bound Entry/SL/TP
  safeguards and chart rendering fixes.
- Document the two project boundaries and existing local startup process.
  Local datasets, broker credentials, runtime state and generated build output
  are excluded from the repository.

Hybrid Quant Terminal remains **v1.0 Conditional — Limited Demo Use**.
Historical availability, broker-clock interpretation, feed quality and broker
execution constraints may be unverified; no automatic trading or profitability
claim is made. This consolidation does not migrate the existing installation.
