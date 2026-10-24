# PQTA-003D-5D — Unsupported Anomaly Representation Design

**Status: Approved Design — Not Implemented**

Inspected baseline: `2b630173704c6cd8502c8cd8f1ca98567e113cad` on `main`.
Governing protocol: `qnt-003d-design-v1`.
Source dataset contract: `pqta-003b-origin-ledger-v1`.
Unchanged approved compatibility policy: `pqta-003d-5b-projection-v1`.

Architect Design Review passed. This document records the approved architecture
and the approval-in-principle and deferred boundaries in the ADR table in §12.
It does not authorize implementation or historical execution. Project Owner
implementation authorization has not been granted. Design approval,
implementation authorization and historical execution authorization are
separate gates.

## 1. Executive Summary

**APPROVED DESIGN — Alternative B: a separate, versioned historical anomaly vocabulary
over the existing lossless historical envelope.** Reuse `HistoricalRecord`,
`HistoricalOutcome` and `HistoricalAnomaly`; do not widen 4A `Quality`, clone its
scoring implementation, or disguise historical records as synthetic fixtures.

The historical adapter already retains `candle` and `unknown` losslessly. The
unresolved problem is exact interoperability with 4A's narrower vocabulary,
not absent storage for these strings. A historical-native representation can
describe them without asserting that 4A can consume them. Its first purpose
is auditable semantic preservation, not increasing compatible-origin counts.

Keep three independent questions visible:

| Question | Meaning | Not established by a positive answer |
| --- | --- | --- |
| Representation compatibility | Can the complete source metadata be retained under a named target schema? | Clean data, model eligibility, or compatibility with a different schema. |
| Data quality | What was observed, affected, unresolved and supported by evidence? | Numeric invalidity or eligibility for every method/sample. |
| Model eligibility | Do the approved method/sample rules permit a completed training label, current input, or closed-outcome score? | Verified historical publication, decision eligibility, or execution authorization. |

Source authentication is an additional gate: a representable, numerically valid
record may still have unauthenticated bytes. No single `clean` or `compatible`
Boolean may stand for all these questions. The following scope-level state
remains mandatory, even if a future native representation accepts both tokens:

```json
{
  "execution_ready": false,
  "point_in_time_verified": false,
  "decision_eligible": false
}
```

## 2. Existing Contracts and Verified Baseline

### Inspected source facts

| Source | Relevant implemented constraint |
| --- | --- |
| [Historical adapter](../src/quant/research/historical_adapter.py) and [5A contract](PQTA-003D-5A_HISTORICAL_ADAPTER.md) | Typed lossless rows, original source values/nulls, separate endpoint/window/unresolved associations; pinned-byte audit distinct from in-memory assertions. |
| [Historical projection](../src/quant/research/historical_projection.py) and [5B policy](PQTA-003D-5B_HISTORICAL_PROJECTION_POLICY.md) | Strict Fail-Closed v1; source-bound receipts, forecast-only plans and closure-gated outcomes. Unsupported required fields block exact projection. |
| [Forecast accounting](../src/quant/research/forecast_accounting.py) | `Quality` accepts only `open`, `high`, `low`, `close`, `volume`; typed `Outcome` and `Score` do not accept a historical envelope in their place. |
| [Evaluation reporting](../src/quant/research/evaluation_reporting.py) | Synthetic-only evidence/mode guards; valid digest syntax does not authenticate artifact bytes. No historical reporting interface. |
| [Synthetic coordinator](../src/quant/research/model_evaluation.py) | Typed synthetic fixtures, completed-label admission and Test-only frozen-alpha Ridge replay. Not a historical runner. |
| [Evaluation protocol](../src/quant/research/evaluation_protocol.py), [QNT-003B](QNT-003B_EVALUATION_PROTOCOL.md), [QNT-003D](QNT-003D_FINAL_RESEARCH_DESIGN.md) | Exact hourly clocks, separate forecast/score statuses, method-specific sample masks, chronological splits and conservation. |
| [Manifest](../src/quant/features/manifest.py) | `missing_hour` uses the literal `candle`; other supported anomaly types permit OHLCV or `unknown`. Evidence, review, severity and version fields have their own validation. |
| [Evaluation documentation](MODEL_EVALUATION.md) | Historical availability limitations, existing synthetic boundaries, source authentication and deferred historical reporting. |

Relevant inspected tests include [historical projection](../tests/test_historical_projection.py),
[historical adapter](../tests/test_historical_adapter.py),
[evaluation reporting](../tests/test_evaluation_reporting.py) and
[synthetic coordinator](../tests/test_model_evaluation.py). They cover unsupported
fields, association separation, pre-closure non-access, exact lag adjacency,
forged bindings, canonical determinism and synthetic-only guards.

### Established 5C compatibility result — not model results

The approved audit at `2026-10-20T13:00:00Z` reported:

| Classification | Distinct origins |
| --- | ---: |
| Compatible | 49,692 |
| Blocked | 1,152 |
| Failed | 0 |
| Audit-only | 1 |
| Not closed | 0 |
| Total | 50,845 |

Unsupported-field sets are `candle = 1,149`, `unknown = 680`, intersection
`677`, union `1,152`. These count distinct source-bound origin identities,
not repeated anomaly occurrences: `1,149 + 680 - 677 = 1,152`.

These are carried-forward verified 5C findings, not a new compatibility audit
or historical evaluation performed for 5D. The compatibility payload digest is
`558e3132c3f160aaa21d898d8673ffc2c60a2623bf151b9cd3ab89f370dc9427`.
No native-schema representability count replaces this baseline.

The existing classification order is source-binding validation, then
`audit_only` for out-of-split rows, then `not_closed` before outcome access,
then schema/identity validation (`failed`), unsupported/unresolved semantics
(`blocked`), otherwise `compatible`. Invalid source authentication is rejected
before a trusted row classification is issued. Findings are not model
abstention reasons.

There are 50,844 in-split origins. The final `2026-10-20T13:00:00Z` origin is
audit-only because Test ends exclusively at that instant; its theoretical
target close is 14:00. The last in-split origin is 12:00, whose target closes
at the audit cutoff, 13:00. Thus `not_closed = 0` does not assert that the
audit-only row's target is complete, or that historical publication is known.

## 3. Problem Definition

The tokens encode source claims, not replacement numeric data:

- `candle` is the manifest's missing-hour field token. It is not shorthand for
  five independently evidenced OHLCV-field anomalies.
- `unknown` preserves unspecified field attribution. It is not a numeric null,
  a missing candle, an unresolved association, or a wildcard matching all fields.
- Endpoint versus feature-window association is a separate axis from the
  affected-field token. The same manifest event may legitimately appear in both
  roles, including repeatedly across different rolling feature windows.
- An endpoint anomaly need not change the numeric return. A valid numeric
  target need not have clean source evidence. A long-window feature anomaly
  need not invalidate the current target.

Extending a string validator alone cannot preserve associations, source-record
multiplicity, raw values or evidence. Conversely, retaining a raw attachment
does not make an incomplete 4A summary an exact projection. Neither numeric-only
outcomes nor removal of the 1,152 blocked origins solves the contract problem.

## 4. Architecture Alternatives

| Alternative | Benefits | Compatibility and migration cost | Design disposition |
| --- | --- | --- | --- |
| A — Extend existing 4A `Quality` vocabulary | Superficially small validator change; strings fit existing summary tuples. | Changes approved validation and negative tests; existing consumers may assume OHLCV. Summary tuples still lose raw order/multiplicity/roles. Wider strings do not establish scoring meaning or bypass synthetic reporting restrictions. Requires a new 4A contract/version and coordinated consumer migration, not a silent v1 relaxation. | **Not recommended for this need.** |
| B — Separate historical anomaly vocabulary over the existing envelope | Retains native tokens and association roles without altering 4A or duplicating model rules. Builds on the actual lossless 5A structures and 5C authentication boundary. | Requires an explicit native schema/policy identity and separate native representability audit. Unsupported rows remain blocked for the legacy 4A target. Historical scoring/accounting/reporting consumption still needs separate design and authorization. | **APPROVED DESIGN — ADR-5D-01; not implemented.** |
| C — Separate versioned executable historical `Outcome`/`Quality` contract | Could eventually supply a complete native outcome/scoring domain with wider metadata. | Must specify closure, source authentication, full-universe accounting and historical reporting afresh. Risks duplicating or diverging from 4A reason precedence and eligibility logic. Requires more adapters, versioned tests and migration than metadata representation alone. | **DEFERRED** until a reviewed scoring interface demonstrates that B is insufficient. |

B is not C renamed: B describes typed anomaly records and derived audit views
inside the already-existing historical envelope. It does not define a new
executable historical `Score`, forecast ledger, or reporting engine. A future
historical scorer must be explicitly designed; no executable bridge is hidden
inside a representation adapter.

## 5. Approved Representation Design

### Schema and policy identities — approved in principle

**APPROVED IN PRINCIPLE — ADR-5D-04:** the native schema/policy identities
below. Canonicalization and binding require implementation review; this does
not certify an implemented schema, serializer or authenticated reader, and
does not grant Project Owner implementation authorization.

| Identity | Purpose |
| --- | --- |
| `pqta-historical-anomaly-representation-v1` | Historical-native metadata schema; seven literal field tokens with the existing manifest's type/field combinations and explicit association roles. |
| `pqta-003d-5d-representation-v1` | New, separately named native representation policy. Acceptance here means lossless native representation, never legacy 4A compatibility. |

A new versioned policy identity is required because consuming `candle` or
`unknown` as representable native metadata is not Strict Fail-Closed v1's
exact-4A projection target. Do not change `pqta-003d-5b-projection-v1`, its
validator, or its 5C counts. If a future design instead extends the existing
projection API, it must approve a separately versioned policy rather than
reuse v1. This design approval does not approve such an API change.

### Lossless authoritative layer and separate derived views

Reuse the existing historical records and full typed manifest. A future native
representation must retain:

| Group | Required retention |
| --- | --- |
| Source identity | Existing dataset/build IDs, contract versions, source hashes, source receipt, original source key, row index, origin and candle-open timestamps. |
| Original row | All source names, typed values, nulls, target validity/reasons, feature values/null reasons, `feature_complete`, `ar_lag_valid`, sample/quality masks and recorded source identifiers. No recalculation. |
| Anomaly occurrence | Original raw record, literal type/field names and values, source column, association role, collection position and row identity. Keep endpoint, feature-window and unresolved collections distinct. |
| Manifest evidence | Original manifest bytes/canonical identity, manifest record identity, timestamps, field precision, recorded close timestamp, evidence references/hashes/times, coverage basis, severity, review state and nullable version availability, where actually present. |
| Audit views | Named target schema/policy; separate source-authentication, evidence, closure and representability findings. Derived summaries must reference their source occurrences. |

Ledger annotations contain reduced manifest summaries, not every full-manifest
field. Preserve both source forms. Link an annotation to a manifest record only
when source identity, timestamp, type and supplied field/evidence content
establish an unambiguous match. Keep absent details absent; a filename, plausible
timestamp or populated evidence reference is not proof. Contradictory linkage
is an integrity failure; unresolved linkage remains an explicit limitation.

Manifest record identity and occurrence identity are different: an existing
manifest's validated timestamp/type key identifies its record within that
manifest version/digest; row key plus source column/role and original position
identifies an annotation occurrence. Never deduplicate occurrences merely
because they reference the same manifest event. Retain original array order;
sorting a derived type/field set must not replace the source arrays.

Expose target-endpoint summaries separately from feature-window records.
Preserve `feature_complete` and `ar_lag_valid` explicitly, not via defaults or
token expansion. Preserve the existing distinction between
`target_manifest_anomaly` (any endpoint anomaly, even for a null target) and
`target_value_sensitive` (a valid calculated target with possible numeric
sensitivity). The latter must not narrow sensitivity exclusions.

A future audit should report independent axes: native lossless representability,
legacy-4A-v1 compatibility, association resolution, evidence completeness,
source authentication, temporal closure and method/sample eligibility. Naming
the target schema prevents a native `representable` result from being mistaken
for a 4A `compatible` result. Unresolved associations can be preserved natively
but still block any interpretation requiring a definite dependency role.

Unrecognized future tokens/types may be preserved as opaque audit evidence,
but are not accepted semantic vocabulary without version review. Do not use
`unknown` as an escape hatch for schema drift. Existing strict source readers
continue to reject invalid source schemas.

## 6. Semantic Decision Matrix

Here **existing** means protocol/source facts; **approved design** means native
retention requirements, not implemented functionality. P = A-primary;
S = A-sensitivity. Historical model consumption remains unauthorized, and
legacy unsupported-field blocks remain unchanged.

| Condition | Representation | Forecast impact | Training impact | Scoring impact |
| --- | --- | --- | --- | --- |
| Supported OHLCV anomaly | **Existing:** literal token retained; endpoint summary is possible only when the whole row passes v1. **Approved design:** preserve all occurrences/roles. | Field name alone creates no new filter. Use existing method-specific current feature/lag masks, never current target flags. | P retains otherwise valid rows; S follows the relevant endpoint/feature/lag masks below. | P retains valid anomalous targets; S excludes any endpoint anomaly, not just a close anomaly. |
| `candle` anomaly | **Existing:** missing-hour token retained; v1 blocks. **Approved design:** native literal, never five-field expansion. | Actual missing input/lag and approved feature masks govern. A remote feature-window occurrence does not itself invalidate the current target. | Preserve exact gap and warm-up rules; no invented target/feature values. S masks remain method-specific. | Numeric target validity and endpoint role remain distinct; no new P exclusion based only on this token. Native scoring intake is **DEFERRED**. |
| `unknown` anomaly | **Existing:** literal unspecified field attribution; v1 blocks. **Approved design:** retain without null/missing/association inference. | No generic exclusion or field guess; use explicit approved feature/lag masks. | Do not infer numeric invalidity. P/S eligibility continues to use existing valid-target and dependency flags. | A known endpoint association triggers existing S exclusion regardless of unresolved field attribution; P retains valid targets. Native intake is **DEFERRED**. |
| Target-endpoint anomaly | **Existing:** separate endpoint records and flag; preserve source fields, even on invalid targets. | Current/future target flags never enter emission. | Completed targets: Mean S excludes flagged labels; AR S uses target plus lag masks; Ridge S uses target plus feature masks. P still requires numeric validity. | After closure, P can score a valid target; S excludes any endpoint flag. Numeric sensitivity is not the exclusion criterion. |
| Feature-window anomaly | **Existing:** preserve window records and per-feature masks separately, not in endpoint `Quality`. | Ridge S excludes affected current vectors; AR S uses its exact lag-endpoint mask, not the generic window union. Zero/Mean have no generic current feature-window filter. | Ridge S excludes affected feature rows; AR S uses its pair masks; Mean S uses target endpoints. No generic all-model window exclusion. | A window-only record is not an endpoint anomaly. Do not change target scoreability merely because a distant window contains an anomaly. |
| Missing candle | **Existing:** explicit null row/validity/reasons and exact timeline; never fill or compress. | Missing current/previous required candles invalidate AR lag; incomplete seven-feature vectors prevent Ridge input. Zero/Mean follow their own history rules. Future missingness cannot decide emission. | No gap-crossing return/pair; rolling warm-up and feature nulls remain authoritative. Only completed valid labels/pairs/rows count toward 720. | Missing/invalid target endpoints prevent scoring; preserve all reasons and a previously emitted forecast. |
| Null target | **Existing:** null plus validity/reasons, never synthesized zero. | No current-target inspection; target scoreability cannot determine emission. | Exclude as a historical label only after closure. Do not silently discard malformed labels marked valid. | An emitted forecast remains emitted and becomes `emitted_but_not_scored`; abstained remains `not_scored_no_forecast`. |
| Unresolved association | **Existing:** retain original record; v1 blocks. **Approved design — ADR-5D-05:** native raw retention with explicit unresolved role. | Do not guess endpoint/window, add a generic mask, or turn projection uncertainty into abstention. | Dependency interpretation remains blocked where required; no selective removal to continue execution. | No guessed endpoint flag or incomplete outcome. Any new resolution/enrichment policy **REQUIRES ARCHITECT REVIEW**. |
| Out-of-split origin | **Existing:** retained separately as audit-only. | No evaluation forecast at that origin; approved split boundaries unchanged. | Not admitted as an evaluation/training row outside the approved history/split contract. | No score, common-set timestamp, metric denominator or fabricated forecast status. |

The S training/current-input masks above are the already-approved retrospective
sensitivity exception, not a new point-in-time claim. Do not replace them with
scoring-only exclusions, a generic anomaly Boolean, or performance-selected masks.

## 7. Temporal and Information Boundaries

For forecast origin `o`, feature candle-open time is `o - 1h`; features use
candles only through that open. The target is
`ln(close[o] / close[o - 1h])`, closes theoretically at `o + 1h`, and is
unavailable through a forecast-only interface. A historical label at origin
`h` can be inspected for admission only when `h + 1h <= o`.

Example: at `2025-01-02T00:00:00Z`, the feature row is indexed by the
`2025-01-01T23:00:00Z` candle. The current target uses the 00:00 candle's
close and closes at 01:00; its value, validity and anomaly flags are forbidden
forecast inputs. The label at `2025-01-01T23:00:00Z` closes at 00:00 and may
be considered completed history, subject to the existing eligibility rules.
AR's current lag requires exact candles at `o - 2h` and `o - 1h`; a historical
AR pair at `h` requires consecutive opens `h - 2h`, `h - 1h`, `h`. Removing a
missing hour must not make nonadjacent candles appear consecutive.

Retain distinct read boundaries:

1. Audit-side authenticated binding may retain the complete immutable source.
2. Forecast consumers receive only allowlisted feature/time/lag fields plus an
   opaque identity reference, never the full row, target fields, attachments or
   a resolver/capability that reveals them. Token summaries must not leak
   target-endpoint associations through this interface.
3. Completed-history consumers check each label's clock before reading its
   value, validity, target anomaly flags or raw attachment.
4. Closed-outcome consumers check `origin + 1h <= checked_at` before outcome
   inspection. Pre-closure findings must not reveal future anomaly tokens or
   validity through diagnostics. Changing `checked_at` cannot expand the
   forecast-only schema.

This design changes no refit or feature/model rules: Mean updates hourly;
Mean/AR/Ridge retain the 720 eligible observation/pair/row thresholds; AR and
Ridge refit at scheduled UTC midnight with no stale fallback. Ridge alpha
remains selected only from fixed 2024 validation folds on identical frozen
timestamps, then fixed before Test; the A-primary selection is reused in S.
Selected-alpha Ridge replay remains Test-only, training remains accounting-only
and validation remains candidate-tuning-only.

Theoretical closure is not verified exchange publication. Existing
`available_at = null`, PIT verification false and Gold decision eligibility
false remain unchanged. Neither native representation nor authenticated bytes
can enable Lane B, trading backtesting, or live decisions.

## 8. Provenance and Canonical Identity

### Five independently auditable boundaries

| Boundary | Required evidence or restriction |
| --- | --- |
| Source-byte authentication | Reuse the approved pinned read-only verifier and bind receipts to the exact audited records, source hashes, indices and keys. Synthetic fixtures/asserted hashes/Booleans cannot mint historical authentication. |
| Anomaly-evidence verification | Preserve evidence references, their hashes/times and verification limitations independently. Matching source/manifest bytes authenticates the recorded claim, not its root cause or every referenced artifact. Do not promote `unverified` to `verified`. |
| Temporal closure | Compare exact aware UTC-equivalent clocks before reading outcomes; does not prove publication availability. |
| Historical PIT availability | Requires auditable observation/publication evidence; currently unknown. Preserve null, not candle-close or processing-time substitution. |
| Decision eligibility | Remains false. Neither a valid return nor an eligible research sample grants trading readiness or execution authority. |

5C's private factory registration, object identity and per-record digests bind
receipts to their exact in-process records; copied receipts and tampering are
rejected. This is not a digital signature or hostile-Python security sandbox.
A persisted digest/receipt cannot authenticate itself. Any future persisted
representation must reauthenticate its source bytes/binding through a reviewed
reader; do not treat receipt-shaped caller input as proof.

### Identity hierarchy — approved in principle

Keep original `dataset_spec_id` and `artifact_build_id` unchanged. New
representation identities must be distinct from those source identities and
from future evaluation identities:

| Design identity | Canonical contents |
| --- | --- |
| `representation_spec_id` | Source dataset/build IDs and exact input byte hashes; canonical manifest digest plus raw-byte hash; protocol/source/manifest/schema/policy versions; declared scope and fixed closure boundary; preservation/association rules. Independent of implementation revision. |
| `representation_build_id` | Representation spec ID, implementing code revision/content digest, dependency versions, serializer/canonicalization version and relevant deterministic configuration. |
| `payload_sha256` | Canonical representation payload bytes, excluding the digest's own field. A published file, if separately authorized later, also needs its actual byte SHA-256; do not confuse the two. |

The following canonicalization and identity requirements remain subject to
implementation review under ADR-5D-04. Approval in principle does not verify
their implementation or binding. Existing source serialization, 5C's
`pqta-003d-5c-canonical-v1`, and comparison-set digest encoding are unchanged:

- UTF-8 JSON, fixed sorted object keys, compact separators and one final LF.
  Timestamp values use aware UTC-equivalent datetimes encoded with six
  fractional digits and `Z`. Preserve raw source bytes separately from this
  typed encoding, including any original timestamp text where supplied.
- Deterministic row ordering by validated source identity and origin; retain
  source indices and original occurrence-array order, duplicates, nulls, raw
  strings and numeric values including signed zero. No NaN/infinity coercion.
- Explicit schema/policy/serializer versions and contract validation before
  digest acceptance; reject duplicate keys, mismatched source links, unknown
  semantic schema versions and conflicting bytes under one immutable build ID.
- Keep original reason order and a separately labeled priority-derived view;
  preserve all reasons and existing precedence. Do not sort raw arrays merely
  to obtain a smaller or simpler digest.
- Processing timestamps are not historical availability. Any future generated
  timestamp must be explicitly pinned as build metadata or excluded from the
  deterministic logical payload; the exact choice requires review before
  implementation. No runtime clock may silently change an immutable identity.
- Existing comparison timestamp digests remain the approved sorted unique UTC
  origin encoding (`YYYY-MM-DDTHH:MM:SSZ` followed by LF per origin), not the
  representation's microsecond JSON encoding.

No identities or representation artifacts are generated by this design task.

## 9. Compatibility and Migration Strategy

**APPROVED DESIGN — side-by-side targets, never implicit fallback.**
Implementation remains unauthorized; the following steps are future work,
not completed functionality.

1. Retain 5A/5C and all legacy validators/tests unchanged. Continue reporting
   exact-4A-v1 compatibility with the existing policy and established counts.
2. After separate implementation authorization, add the native schema/policy
   and a named native representability audit over the same authenticated source.
   Report source/evidence/association/closure axes independently; acceptance of
   a literal token does not mean its uncertainty or an execution block is solved.
3. Keep forecast-only, completed-history and closed-outcome views separate.
   A native envelope is not a 4A `Outcome` or an argument to `run_synthetic`.
4. **DEFERRED:** specify and review a historical scoring/accounting interface
   that consumes native metadata, preserves existing metric math, reasons,
   sample rules and temporal gates, and authenticates source bindings. Reuse
   suitable pure protocol helpers rather than duplicate their policy; no
   adapter may erase unsupported fields to reach 4A `Score`.
5. **DEFERRED:** separately version/review historical reporting and publication.
   Existing `ValidationEvidence` synthetic mode and provenance guards stay
   intact. A historical result must not claim to be synthetic or use a
   caller-supplied verification flag to bypass those guards.
6. Historical execution requires an explicit Project Owner authorization after
   blocking interface decisions are resolved. No stage here grants it.

For any future authorized run, declare the entire in-split universe before
models run. Audit-only rows remain separately conserved, not evaluation
origins. Projection failures/blocks are pre-execution blockers, not a fifth
model, score status, abstention reason, or permission to shrink the universe.
If required rows cannot be interpreted, report the scope blocked; do not
produce a seemingly complete comparison on the compatible subset.

For every authorized period/method/sample, retain the existing invariants:

```text
N_origins = N_emitted + N_abstained
N_emitted = N_scored + N_emitted_but_not_scored
N_abstained = N_not_scored_no_forecast
```

Retain one existing forecast status and one final score status per evaluation
origin, exclusive plus overlapping reasons, and scored-only identical timestamp
sets for direct comparisons. Method-own coverage remains distinct from common
metric counts. Scoring exclusions never retract an emitted forecast. Do not
fabricate these records for a blocked/unexecuted scope. Reporting-status
precedence remains distinct from representation classifications; a native
representability result cannot make an evaluation `complete`.

## 10. Synthetic Verification Plan

These are specifications for a future separately authorized implementation,
not tests created or executed here:

| Test group | Required synthetic assertions |
| --- | --- |
| Literal preservation | Round-trip `candle` and `unknown` with original values/nulls; no OHLCV expansion, generic mask, numeric imputation or evidence-status promotion. Test supported/invalid type-token combinations separately. |
| Associations and multiplicity | Same event in endpoint and window roles remains two occurrences; repeated window occurrences retain positions. Unresolved roles remain raw/unresolved, never inferred from token spelling. |
| Source and manifest linkage | Exact identity/key/index/timestamp and manifest linkage; reject contradictory fields, swapped rows, ambiguous enrichment and forged receipts. Partial evidence stays explicitly unverified. |
| Compatibility isolation | Legacy v1 still rejects unsupported fields even in feature-only windows. Native representability does not change its counts, return 4A objects, or pass synthetic runner/reporting guards. |
| Model/sample semantics | Reuse independently checked P/S cases for endpoint-only, window-only, lag-only and mixed anomalies; preserve the retrospective S exception, valid anomalous P targets and all existing masks. No new fitting/scoring policy. |
| Temporal non-access | Instrument forbidden target access before closure, including validity/anomaly diagnostics and attachments; mutate current/future target metadata without changing forecast-only views. Exact-close admission is inclusive. |
| Gaps and nulls | No compressed adjacency, forward fill or cross-gap AR pairs; preserve feature warm-up/null reasons and target reasons. Numeric validity, evidence, representability and eligibility remain separate. |
| Full universe | Mutually exclusive legacy classifications; exact declared-universe conservation, audit-only final origin, distinct-origin unsupported unions. Blocks cannot become abstentions or disappear from scope. |
| Canonical identities | Stable pinned-input payload; raw array order/multiplicity/null/signed-zero retention; changed source/token/role/version changes the relevant identity. Code/serializer changes affect build, not unchanged logical spec. Reject conflicting immutable bytes. |
| Safety boundary | Trap dataset writes, network/model/forecast/report execution; native audit alone produces no forecast/score ledger or performance claims. |

Use synthetic fixtures and temporary bytes for negative authentication tests;
they must never claim authenticated approved historical status. Any later
historical compatibility check must be read-only and explicitly distinguished
from these fixtures and from model evaluation.

## 11. Remaining Blockers

- The 1,152 legacy exact-projection blocks remain real under unchanged v1.
  Native token preservation would address a representation target, not certify
  evidence, repair anomalies, or establish a complete historical execution path.
- Unresolved associations/linkage, where present, require an explicit reviewed
  resolution policy or remain blocking; no new historical prevalence is claimed.
- Anomaly root causes and historical publication availability remain unresolved.
  Authenticated source bytes do not resolve either limitation.
- Native historical scoring/accounting and historical reporting are deferred
  interface decisions. Neither the synthetic coordinator nor its guards may be
  reused by relabeling source history as synthetic.
- Implementation, historical execution, results publication and trading are
  separately unauthorized. Lane B and trading backtesting remain blocked.

Design-only validation consists of direct document inspection, Markdown
structure/local-link/whitespace checks, Git scope/index checks and read-only
hash comparisons. No regression-suite rerun or new 5C classification run is
claimed for this documentation-only milestone.

## 12. Architecture Decision Record

| ADR | Disposition | Approval boundary |
| --- | --- | --- |
| ADR-5D-01 | **APPROVED:** Alternative B, separate native historical vocabulary over the existing lossless envelope. | Preserve literal tokens, raw records, roles and multiplicity; leave 4A unchanged. Design only, not implementation authorization. |
| ADR-5D-02 | **APPROVED:** native representability and legacy 4A compatibility remain independent. | Keep target-schema-specific audit axes, Strict Fail-Closed v1 and existing 5C classifications/counts unchanged. |
| ADR-5D-03 | **APPROVED:** native representation does not unblock historical execution. | Readiness/PIT/decision flags remain false; historical execution requires separate authorization and resolution of blocking interfaces. |
| ADR-5D-04 | **APPROVED IN PRINCIPLE:** native schema/policy identities in §5 and source-linked identity design. | Canonicalization and binding require implementation review, including exact schema/serialization, processing-time treatment and reader/authentication tests. No implementation or byte-verification claim is granted. |
| ADR-5D-05 | **APPROVED:** preserve unresolved associations without guessing or dropping records. | Retain raw evidence and block required interpretation. Any new resolution/enrichment policy requires separate Architect review. |
| ADR-5D-06 | **DEFERRED:** historical scoring/accounting/reporting interfaces. | Separate interface design/review required; preserve existing synthetic contracts and guards. No executable historical replacement contract is approved here. |

### Authorization separation

| Gate | Current state |
| --- | --- |
| Design approval | Architect Design Review passed; dispositions are limited to the ADRs above. |
| Implementation authorization | **NOT GRANTED.** Requires separate Project Owner authorization and implementation review; no native representation has been implemented by this milestone. |
| Historical execution authorization | **NOT GRANTED.** Deferred scoring/accounting/reporting and other execution blockers remain unresolved. |

This finalization records approved design only. It grants no authorization to
implement, fit, forecast, score, benchmark, publish results, backtest or trade.
