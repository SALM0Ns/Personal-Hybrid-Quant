# PQTA-003D-6A — Native Types and Validation Implementation

**Status: PQTA-003D-6A — CORRECTED, AWAITING FINAL ARCHITECT REVIEW**

This milestone implements only Stage A of the approved
[native scoring/accounting contract](PQTA-003D-5G_NATIVE_SCORING_ACCOUNTING_IMPLEMENTATION_CONTRACT.md).
It provides immutable data records, strict validators and canonical data-only
serialization. It does not execute a model, inspect a live historical outcome,
classify a score, reconcile an execution, compute metrics, publish results, or
create trading functionality.

## Implemented boundary

[`historical_scoring_contract.py`](../src/quant/research/historical_scoring_contract.py)
defines:

- `HistoricalProvenanceRef`, `HistoricalOriginRef` and `HistoricalScopeSpec`;
- `HistoricalForecast` and the pure-data `ScoreClassification` schema;
- `HistoricalOutcomeView`, `HistoricalScore`, `AccountingReconciliation`,
  `HistoricalAccountingResult` and `HistoricalScopeBlock` as non-authoritative
  validated data schemas;
- validators for approved versions, source identity, UTC/hour alignment,
  periods, exact source-ledger membership, finite values, reason ordering,
  parent/child identity and count conservation; and
- deterministic canonical JSON, logical specification, build, record and
  payload identities.

Every public authentication/completion property is false, and
`public_authority_issuers()` is empty. A caller-provided digest, source-mode
label, Boolean, or serialized descriptor cannot authenticate source bytes,
forecast production, score issuance or completed historical accounting.

When complete forecast and classification records are supplied,
`validate_reconciliation()` recomputes all emission and final-score counts,
exclusive abstention and primary-score reason counts, overlapping diagnostic
counts, coverage, the exact sorted scored-origin set, and its timestamp digest.
It compares every derived value with the immutable reconciliation declaration;
balanced but inaccurate summaries fail closed. Exact source/scope/spec/build,
model/sample, origin-order, forecast-ID and classification-parent relationships
are checked before summaries. Audit-only origins cannot enter the declared
evaluation universe.

Structural scope validation and exact comparison with a caller-supplied source
ledger remain data-integrity checks. Neither authenticates pinned historical
bytes; only a separately reviewed live source authority could establish that.

## R-A01 — nonrecursive scoring specification identity

`scoring_spec_id` hashes the exact logical specification:

- governing schema, policy, protocol, dataset, projection and native-contract
  versions;
- the approved source provenance record;
- period boundaries, fixed analysis boundary and intended use;
- timestamp and exact source-ledger identity-set digests, including the
  separate audit-only identity-set digest;
- ordered model and sample identities; and
- the frozen Ridge selection identity when Test Ridge is in scope.

The canonical input deliberately excludes the stored `scoring_spec_id`, result
values, runtime clocks, code/dependency versions and build configuration.
Equivalent specifications therefore reproduce the same identity; any changed
semantic input changes it; and an incorrect supplied identity is rejected.

## R-A02 — exact forecast parent binding

`ScoreClassification.forecast_id` is mandatory. Parent validation compares it
with the exact immutable `HistoricalForecast.forecast_id` and also checks the
origin, model, sample, emission status, prediction and abstention reasons.
Because the forecast identity covers the full forecast record, substitution of
a forecast with a changed prediction, abstention reason, producer trace, build
identity or other parent field is rejected even when origin/model/sample match.

This is an integrity relationship only. It is not producer authentication and
does not authorize construction of an authenticated historical score.

## Canonical serialization

Canonical payloads use UTF-8 JSON with sorted keys, compact separators and
exactly one trailing LF. UTC-equivalent timestamps are normalized to six-digit
microsecond `Z` form. Null and absent values remain distinct, signed zero is
preserved, and native anomaly arrays retain order and multiplicity. Duplicate
JSON keys, nonfinite numbers, paths, bytes, callables and unsupported objects
are rejected.

`scoring_spec_id`, `scoring_build_id`, record-level IDs and `payload_sha256`
are separate. A reusable build identity may produce multiple payload digests.
Digest agreement proves deterministic byte/data integrity, not execution or
producer authority.

`CanonicalScoringBundle` enforces the exact §12 field set and exactly one of a
pure reconciliation, historical-accounting schema, or scope-block terminal.
Its authenticated-history property is always false; loading or validating its
bytes cannot recreate source, outcome, producer, execution, or completion
authority.

## Deferred authority and execution

The live `ClosedHistoricalOutcomeRef` capability issuer is intentionally not
implemented because a public constructor would create an unauthorized outcome
access path. Stage A likewise exposes no scoring or reconciliation kernel and
no historical score/accounting factory. `HistoricalScore` and
`HistoricalAccountingResult` are schemas that always report unauthenticated
issuance/completion.

Stage B and every historical execution, scoring, reconciliation, metric,
reporting, dashboard, signal and trading activity require separate review and
Project Owner authorization.
