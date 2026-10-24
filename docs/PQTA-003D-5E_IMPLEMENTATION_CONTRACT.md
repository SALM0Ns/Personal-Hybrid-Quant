# PQTA-003D-5E — Native Representation Implementation Contract

Status: Implemented; Architect Review Pending. Internal Phase A contract review
was completed before production-code changes; acceptance evidence is recorded
in the evaluation documentation after validation.
Governing approved design: [5D](PQTA-003D-5D_UNSUPPORTED_ANOMALY_REPRESENTATION.md),
unchanged `qnt-003d-design-v1` and `pqta-003b-origin-ledger-v1`.
Implementation/testing is authorized for 5E only; historical execution is not.

## 1. Contract review and public API

Use one module, `quant.research.historical_representation`, over existing
immutable `HistoricalRecord` / `HistoricalOutcome` / `HistoricalAnomaly` objects.
No 4A vocabulary, model, synthetic runner, score/report contract, 5B policy or
5C serializer is changed. The approved 5D document remains unchanged.

```text
SCHEMA_VERSION = pqta-historical-anomaly-representation-v1
POLICY_VERSION = pqta-003d-5d-representation-v1
SERIALIZER_VERSION = pqta-003d-5e-canonical-v1

NativePolicy(schema_version, policy_version, serializer_version)
ManifestReference(source_identifier, canonical_sha256, raw_sha256, manifest_version)
NativeSource(binding: SourceBinding, manifest_reference: ManifestReference)
NativeOccurrence(source_ref, collection, position, association, source_column,
                 raw, linkage, manifest_record_index, manifest_record_sha256,
                 manifest_record)
NativeDimensions(native_representability, legacy_4a_compatibility,
                 source_authentication, association_resolution,
                 evidence_completeness, temporal_closure)
NativeEnvelope(record: HistoricalRecord, occurrences: tuple[NativeOccurrence, ...])
NativeResult(source_ref, period, dimensions, findings, envelope | None)
NativeAudit(report: read-only Mapping, canonical_report: bytes, payload_sha256: str)

verify_pinned_representation_source(root: Path) -> NativeSource
bind_synthetic_representation(adapter, *, manifest_bytes: bytes | None = None)
    -> NativeSource
represent_closed(source, origin, *, checked_at, policy=NativePolicy()) -> NativeResult
audit_native(source, *, checked_at, origins=None, policy=NativePolicy()) -> NativeAudit
canonical_payload(value) -> bytes
representation_spec_id(spec: Mapping) -> str
representation_build_id(spec_id, *, code_sha256, dependency_versions,
                        serializer_version=SERIALIZER_VERSION) -> str
```

These are audit-side interfaces, not execution/forecast/scoring interfaces.
There is deliberately no native forecast API, label-admission API or writer.
The existing forecast-only plans are not widened or given native attachments.
Identity helpers hash specifications; caller-supplied IDs never authenticate data.
The build helper can identify an explicitly supplied future serializer version;
it does not enable that serializer. Actual audit policies accept only the
approved schema/policy/serializer triple above.

## 2. Exact native schema and occurrence semantics

All dataclasses are frozen. Source contexts require private factory membership;
constructing or copying a dataclass does not authenticate it. A registered
context retains the exact existing binding, exact raw manifest bytes, decoded
raw manifest mapping, typed manifest and immutable manifest reference.

| Field | Type and rule |
| --- | --- |
| `source_ref` | Existing `OpaqueSourceRef`: exact dataset/build/receipt IDs, source identifier, integer row index and aware hourly UTC origin. |
| `collection` | `target_endpoint_anomalies`, `feature_window_anomalies` or `unresolved_anomalies`; collections remain separate. |
| `position` | Nonnegative integer original position within that collection; never deduplicated. |
| `association` | `target_endpoint`, `feature_window` or `unresolved`, as recorded; no inference from anomaly tokens. |
| `source_column` | Original nonempty string; known endpoint/window columns must match their source role. |
| `raw` | Deeply read-only complete original annotation mapping, preserving extra keys, original values, absent keys, explicit nulls and arrays. |
| `linkage` | `matched`, `missing`, `contradictory` or `unknown_vocabulary`; never guessed. |
| `manifest_record_index` | Original raw manifest array index for a unique matched timestamp/type key, else null. |
| `manifest_record_sha256` | Digest of that exact raw record's canonical JSON, retaining its original timestamp strings, else null. |
| `manifest_record` | Full original raw manifest record mapping for a match, including original timestamp strings/evidence/nullable details, else null. |

The seven literal tokens are `open`, `high`, `low`, `close`, `volume`,
`candle`, `unknown`. `missing_hour` permits exactly `candle`; other existing
types (`source_discrepancy`, `shortened_close`) permit OHLCV/`unknown` only.
Do not expand `candle`, interpret `unknown` as null, or infer numeric validity.
Empty, non-string or duplicate affected-field names are invalid. Known invalid
type/token combinations fail native validation. Future unrecognized semantic
types/tokens remain opaque in retained raw evidence and block native semantic
representability; they are not new accepted manifest vocabulary.

Manifest parsing rejects duplicate JSON keys, nonfinite numbers, invalid
manifest schemas and duplicate timestamp/type identities. Annotation links use
that exact timestamp/type key. Compare every supplied reduced annotation field
to the manifest's corresponding summary, including affected-field membership,
severity, review status and evidence references. Also compare supplied known
full-manifest fields, including manifest version, close metadata, coverage basis
and evidence hashes/times; UTC normalization is comparison-only, not a rewrite.
Unknown extra opaque keys remain preserved without invented interpretation.
Missing required linkage information blocks rather than guessing; contradiction
is an explicit integrity failure. Absent required keys remain absent (blocked),
distinct from present malformed values (failed); the legacy dimension may fail
on a partial annotation while native representation independently blocks it.
No positional fallback, token expansion or enrichment is permitted. Typed
manifest records and raw manifest array order are both retained. Record matches
do not verify referenced evidence bytes or root causes.

Collections concatenate in the fixed order endpoint, window, unresolved; each
keeps its original positions/multiplicity. Original row values/reason arrays
are retained unchanged in the existing record, not flattened or recalculated.
Native envelopes are audit-side and never 4A `Outcome`/`Quality` objects.

## 3. Independent dimensions and failure behavior

| Dimension | Values and interpretation |
| --- | --- |
| `native_representability` | `represented`, `blocked`, `failed`, `not_inspected`. Unsupported native semantics or non-unique/missing linkage block; contradictory linkage and invalid structure fail. |
| `legacy_4a_compatibility` | Existing 5C classification from the unchanged closed-outcome compatibility function; not native eligibility. |
| `source_authentication` | Existing factory receipt mode: `authenticated_pinned_history` or `synthetic_fixture`. Synthetic never upgrades. |
| `association_resolution` | `resolved`, `unresolved`, `not_inspected`. Raw unresolved association is representable, but required dependency interpretation remains blocked. |
| `evidence_completeness` | `recorded_references_unverified`, `unresolved_linkage`, `no_occurrences`, `not_inspected`. None means independent evidence verification. |
| `temporal_closure` | `closed` or `not_closed`, from clocks only. Independent of audit-only status and publication evidence. |

Source/context/schema/policy authentication failures raise `ValueError` before
a trusted native result is produced. Closed-row semantic/structural failures
are explicitly counted per origin; no row is dropped. Required linkage issues
return blocked findings while preserving raw occurrences. Unresolved roles
remain visible separately even when all raw metadata is representable.

At every scope/result, execution readiness, PIT verification and decision
eligibility remain false. These dimensions do not implement method/sample
eligibility, historical scoring, a new abstention reason or a model filter.

## 4. Authentication and temporal review

The pinned factory calls the existing `historical_projection.verify_pinned_source`
and checks the registered source state. It separately reads the manifest bytes,
strictly decodes/validates them and requires canonical digest/version equality
with the bound identity. The raw-byte hash is observed and bound in the native
context, not claimed to be a pre-pinned hash in the legacy receipt. No other
factory accepts caller proof of historical authentication.

The synthetic factory uses `bind_synthetic` with an explicit adapter and optional
raw manifest bytes. Hash/record validation does not turn that fixture into
authenticated history. Registered native context identity, original binding,
receipt/manifest references and post-closure record digests are checked on use.
Copies, substitutions, forged flags and tampering fail closed. This is an
in-process integrity boundary, not a hostile-Python security sandbox/signature.

`represent_closed` validates only source/clock/key identity before closure.
For `origin + 1h > checked_at`, return no envelope, no occurrence diagnostics,
no target/validity/anomaly access or full-row digest traversal. An out-of-split
origin also has no envelope; its independent closure axis still reflects its
clock (the final historical audit origin is not closed at the source cutoff).
Raw audit sources remain retained in the separate source context. No source
context/full manifest/envelope/resolver is added to forecast plans.

The guard is `outside_approved_split OR target_not_closed`, not a claim that
the final origin fails the native schema. At origin `2026-10-20T13:00:00Z`,
checked at 13:00, its target closes at 14:00: native representability is
`not_inspected`, legacy compatibility `audit_only`, closure `not_closed`,
association/evidence `not_inspected`, envelope null and findings `audit_only`.
At checked-at 14:00, closure becomes `closed` but all those other fields remain
unchanged: the origin is still outside Test and no outcome is inspected.
Source authentication is independently retained from the registered binding.

After closure, validate the exact bound record and use unchanged 5C compatibility
for the legacy axis, without converting the native envelope to a score input.
All approved exact adjacency, target/feature masks, A-primary/A-sensitivity,
reason priorities, refit and frozen-alpha contracts remain unchanged. No model
is called. Historical availability stays null, not derived from closure.

## 5. Canonical bytes and exact audit payload

Canonicalization: Python 3.12 standard-library JSON; UTF-8 (`ensure_ascii=False`),
lexically sorted string object keys, compact separators, `allow_nan=False`, one
final LF. Dataclasses become objects; immutable mappings become objects; tuples
and lists become arrays in their original order. Aware zero-offset timestamps
encode `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Original raw manifest timestamp strings
remain strings. Only null, exact bool/int/finite float/string values are accepted.
Binary64 floats use Python's round-trip JSON number representation without
rounding; `-0.0` remains `-0.0`. Integers are not silently converted to floats.
Absent map keys remain absent, distinct from present JSON null. Bytes are not
coerced to text/base64; source bytes are retained separately and referenced by
exact hash/identifier. No runtime timestamp enters any logical payload.

The complete audit object has exactly these top-level keys:

```text
target_schema, policy, schema_version, policy_version, serializer_version,
source_identity, source_receipt_sha256, source_authentication,
manifest_reference, scope,
representation_spec_id, representation_build_id, build,
dimension_counts, rows,
research_only, execution_ready, point_in_time_verified, decision_eligible,
anomaly_evidence_verified, limitations, payload_sha256
```

`scope` has `origins` (sorted unique aware hours bound to the original timeline)
and `checked_at` (fixed aware hour). `rows` contains the same sorted origins,
each a canonical `NativeResult` with exactly its dataclass fields above.
`NativeEnvelope.record` serializes the original existing HistoricalRecord;
`occurrences` carries typed separate role/position/raw/linkage fields above.
No envelope is serialized for pre-closure/audit-only results.
`dimension_counts` has one sorted value/count map per dimension, each summing
to the declared origin count, including empty scopes. Audit-only rows are
counted, never evaluation-scheduled. No forecast or score counts are invented.

`manifest_reference` has exactly the four fields in §1. The complete raw
manifest bytes/mapping remain in the registered audit context, not a
forecast-facing payload; matched full raw records are attached only to closed
envelopes. `build` has `code_sha256`, `dependency_versions`, `serializer_version`.
Readiness flags and `anomaly_evidence_verified` are false; `research_only` true.
`limitations` is a fixed ordered list of the declared authority/evidence limits.
The canonical report includes `payload_sha256`; its digest hashes the canonical
object with that one field omitted. No report/artifact file is written.

## 6. Identity review

The logical spec hashes exactly schema/policy versions, unchanged protocol and
dataset contracts, full existing source identity, source receipt's byte-hash
references (not its digest or implementation-derived audit report), manifest
reference, fixed scope/closure boundary and preservation rule version. Code-only
changes preserving those inputs and the approved canonical-spec encoding do not
change the spec. A non-authentication mode marker distinguishes synthetic
assertions from pinned-source specifications.

Spec stability assumes fixed logical inputs and the unchanged approved
canonical-spec encoding. No runtime clock is automatically sampled. The
explicit `checked_at` cutoff is a semantic scope input: changing it deliberately
changes spec, build and payload identities. Changed source byte references,
including observed raw-manifest SHA-256, likewise change the relevant identities.
This is not invariance to arbitrary future serializer/canonicalization changes.

The build hashes spec ID, code-content digest, dependency versions and explicit
serializer version. Code content includes this module and its reused source,
manifest, dataset/protocol/compatibility/accounting contracts; no Git working
tree path or runtime clock is included. The same canonical source spec with different code
changes build identity, not spec identity. Actual payload bytes independently
determine `payload_sha256`. No source dataset/build ID or old canonical/comparison
encoding is overwritten. No immutable artifacts are published by this module.
The serializer-version identity test changes the build helper's declared version
input, not the executing audit codec. Actual `NativePolicy` accepts only the
approved version triple. A future serializer migration needs review and may
also change canonical spec bytes; code-only stability is not a blanket
serializer-migration guarantee.

After complete validation/serialization, a private process-local map binds each
representation build ID to its payload digest. Deterministic repeats are allowed;
conflicting payload bytes fail closed before returning a NativeAudit, preserving
the original entry. This also catches conflicting synthetic assertions under
identical source IDs. It is not persisted/cross-process immutability verification;
a future publisher still needs separately reviewed artifact-byte validation.

Evidence counters count distinct requested source-bound origins, once per
`NativeResult`, not anomaly occurrences, manifest records or evidence references.
After successful core validation, an origin with one or many matched occurrences
receives one `recorded_references_unverified` classification. Zero occurrences yields
`no_occurrences`; unmatched linkage yields `unresolved_linkage`; uninspected
origins retain `not_inspected`. These are independent of legacy compatibility
and never certify referenced evidence bytes. Numerically equal counts in a
particular snapshot do not establish equal sets or a cross-dimension invariant.

## 7. Review acceptance criteria

Internal review found no need to change ADR-5D-01–06. Implementation can proceed
under the explicit 5E authorization; it is not historical execution approval.

Acceptance requires synthetic tests for literal/type validation, roles and
multiplicity, absent/null/signed-zero retention, exact source/manifest linkage,
ambiguous/contradictory links, forged/copied contexts, deterministic and separate
identities, independent native/legacy counts, closure non-access, unchanged
forecast/synthetic guards, gaps and full-universe accounting. No model, scoring,
historical publisher or forecast/score ledger may be invoked or created.
Full regression, lint/format, dependency, documentation and protected-hash gates
remain required before returning for Architect review. No Git publication is
authorized.
