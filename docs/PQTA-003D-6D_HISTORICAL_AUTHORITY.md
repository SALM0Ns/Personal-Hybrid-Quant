# PQTA-003D-6D — Historical Source and Closed-Outcome Authority

Status: **PQTA-003D-6D — IMPLEMENTED, AWAITING ARCHITECT REVIEW**

## Scope

[`historical_authority.py`](../src/quant/research/historical_authority.py)
implements the separately authorized Stage D source/outcome boundary under
[`qnt-003d-design-v1`](QNT-003D_FINAL_RESEARCH_DESIGN.md),
[`pqta-003b-origin-ledger-v1`](PQTA-003C_DATASET_IMPLEMENTATION.md), and the
[approved 5G contract](PQTA-003D-5G_NATIVE_SCORING_ACCOUNTING_IMPLEMENTATION_CONTRACT.md).
It grants explicit inspection of a particular theoretically closed outcome.
It does not grant authority to run a model, issue a forecast or historical
score, or complete historical accounting.

Stage A/B/C data contracts and fixed-false authority properties remain
unchanged, apart from the narrowly approved provenance correction below.
The synthetic scoring/accounting entry points still reject historical use.
No historical runner, metric bridge, publication, dashboard integration,
signals, backtesting, or orders are implemented by Stage D.

## Public interface

| API | Purpose and boundary |
| --- | --- |
| `open_verified_native_source(root, *, policy_version=...)` | Read and verify the approved pinned source chain; return an opaque `HistoricalSourceContext`. No supplied receipt, digest, adapter, or authentication flag is accepted as authority. |
| `source_provenance(context)` | Return a validated data-only `HistoricalProvenanceRef`; possession of it grants no authority. |
| `evaluation_origins(context, period_id)` | Return exact immutable-ledger origin references for the requested period without inspecting target values, validity, or anomalies. The audit-only period remains separately inspectable. |
| `validate_historical_scope(context, scope, *, policy_version=...)` | Validate the declared scope against the exact verified ledger identity set and its separate audit-only set. This does not authorize execution. |
| `issue_closed_outcome(context, scope, origin_ref, *, checked_at, policy_version=...)` | Check source, scope, origin, theoretical closure and native representation before issuing a registered `ClosedHistoricalOutcomeRef`. Boundary failures raise without returning target diagnostics. |
| `inspect_closed_outcome(context, scope, capability, *, policy_version=...)` | Explicitly resolve the exact registered capability to a validated, read-only `HistoricalOutcomeView`; recheck bindings and payload digests. The view itself remains data-only. |
| `describe_closed_outcome(capability)` | Return an explicitly untrusted descriptor containing safe identity, clocks and digest fields; never reconstruct authority. |
| `invalidate_source(context)` | Revoke that context and its dependent outcome capabilities within this process. |

## Source verification and provenance

Opening a context reuses the existing read-only chain:

```text
5A pinned artifact reader and validation
  → 5C source receipt and exact row binding
  → 5E raw/canonical manifest binding and native representation
  → Stage D private source-context registry
```

The reader recomputes approved Silver, Gold, origin-ledger, validation,
provenance, sidecar and canonical manifest digests from actual bytes. Existing
schema, contract-version, feature-order, timeline, source-identity and
quality-mask validation remains in force. The native binder separately reads
the manifest representation, validates its canonical identity and binds the
observed raw bytes and their recomputed digest. This does not invent an
independently approved raw-byte pin or independently verify the referenced
anomaly evidence.

The source receipt authenticates the snapshot read, not all subsequent
filesystem states. Reopening a context re-verifies sources. Caller-supplied
hashes, syntactically valid identifiers and Boolean claims cannot mint source
or outcome authority. Source authentication does not prove model execution,
producer authority, historical publication time or point-in-time availability.

### Stage A digest-role correction

`HistoricalProvenanceRef` now permits distinct required digest roles to carry
the same valid SHA-256 value. The pinned manifest's raw representation is
already canonical, so those two roles legitimately have equal values. The
validator still enforces exact required fields, unique role names through the
strict record/JSON interfaces, valid lowercase digests, source versions and
feature order. Canonical serialization and specification derivation are
unchanged. Equality of caller-supplied digests does not establish equality or
authentication of source bytes; verification must recompute relevant digests.

## Exact origin membership and closure

The context derives origin references from verified source records rather
than synthesizing an hourly range. Missing-hour, invalid, anomalous,
unrepresentable and unscorable origins remain in the declared evaluation
universe. Scope validation requires exact source-ledger identity-set equality,
including source row/key, provenance, period and timestamp identities; matching
counts alone is insufficient. Audit-only origins remain separate and cannot
receive outcome capabilities.

For forecast origin `o`, the source candle opens at `o - 1h`, and the target's
theoretical close is `o + 1h`. `checked_at` is an explicit aware, hour-aligned,
zero-offset timestamp. Capability issuance requires
`checked_at >= o + 1h`; an origin at `2026-10-20T13:00:00Z` therefore cannot
have its outcome inspected at that same timestamp and remains audit-only.

Source/session, scope, origin membership and closure checks precede outcome
traversal at the capability interface. The underlying audit-side source
verifier necessarily reads and validates the historical artifacts when
opening the context; it is not a forecast-origin input interface. No target,
target-validity or target-anomaly data is returned through the identity-only
APIs or pre-closure failure diagnostics.

Theoretical closure is a mathematical boundary, not evidence of exchange
publication. Existing Gold `available_at=null` and `decision_eligible=false`
remain unchanged. Stage D does not make Lane B, trading or backtesting ready.

## Native anomaly and outcome preservation

Successful issuance requires a represented, theoretically closed native
result, resolved required associations, and matched required manifest links.
An unresolved association, missing/contradictory linkage, malformed outcome,
or changed source binding fails closed. This is a boundary failure, not a
model abstention or an invented score row.

Literal `candle` and `unknown`, raw fields and values, endpoint/window roles,
source references, collection order, positions and multiplicity are preserved.
They are not translated into OHLCV fields. A feature-window anomaly alone
does not globally invalidate a target; native representability is independent
of legacy 4A compatibility. The approved A-primary/A-sensitivity rules are
not changed or executed here.

Legitimate source-invalid targets retain null values and their explicit
invalid reasons. Original lexical reason order is retained separately from
the existing approved reason priority. `target_value_sensitive` is copied
when present, otherwise left null rather than inferred. Anomaly evidence
remains `recorded_references_unverified` when occurrences exist; authenticated
source bytes do not upgrade evidence-review status.

## Capability lifecycle and limits

Contexts and capabilities use frozen, identity-equal-only dataclasses and
private weak registries. The live capability binds the exact source context,
scope/specification, origin, target close, checked-at timestamp, native-result
digest and outcome-view digest, plus a private opaque nonce. Public
construction, copying, dataclass replacement, pickling, JSON or a digest alone
cannot register authority. Inspection revalidates the registered context,
scope, native result and exact view; invalidating a context revokes dependent
capabilities. A separately opened context does not inherit existing capabilities.

The descriptor is labeled `untrusted_closed_outcome_descriptor` and includes
only `origin_ref`, `checked_at`, `theoretical_close_at`,
`native_result_sha256`, and `outcome_view_sha256`, plus that label. It contains
no nonce, resolver or source-record access. Loading its data never returns a
registered capability. Returned data-only views retain their Stage A
fixed-false authentication property.

This is a process-local correctness boundary for cooperating Python code,
not a security sandbox against hostile code with access to private objects or
module internals. It provides no persistent registry, cross-process transfer,
restart reconstruction, producer receipt, or execution-completion authority.
The separately deferred historical scoring and accounting wrappers remain
unimplemented.

## Validation boundary

Focused tests use invented temporary artifact files and synthetic negative
cases, including byte tampering, wrong pins, exact scope membership, closure,
native tokens, capability substitution and revocation. Any separately reported
read-only integration check uses the existing pinned artifacts without
running historical models, forecasts, scores, metrics or reporting, and writes
no historical evaluation artifact. Protected dataset and immutable-artifact
hashes, the canonical manifest digest, and the three pre-existing QNT-003
document edits must remain unchanged.
