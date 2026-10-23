# Model Evaluation Publication Index — Proposed

**No historical model evaluation has been run or published.** This folder
currently contains documentation only, not model results. The four model
components and PQTA-003D-4A accounting/reporting have synthetic tests;
those are not evidence of BTC/USDT predictive performance.

The [PQTA-003D-4 contract](../MODEL_EVALUATION.md) defines a versioned
`pqta-model-evaluation-v1` comparison format governed by unchanged
`qnt-003d-design-v1` and source dataset contract
`pqta-003b-origin-ledger-v1`. Pure in-memory schema validation is
implemented; the historical runner and public-summary publisher are not.
PQTA-003D-4A Architect review is approved for the synthetic implementation;
separate owner historical execution authorization is still required.
Lane B and trading backtesting remain
blocked; all current Gold rows have unverified historical availability
and false decision eligibility.

Approved report boundaries are training-history accounting only, Ridge
validation candidate tuning diagnostics only, and frozen-alpha test
comparison. There is no selected-alpha validation replay or training-history
performance report. Research metrics are not trading confidence.
Synthetic fixture reports remain in memory; none is a historical result
or published summary. The validator needs independent typed accounting
evidence and does not authenticate source-file bytes by digest syntax alone.
Reporting precedence is `blocked`, `no_forecasts`, `no_scored_forecasts`,
then `complete`. A blocked Ridge blocks a four-model comparison. Supplied
forecast counts/coverage remain distinct from common-set denominators;
blocked metrics are null without erasing those counts. Anomaly metadata
remains explicitly unverified/partial, and source-byte verification is
always false in this synthetic-only implementation.

## Proposed future report pair

After execution is separately authorized, the complete requested scope
is validated, and the owner approves publication:

- `<evaluation_build_id>.md`: readable methods, period/sample/comparison
  scope, metrics, denominators, abstentions, exclusions and limitations.
- `<evaluation_build_id>.summary.json`: bounded aggregate public projection
  of the versioned format in MODEL_EVALUATION §4. Include dataset/source
  build, evaluation spec/build, protocol, source/manifest digests and
  local artifact digests. Public bytes receive their own checksum.

No result links or numeric placeholders are listed until a real validated
report exists. `complete` will describe validated retrospective processing,
not profitability or point-in-time verification. Empty sets have null
metrics and an explicit unavailable status, not apparent zero error.

## Publication checklist — not an execution command

1. Verify authorization, immutable inputs, full origin accounting, daily
   refit and frozen-alpha evidence, common scored-set digests and rerun
   determinism. Separate validation selection scores from test metrics.
2. Keep A-primary and A-sensitivity separate. Direct method comparisons
   must share exact scored timestamp sets. Retain unavailable models,
   coverage, exclusion and failure counts, and unresolved evidence caveats.
3. Include the warning: **HISTORICAL / RESEARCH ONLY — POINT-IN-TIME
   AVAILABILITY UNVERIFIED — NOT APPROVED FOR TRADING**.
4. Keep source candles, targets/predictions by origin, Parquet, refit
   parameters, raw evidence and large artifacts under ignored local
   `data/`. Do not upload them as repository files or release assets.
5. Review the bounded summary for credentials, absolute local paths and
   private information. Stage only owner-approved report files; inspect
   the complete staged diff. No automated publication or push is proposed.
6. Publish new immutable identities for changed bytes; retain history with
   explicit supersession notes. Do not overwrite old results silently.

Public summaries reference local hashes but cannot independently reproduce
results without the private local artifacts. A dashboard may later inspect
these summaries read-only; it must not convert model inspection, RMSE,
accuracy or coverage into a trading recommendation or confidence score.
