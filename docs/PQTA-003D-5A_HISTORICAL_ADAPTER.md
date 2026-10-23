# PQTA-003D-5A — Read-Only Historical Adapter and Readiness Audit

## Architecture decision and pre-implementation mapping

The owner approved a lossless historical representation, not a projection
into PQTA-003D-4A `Quality`/`Outcome`. Original `candle` and `unknown` fields
remain unchanged. Target-endpoint and feature-window anomaly records remain
separate; an association unsupported by its source column is `unresolved`.
The 4A contracts, synthetic runner and model mathematics are unchanged.
There is no historical execution bridge, fit, prediction, score or publisher.

Approved sources and immutable byte identities are recorded in
[PQTA-003C_DATASET_IMPLEMENTATION.md](PQTA-003C_DATASET_IMPLEMENTATION.md).
The adapter reads BTC/USDT Silver, QNT-002B candidate Gold, the canonical
candidate manifest, and the four files in the published origin-build
directory only. It must not invoke the dataset builder or feature engine.

| Source field | Lossless historical mapping / gate |
| --- | --- |
| `forecast_origin_utc`, `feature_open_t` | Preserve; require exact `origin - 1h` alignment. |
| Seven named feature columns | Preserve nullable values in canonical `FEATURES` order; reject schema/order drift. |
| `null_reason__*`, `feature_complete` | Preserve; validate finite values/null reasons against existing Gold contracts. |
| `target_next_1h_log_return`, `target_valid`, `target_null_reasons`, primary reason | Preserve original value, lexical reason order and primary reason; independently audit against exact Silver keys using existing target-audit semantics. No 4A reason projection. |
| `target_endpoint_anomalies` | Preserve raw records under target-endpoint association; compare to exact manifest endpoints. |
| `involved_anomalies` | Preserve raw feature-window records separately; compare to approved dependency windows. |
| `anomaly_involved_features`, `feature_manifest_anomaly` | Preserve canonical feature order and separate feature mask. |
| `ar_lag_valid`, `ar_lag_manifest_anomaly` | Audit exact Silver opens `t-1h,t`, never current/future outcome metadata. |
| `lane_a_primary`, `lane_a_sensitivity` | Preserve target-only eligibility; these do not assert model-specific eligibility or tradability. |
| `split_id` | Validate protocol boundaries; retain the final out-of-split audit row separately from three period universes. |
| Source IDs, hashes and original ledger row | Preserve alongside source row index and timestamp identity. Verify pinned bytes before Parquet inspection. |
| `gold_available_at`, `gold_decision_eligible` | Require existing unknown/false state; no publication evidence is invented. |

The source schema and manifests establish these associations. Raw anomaly
tokens outside the 4A OHLCV vocabulary are recorded as a deferred projection
requirement, not silently normalized. Evidence references are preserved;
source-byte verification does not verify referenced anomaly evidence.

## Public API and readiness scope

`historical_adapter.audit_pinned_history(root) -> HistoricalAudit` checks
the independently approved file hashes before parsing verified Parquet
bytes. The four-file artifact set, provenance sidecar/canonical JSON,
logical dataset identity, recorded build inputs and builder-content identity
are checked against the existing PQTA-003C contracts. No writer, database,
feature recalculation, builder or model is called.

`audit_frames(silver, gold, ledger, manifest, *, identity)` is the pure
in-memory semantic test boundary. It cannot authenticate caller-supplied
digests: its valid result is blocked on file-byte verification. It checks
existing schema/order, exact source joins, temporal closure, null-reason
continuity, target values/reasons, period assignment and anomaly masks.
Target arithmetic is checked against existing Silver values, not published
as a new target dataset; copied adapter values are the original ledger values.

`HistoricalAudit` exposes an optional `HistoricalAdapter`, a structured
report, and canonical UTF-8 JSON bytes (the existing sorted compact JSON
format with trailing LF). Invalid input returns `failed` with no adapter.
The report has version `pqta-003d-5a-readiness-v1`. It distinguishes hash
syntax, checked file bytes, matched identities and a complete **local
source identity chain** from unverified anomaly evidence and historical PIT.

The adapter retains every audit row, its original index/key, a deeply
read-only copy of all ledger fields and the full typed manifest. Separate
feature and outcome objects preserve original nulls/reasons and raw nested
anomaly fields. They are not synthetic fixtures or 4A `Outcome` instances.
`HistoricalFeatures.forecast_fields()` exposes no target or future quality
fields. It is an inspection view, not an execution bridge or PIT certificate.

`associate_anomaly(raw, *, source_column, source_row_index)` preserves raw
records from unsupported association columns as `unresolved`. The strict
ledger schema is not expanded: unknown ledger columns fail closed. Approved
source columns establish endpoint versus feature-window association even
though the anomaly's evidence completeness and cause remain unresolved.

Successful pinned inspection is `ready_for_architect_review`, scoped to
this read-only adapter. `execution_ready=false` is unconditional. Projection
into 4A still requires a reviewed field/association policy; historical
execution requires separate authorization, and PIT remains unverified.
Non-OHLCV fields `candle` and `unknown` are listed as deferred projection
requirements. Evidence references are preserved but their referenced files
are not authenticated in this milestone. No historical audit/evaluation
output is written; the report exists only in memory.

Status: Implemented; Architect review pending. Historical execution is not
authorized. No dependency or research-protocol change is required.

## Software validation

The 62 synthetic adapter tests passed, including lossless anomaly metadata,
schema/order/identity and mask failures, immutable source preservation,
reader hash gates before parsing, synthetic temporary-source verification,
no model/runner/builder calls, canonical output and the unchanged synthetic
fixture guard. The complete suite passed 759 tests in 12.65 seconds using
the `pqta` environment with loopback permission for the existing HTTP test.
Ruff lint/format, `pip check` and Git whitespace checks passed. No historical
model was fitted or evaluated by adapter validation.
