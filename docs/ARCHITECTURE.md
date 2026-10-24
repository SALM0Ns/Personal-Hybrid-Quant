# Architecture

## Proposed logical architecture

```text
Market Data
  → Bronze
  → Silver
  → Gold
  → Statistical / ML Research
  → Signal Generation
  → Risk Assessment
  → Dashboard
  → Manual Trading
```

| Component | Responsibility | Status |
| --- | --- | --- |
| Market Data | Obtain Binance Spot historical 1h OHLCV through CCXT. | Implemented for three symbols |
| Bronze | Preserve distinct raw source observations and retrieval metadata. | Implemented |
| Silver | Validate, normalize, deduplicate, and standardize UTC records. | Implemented for hourly crypto OHLCV |
| Gold | Create curated, analysis-ready datasets and features. | BTC/USDT gap-aware EDA and research-only seven-feature snapshot implemented; other Gold work proposed |
| Statistical / ML Research | Evaluate hypotheses and candidate models. | Descriptive BTC/USDT EDA implemented; QNT-003 statistical evaluation designed but not executed; ML remains proposed |
| Signal Generation | Produce `BUY`, `SELL`, `HOLD`, or `NO SIGNAL` outputs from complete data. | Proposed |
| Risk Assessment | Assess exposure and constraints before manual action. | Proposed |
| Dashboard | Present research, signals, and risk information. | Proposed |
| Manual Trading | Human reviews and manually executes any decision. | Confirmed boundary |

## Implemented components

Bronze and Silver use one Parquet snapshot per symbol under
`data/{bronze,silver}/binance/1h/BTC-USDT.parquet` (and similarly for ETH and
SOL). The symbol file is the partition and is atomically replaced after a
complete write. Bronze is committed before Silver, so a rerun can rebuild
Silver after an interrupted write. Reports are JSON under `data/reports/`.

Bronze retains timestamped change events and raw CCXT arrays; repeated
observations of the current value are deduplicated. If a provider changes a
candle and later restores an earlier value, all three events remain in Bronze.
Silver selects the valid observation with the latest `observed_at` per candle
key. A candle can enter Silver only when the provider was observed after that
candle closed; re-fetching an identical value after close creates a new event.
Re-fetch overlap is configurable. Coverage is checked against every expected
hour in the requested half-open interval `[start,end)`; the legacy inclusive
end CLI option remains available. The optional per-symbol availability file
requires an explicit UTC start and evidence. Without it, unobserved hours are
`unknown`, never inferred to be before listing from a first returned candle.
With a verified start, pre-availability hours and missing hours within verified
coverage are counted separately. All unobserved requested hours retain the
legacy `missing_candle_count`, and `ingestion_status` remains `incomplete`.
An empty provider page is not treated as proof of completion.
DuckDB can directly query Silver Parquet; no database service is required.

QNT-002A adds a read-only BTC/USDT exploratory workflow. It derives a complete
hourly timeline with null OHLCV at gaps, continuity-valid returns, raw hourly
rolling volatility, and retrospective descriptive labels. Its local-only Gold
Parquet, aggregate tables, JSON, and SVG charts are under
`data/gold/qnt-002a/btc_usdt_1h/`. These are research artifacts, not trading
signals or changes to Bronze/Silver. The report is
`docs/QNT-002A_EDA_REPORT.md`.

QNT-002B reads the existing BTC/USDT Silver Parquet offline and constructs an
explicit UTC hourly Gold timeline. Missing hours remain null; the seven
contracted features require their exact source-candle dependencies and strict
continuity. A versioned candidate anomaly manifest under `configs/` is
separate from Silver and carries evidence for missing hours, shortened closes,
and the REST/archive discrepancy without correcting OHLCV. The local-only
feature snapshot is under `data/gold/qnt-002b/btc_usdt_1h/candidate_v1/`.
Each row records feature and manifest versions, source and manifest SHA-256
digests, and `generated_at` processing time. See the
`docs/QNT-002B_FEATURE_CONTRACT.md` and
`docs/QNT-002B_MANIFEST_AUDIT.md`.

`timestamp` is the UTC candle open and `candle_end_at` is its theoretical close,
not proof of exchange publication. Historical publication availability and
the candidate manifest's version availability remain unverified; the pinned
Gold snapshot therefore has null `available_at` and zero decision-eligible
rows. Anomaly-affected rows also fail the row-level eligibility policy. The
snapshot is for descriptive research, not trading signals or historical
backtesting. Its real-data findings are in
`docs/QNT-002B_REAL_DATA_AUDIT.md`.

PQTA-002B adds a non-network, in-memory adapter around the **same** QNT-002B
feature engine. It accepts only ordered, unique, closed, UTC-aligned BTC/USDT
1h observations with explicit local `ingested_at`, analysis boundary, expected
latest candle, and versioned anomaly manifest. It rejects invalid, future,
out-of-order, duplicate, or stale inputs rather than sorting or repairing
them; `expected_latest_candle` must equal the latest full hour closed at
`analysis_as_of`, and source or quality evidence cannot postdate that boundary.
The output is the engine's existing typed Gold schema in memory; no
Parquet is created. The exact seven formulas, gap rows, null reasons, and
24/168-hour contiguous warm-up are unchanged.

Adapter provenance is distinct from historical Silver-file provenance. For
adapter output, `source_snapshot_sha256` means SHA-256 of canonical UTF-8 JSON
(`pqta-canonical-ohlcv-v1`) containing the fixed market identity, fixed field
order, ascending source rows, six-digit UTC `Z` timestamps, and big-endian
IEEE-754 Float64 hex values; compact sorted-key JSON ends with a newline.
The adapter's feature-version suffix identifies that hash type. Historical
QNT-002B output continues to hash exact Silver Parquet bytes. The manifest
version and canonical digest remain separate. An empty anomaly list is not
quality proof; unknown quality availability leaves `available_at=null` and
`decision_eligible=false`. A local observation time is not exchange
publication time. The adapter is not connected to the chart, any fresh-data
fetcher, model, signal engine, or order route.

`.github/workflows/python-tests.yml` runs the complete offline pytest suite
and Ruff lint/format checks on a clean GitHub Actions runner. Run
`39575760185` passed 84 tests and both Ruff checks for QNT-002B commit
`aa5ac8d6511eb7ea9b26ef6df47308ab338ea6ef`. CI validates the code's
regression behavior; it does not fetch market data, resolve source anomalies,
or establish historical point-in-time availability.

QNT-003 is a completed **research design**, not an implemented evaluation.
Protocol `qnt-003d-design-v1` defines the next-hour BTC/USDT target, three
statistical baselines (zero return, expanding mean, AR(1)), one seven-feature
Ridge comparator, chronological validation, and forecast/score accounting.
Its Lane A is retrospective and needs separate authorization before any
statistical evaluation. Lane B requires verified historical point-in-time
source, feature, and manifest availability and is currently blocked. Trading
backtesting remains blocked. At QNT-003 design closure, no target, model,
prediction, or metric had been generated. PQTA-003C later created only the
research target, as described below. See `docs/QNT-003D_FINAL_RESEARCH_DESIGN.md`.

PQTA-003A completed a read-only inspection of those historical inputs and
contracts. `docs/PQTA-003B_ML_ARCHITECTURE_DESIGN.md` designed a separate,
versioned, **research-only** forecast-origin dataset and linked future
forecast, score, and refit records. Its status remains Complete — Architecture
Approved (Design Only). PQTA-003C is Complete — Architecture Approved
(Research Dataset Only). It implemented the origin ledger alone in
`src/quant/research/forecast_dataset.py`. It verifies exact pinned
Silver, Gold, and canonical-manifest digests; preserves all seven Gold features,
nulls, anomaly metadata, and false decision eligibility; joins Silver by exact
UTC candle open; and constructs the retrospective next-hour target and separate
feature/target/AR-lag quality masks. The last 13:00 UTC audit origin is outside
the approved evaluation splits. Deterministic specification, build, and
artifact-byte identities protect an immutable local-only output under
`data/research/pqta-003/`. See `docs/PQTA-003C_DATASET_IMPLEMENTATION.md`.
The ledger is **not** an approved point-in-time training or backtesting dataset.
Historical forecast/score/refit orchestration, ML fitting/evaluation,
chart integration, Lane A/B execution, signals, and trading remain
unimplemented or blocked.

PQTA-003D-1 — Synthetic Evaluation Protocol Implemented; Architect Review Pending.
`src/quant/research/evaluation_protocol.py` adds pure validation and eligibility
helpers under the unchanged `qnt-003d-design-v1` and
`pqta-003b-origin-ledger-v1` contracts. It reuses the dataset split function
and forecast-side field allowlist, admits historical outcomes only after
theoretical closure, and keeps input eligibility, history counts, daily
refit scheduling, immutable emission status, and ex-post score status separate.
Its 120 synthetic tests do not read historical Parquet. No model, forecast,
predictive metric, or Lane A execution is implemented by this milestone;
Lane B remains blocked and trading/backtesting are not authorized.

Protocol interface clarifications: `validate_hour` accepts any aware,
hour-aligned datetime whose offset is zero at the supplied instant, including
custom timezone objects, consistent with PQTA-003C's UTC representation check.
`historical_target_eligible` selects completed history only: before closure
it returns false without evaluating outcome flags; at or after closure both
flags must be Booleans. It is not a current-origin emission interface.
`validate_score_state` validates final classifications, with no pending status.
Both `scored` and `emitted_but_not_scored` require theoretical target closure;
an abstention may have `not_scored_no_forecast` from its forecast origin.

PQTA-003D-2 — Synthetic Statistical Baselines Implemented; Architect Review Pending.
`src/quant/research/statistical_baselines.py` supplies pure in-memory Zero
Return, expanding Mean, and AR(1) components using the existing protocol.
Mean history preparation admits completed sample-eligible labels only;
prediction recalculates `math.fsum(values)/n` hourly after the 720-label
minimum. AR history preparation uses exact previous/current/next open keys,
not adjacent surviving rows. It admits only completed three-candle pairs
and applies the separate A-primary/A-sensitivity masks. The fit interface
requires midnight, 720 pairs, centered `math.fsum` OLS, finite intermediates,
and `Sxx/n > 1e-16`. Its immutable result records success or failure.
Current-lag preparation and prediction are separate; prediction accepts only
the current day's midnight fit, and a failed or skipped refit cannot reuse
older coefficients. Forecast-side mappings use the existing allowlist.

Source status flags are supplied by the validated-input caller; these APIs
do not read Silver, Gold, or origin ledgers. Synthetic fits/predictions are
covered by 117 tests, including numerical failures, sample masks, gaps,
closure boundaries, and future-row invariance. No historical evaluation,
forecast/score ledger, predictive metric, Ridge implementation, or new
dependency is included. Lane B, trading, and backtesting remain blocked.

Construction checks reject malformed manually supplied `ARFit` and
`CurrentLag` records. A successful fit requires finite parameters, at least
720 pairs, a scheduled UTC midnight, and a non-null maximum outcome close
no later than that refit. A failed fit carries an approved reason and no
parameters. A successful lag requires a finite numeric value; an unavailable
lag carries a null value and an approved reason. These are structural and
numeric checks, not cryptographic provenance verification.

Mean history selection retains the approved closure and sample rules:
`target_valid=false` excludes the label; `target_valid=true` retains the
sample-eligible label even if its value is missing or nonfinite. After the
unchanged 720-label minimum is met, finite values produce the mean and any
eligible missing/nonfinite value produces `nonfinite_prediction`. Such
labels are never silently discarded to obtain a prediction.

## PQTA-003D-3 synthetic Ridge comparator

`src/quant/research/ridge_regression.py` is Synthetic Ridge Implemented;
Architect Review Pending. The practical product goal is a personal 1H crypto
BUY/SELL/HOLD assistant for small-capital decision support. These components
remain isolated from the historical chart and protect that future product
through the unchanged research contracts; synthetic tests establish no
historical performance, profitability, or live-trading readiness.

The pure in-memory APIs separate `prepare_history`, `fit_scaler`,
`standardize`, `fit_ridge`, `select_alpha`, and `predict`. `ResearchRow`
uses the seven-feature contract order and historical label origin, not
candle open. The closure gate precedes outcome/quality inspection. Training
omits missing/nonfinite features without imputation, applies the fixed
sample masks, and requires 720 completed eligible rows. An inconsistent
eligible target causes explicit numerical fit failure. Forecast mappings
use the existing allowlist and seven features; target-side fields are
rejected. Missing current features or sensitivity-filtered feature windows
produce the approved abstention reasons.

Each midnight fit computes training-only feature means and population
standard deviations (`ddof=0`); zero variance gets scale `1`. `math.fsum`
and scaled `math.hypot` norms limit cancellation/overflow. Householder QR
solves the augmented `[1,Z; 0,sqrt(alpha)I]` least-squares system directly,
with seven penalty rows and no intercept penalty. This preserves the
summed-square objective and avoids normal equations/inversion. Positive
alpha stabilizes collinear features. The solver rejects a QR diagonal at
or below `64 * binary64_epsilon * largest_original_column_norm`, nonfinite
intermediates, or nonfinite parameters/predictions with
`ridge_numerical_failure`; it does not change alpha or switch solvers.
Overflow can therefore abstain even on otherwise finite inputs. Fitted
scalers/parameters are immutable and valid only for their midnight's day;
failed or skipped refits never reuse yesterday's fit.

Alpha selection uses A-primary only, the exact grid
`{0.01,0.1,1,10,100}`, and the three existing 2024 half-open folds ending
May 1, September 1, and January 1, 2025. Before fitting any candidate,
`frozen_validation_origins` fixes membership from valid outcomes, complete
features, and the eligible-history count at each origin's midnight. Every
candidate uses this identical set with chronologically prepared daily
fits. Pooled RMSE uses one denominator over all candidate origins, not an
average of fold RMSEs. Failures retain their origins and disqualify the
entire alpha; scheduled refit failures and affected candidate-origin failures
are retained separately. An empty set or no survivor makes Ridge unavailable. Exact
ties choose the smallest alpha. Test outcomes are not inspected during
selection. Test-period refits require the immutable selection result and
the same chosen alpha for either separately fitted Lane A sample. The
selection's analysis boundary must be no later than the test fit cutoff.

Candidate failure records accept the bounded Ridge abstention vocabulary:
`insufficient_training_history`, `ridge_numerical_failure`,
`nonfinite_prediction`, and the seven feature-null and seven feature-anomaly
reason codes. A-primary selection retains its existing masks; this taxonomy
does not enable sensitivity filtering during tuning. Any returned approved
abstention disqualifies the entire alpha and retains its origin/reason;
only survivors receive pooled RMSE on the full frozen set. Refit failures
have their separate insufficient-history/numerical vocabulary. Unknown
reasons and malformed input contracts still raise errors, never forecasts.

Any 2024 row marked `target_valid=true` with a missing/nonfinite target
raises `ValidationDataIntegrityError` identifying its origin before any
candidate fits, including feature-incomplete or cold-start rows. The row
is not imputed, relabeled, or silently removed to change the denominator.

The selection's `analysis_as_of` is an injected theoretical boundary,
not processing time or verified publication. The caller supplies the
complete intended research timeline and validated quality flags; no
historical reader or evaluation orchestrator is added here. All fits,
selection scores, and predictions exercised in 89 Ridge tests are synthetic
and in memory. No Ridge artifacts are published or appended to PQTA-003C's
immutable build. Historical execution needs separate approval; historical
availability remains unverified, Lane B blocked, and trading/backtesting
unauthorized. Numerical equivalence tests cover analytic orthogonal and
collinear solutions and objective stationarity, but do not guarantee
bit-identical results across Python/libm platforms.

## PQTA-003D-4 evaluation architecture and synthetic-only reporting

[MODEL_EVALUATION.md](MODEL_EVALUATION.md) designs a future historical
coordinator around the implemented protocol, baseline and Ridge APIs.
That historical path would verify the immutable origin build and pinned sources,
separate current forecast inputs from completed-label history, preserve
sample-specific refit paths, and record linked forecasts, scores and
refits before deriving paired metrics. Existing protocol, splits, masks,
metric conventions and frozen Ridge alpha are unchanged.

Approved `pqta-model-evaluation-v1` summaries distinguish full-period
forecast coverage/abstentions from common scored-set metric denominators.
New evaluation spec/build/byte identities reference, never overwrite,
the source dataset spec and origin-build identities. A separate ignored
`data/research/pqta-003-evaluations/` root would hold immutable local outputs;
reviewed aggregate Markdown/JSON only may later be approved for GitHub.
The [publication index](evaluations/README.md) contains no evaluation results.

PQTA-003D-4A is Complete — Architect Approved (Synthetic Only).
It implements `forecast_accounting.py` and
`evaluation_reporting.py` as pure in-memory components. They validate
scheduled origin coverage, immutable emission versus closed-outcome score
states, deterministic exclusive/overlapping reasons, conservation, exact
scored-set intersections, finite metrics and evidence-linked strict JSON
reports. Bounded synthetic windows are explicitly contained within fixed
protocol splits; they do not represent full historical evaluation.
Training history has accounting only, Ridge validation has candidate tuning
diagnostics only, and test fixture comparisons require frozen Ridge alpha.
No model is fitted or dataset accessed by these modules. The Python schema
validator reconstructs reports from independent typed in-memory evidence;
it does not authenticate local artifact bytes or verify historical PIT.
Final reporting precedence is blocked, no forecasts, no scored forecasts,
then complete. Missing Ridge selection blocks its comparison, not unrelated
method-own comparisons. Counts and timestamp denominators are retained even
when blocked metrics are null. Explicit unverified/partial anomaly labels
and `artifact_bytes_verified=false` prevent metadata/digest syntax from
being mistaken for verified evidence.
The historical runner, immutable publisher and public-summary projection
remain unimplemented; no historical performance result exists.

The read-only Model Evaluation panel and local summary endpoint are future
designs, not application behavior. They would display research metrics,
coverage, provenance and unverified-PIT warnings separately from signals.
The chart still shows `NO SIGNAL`; `Analyze Now` does not fit or evaluate
models. Research metrics are not trading confidence. Selected-alpha
validation replays and training-history performance claims are excluded.
No historical evaluation is authorized by this
design; Lane B and trading backtesting remain blocked.

## PQTA-003D-4B chronological coordinator — synthetic only

`src/quant/research/model_evaluation.py` implements `run_synthetic` on
immutable, explicitly attested `SyntheticFixture` inputs and a bounded
`OriginUniverse`. Status: Implemented; Architect review pending. No
historical reader, immutable publisher, CLI or dashboard route is added.

At each UTC clock event, labels with `h+1h <= origin` are admitted and
previously emitted forecasts receive their closed-outcome audit. Then the
Mean updates hourly and AR/Ridge refit only at 00:00; current forecasts
use only time/current-feature views plus admitted history. The final
clock closes the last target without adding a forecast. Admission/update
audits record exact label origins, maximum closure, fit result and alpha.

The existing AR convenience preparers accept candles, not target rows.
A small local adapter instead constructs public `ARPair`/`ARHistory` and
`CurrentLag` inputs from exact adjacent valid closed labels, then calls
the existing `fit_ar`/`predict_ar`. This duplicates no return or OLS math.
Mean and Ridge reuse their history/fit/prediction APIs. Source validity
is asserted by the synthetic target contract, not independently verified
from OHLCV. Gaps are never made adjacent by dropping rows.

Each sample has independent fit state. Midnight invalidates prior state
before a replacement fit; failed fits remain failures through the day.
An initial non-midnight window cannot invent a midnight fit. Ridge uses
only a caller-supplied frozen selection; missing selection skips fitting
and is recorded explicitly, never replaced by a guessed alpha. The
approved input/fit abstention priorities remain unchanged.

All four methods and both samples are retained in 4A accounting. Test
fixtures produce method-own, baseline/feature-common and paired sets;
training has accounting only, validation only supplied candidate tuning
diagnostics. The coordinator validates and returns report objects and
canonical bytes in memory, not files. Report PIT/decision flags stay false;
no historical performance, trading confidence or profitability is implied.

## PQTA-003D-5A read-only historical adapter — no execution bridge

`src/quant/research/historical_adapter.py` is implemented; Architect review
is pending. The owner-approved architecture clarification separates typed,
lossless `HistoricalFeatures` and `HistoricalOutcome` records from the
synthetic 4A `Quality`/`Outcome` contract. `HistoricalAdapter` holds these
records, source identity, manifest and approved period universes;
`HistoricalAudit` holds the adapter, report and canonical report bytes. See the
[adapter contract](PQTA-003D-5A_HISTORICAL_ADAPTER.md).

`audit_pinned_history(root)` authenticates approved Silver/Gold/manifest
and immutable origin-build bytes before Parquet inspection. It shares the
validation core with `audit_frames(silver, gold, ledger, manifest, *, identity)`
to check exact schemas, ordered feature columns, UTC source/forecast identities,
approved
split boundaries, source joins, target validity and anomaly masks. Synthetic
tests exercise the in-memory boundary without fitting or forecasting.
The final out-of-split origin remains a separate audit record, never an
evaluation opportunity. No source or immutable artifact is rewritten.

The adapter preserves nullable feature values and null reasons, original
target values and validity reasons, raw source identifiers, row identity
and source timestamps. Target-endpoint and feature-window anomaly records
remain distinct. Original affected-field tokens, including `candle` and
`unknown`, are retained verbatim rather than translated into OHLCV fields.
An association not established by source evidence is retained as
`unresolved`, not silently assigned, by the standalone association helper.
The pinned ledger reader still rejects unknown columns as schema drift;
its two approved anomaly columns have explicit source associations.
Readiness findings list observed categories, association counts, evidence
limitations and required projection
policies. Checking pinned source bytes does not authenticate referenced
archive/REST evidence or determine anomaly causes.

No adapter output is passed to `run_synthetic`, 4A forecast/score construction,
or a model. Those contracts and model mathematics remain unchanged. A
future historical execution bridge must preserve the approved 5B projection
semantics, including strict blocking of fields outside 4A's OHLCV vocabulary
and the endpoint-only quality scope. `ready_for_architect_review` means only
the read-only audit is ready for review; `execution_ready=false` remains explicit.
The approved policy and 5C compatibility layer below do not provide or
authorize that execution bridge.
Historical PIT remains unverified, Lane B and backtesting remain blocked,
and no fit, forecast, score, metric, output file or dashboard route is
produced by this adapter.

## PQTA-003D-5C historical projection compatibility — no execution bridge

`src/quant/research/historical_projection.py` is implemented; Architect review
is pending. It applies approved policy `pqta-003d-5b-projection-v1` in a
separate read-only layer around the lossless 5A representation. The
[5B design](PQTA-003D-5B_HISTORICAL_PROJECTION_POLICY.md) remains the policy
authority, not a historical execution or reporting interface.

The public boundaries separate `verify_pinned_source(root)` from
`bind_synthetic(adapter)`. The former uses the existing pinned-history
verification path and binds exact source identities/bytes to an authenticated
receipt; the latter labels in-memory fixtures synthetic, never authenticated
history. Neither caller-supplied verification flags nor valid SHA-256 syntax
can establish authenticated bytes. Byte authentication remains separate from
unverified anomaly-evidence completeness and publication availability.

`plan_forecast_fields` exposes only current feature/time fields and an opaque
source reference, without an outcome attachment or resolver.
`plan_completed_history` checks `h+1h <= forecast_origin` before target/flag
access, preserving exact hourly adjacency and the approved retrospective
A-sensitivity training/current-input masks. `project_closed_outcome` produces
a supported closed-outcome projection with its mandatory lossless audit
attachment; feature-window evidence remains separate from target-endpoint-only
4A Quality. Explicit `feature_complete` and `ar_lag_valid` are retained, not
silently inferred from constructor defaults.

`audit_compatibility` returns deterministic canonical report bytes and a
payload digest in memory. It retains every requested origin and distinguishes
`compatible`, `blocked`, `failed`, `audit_only` and `not_closed` projection
classifications from existing forecast/score/abstention vocabularies. The final
out-of-split row remains audit-only. Raw `candle` and `unknown` fields are never
translated, removed or disguised as model abstentions. Unsupported required
records, unknown anomaly types or unresolved associations block the requested
scope; no reduced-universe metrics are permitted.

All outputs retain `execution_ready=false`, `point_in_time_verified=false`
and `decision_eligible=false`. There is no model call, historical runner,
synthetic guard bypass, historical reporting, artifact writer or dashboard
integration. Historical execution needs separate authorization; reporting is
deferred pending its own reviewed interface. Run the synthetic compatibility
tests in `pqta` with `python -m pytest -q tests/test_historical_projection.py`.

## PQTA-003D-5E native historical anomaly representation — audit-side only

Status: **Implemented; Architect Review Pending.**
`src/quant/research/historical_representation.py` implements the separately
approved [5D design](PQTA-003D-5D_UNSUPPORTED_ANOMALY_REPRESENTATION.md),
without changing ADR-5D-01–06, 4A Quality/Outcome/Score, the 5B/5C policy,
models or the synthetic runner. Exact interfaces and canonical schema are
recorded in the [5E implementation contract](PQTA-003D-5E_IMPLEMENTATION_CONTRACT.md).
The approved 5D document remains the design milestone's historical record;
5E's separate implementation authority does not authorize execution.

The native schema `pqta-historical-anomaly-representation-v1` and policy
`pqta-003d-5d-representation-v1` reuse the existing lossless historical
envelope. Typed occurrences retain raw values, original field tokens,
source column, endpoint/window/unresolved association, original collection
positions and multiplicity. The seven literals are `open`, `high`, `low`,
`close`, `volume`, `candle` and `unknown`, with the existing manifest's
type/token restrictions. Neither `candle` nor `unknown` is expanded into
OHLCV, numeric missingness, generic eligibility or an inferred association.
Unknown semantic vocabulary is retained as opaque audit evidence, not
silently accepted under v1. Missing, ambiguous or contradictory linkage is
reported explicitly rather than enriched from a plausible timestamp.

`verify_pinned_representation_source` reuses the approved source-bound
receipt verifier and binds exact raw manifest references. The separate
synthetic factory cannot authenticate historical bytes. Copied receipts,
reconstructed contexts or caller-supplied Booleans/hash strings do not mint
that binding. This is an in-process integrity boundary, not a signature or
hostile-Python sandbox. Matching manifest/source bytes authenticates the
recorded claim, not external anomaly evidence or publication availability.

`represent_closed` and `audit_native` are audit-side only. Before theoretical
target closure, they do not inspect current/future outcome values, flags,
attachments or anomaly diagnostics. The final out-of-split origin remains
audit-only; its separate closure dimension is not hidden by that label.
No native envelope, source context, manifest or outcome resolver is added
to forecast-only plans. No model, fit, forecast, scoring or historical
evaluation interface is introduced.

Each audit reports independent native representability, legacy 4A
compatibility, source authentication, association resolution, evidence
completeness and temporal closure. The unchanged 5C compatibility result
is a separate target-schema result, not a native acceptance threshold.
Representable raw unresolved associations may still block any interpretation
requiring a definite dependency role. All requested origins remain counted.

Serializer `pqta-003d-5e-canonical-v1` uses compact sorted-key UTF-8 JSON
ending in one LF, six-digit UTC `Z` timestamps, finite round-trip binary64
numbers and preserved `-0.0`, original arrays, nulls and absent fields. New
`representation_spec_id`, `representation_build_id` and `payload_sha256`
separate logical source/scope policy, code/dependency/serializer build and
canonical bytes. Runtime timestamps do not enter logical identity. Existing
dataset/build IDs, 5C serialization and comparison digests remain unchanged.
The audit returns canonical bytes in memory and writes no artifact.

Historical scoring/accounting/reporting remain deferred under ADR-5D-06,
and historical execution needs separate owner authorization. Native audit
acceptance is not model eligibility, historical evaluation completion or
live-trading evidence. `execution_ready=false`, `point_in_time_verified=false`
and `decision_eligible=false` remain mandatory. Acceptance passed 112 new
synthetic tests and the full 928-test regression, lint/format, dependency and
protected-integrity checks. A read-only full-origin scan retained all 50,845
origins (50,844 native representations and one uninspected audit-only origin);
39 canonical anchor origins were independently repeated byte-for-byte. The
[acceptance findings](MODEL_EVALUATION.md#read-only-acceptance-findings) distinguish
the complete semantic scan from bounded canonical payload verification and
the initial incomplete time-bounded attempt. No evaluation artifact was written.

## Data boundaries

- Data moves forward through layers; downstream outputs must be reproducible
  from versioned code and recorded inputs.
- Silver and Gold datasets must use timezone-aware UTC timestamps.
- Completeness checks must prevent unfinished candles from entering signals.
- Validation precedes consumption by feature, strategy, model, and backtesting
  work.
- No architecture component may submit orders; the final step is manual trading.
