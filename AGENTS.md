# Engineering Rules

Before implementing a change, read `docs/PROJECT_CONTEXT.md` and
`docs/DECISIONS.md`. Treat confirmed decisions as constraints; do not change
architectural decisions without project-owner approval.

## Data and research integrity

- Never introduce look-ahead bias or data leakage.
- Use timezone-aware UTC timestamps for all market data and derived records.
- Never generate trading signals from incomplete candles.
- Keep ingestion idempotent: rerunning a job with the same inputs must not
  create duplicate or conflicting records.
- Validate historical market data before it is used downstream.
- Write tests for critical transformations, including time and completeness
  boundaries.

## Trading boundary

- This project is semi-automated: it may produce research outputs and signals,
  but execution remains manual.
- Do not implement automated order execution, brokerage connectivity, or live
  trading functionality.

## Repository hygiene

- Keep secrets and API keys out of source control.
- Prefer small, explicit, maintainable changes and update documentation when
  implemented scope changes.
