# PQTA-003D-6B — Synthetic Native Scoring Kernel

**Status: PQTA-003D-6B — IMPLEMENTED, AWAITING ARCHITECT REVIEW**

Baseline: `0a0a3e21af455b8578e8af7b94675c0728cd5fa6`.
This milestone implements Stage B under the approved
[5G contract](PQTA-003D-5G_NATIVE_SCORING_ACCOUNTING_IMPLEMENTATION_CONTRACT.md),
using the [Stage A schemas](PQTA-003D-6A_NATIVE_TYPES_VALIDATION.md).
Governing protocol `qnt-003d-design-v1`, dataset contract
`pqta-003b-origin-ledger-v1` and approved score/sample rules remain unchanged.

## Public API and identities

[`native_scoring.py`](../src/quant/research/native_scoring.py) exports:

```python
def classify_native_score(
    forecast: HistoricalForecast,
    outcome: HistoricalOutcomeView,
    *,
    scope: HistoricalScopeSpec,
    scoring_build_id: str,
    sample_policy: str,
    policy_version: str = POLICY_VERSION,
) -> ScoreClassification: ...
```

The function accepts only the exact approved Stage A record types. Scope and
provenance must identify `synthetic_fixture`; the outcome must independently
declare that mode, and the forecast must have `execution_instance_id=None`.
Historical labels, digests or serialized descriptors cannot authorize this
synthetic entry point to consume authenticated historical outcomes.

Stage A recomputes the forecast ID and logical scope ID. The kernel validates
exact origin/source identity, model and sample membership, forecast-to-scope
specification identity, the supplied expected scoring-build identity, the
fixed sample argument and approved policy version. Ridge's selection reference
continues to match the scope under existing Stage A validation.

The expected build digest is caller-supplied validation context. Matching it
does not independently verify code/dependency bytes or execution. Structural
scope validation likewise does not authenticate a historical origin ledger.
There is no source reader or capability issuer in this API.

## Closure and availability

For origin `o`, the feature candle opens at `o - 1h`, and the target's
theoretical close is `o + 1h`. The kernel validates safe identity and clock
fields before inspecting target values, validity, reasons or anomaly metadata.
The explicit `checked_at` must be an aware, zero-offset hourly timestamp at or
after that close. UTC-equivalent timezone names are accepted.

An unavailable target is a closed view with `target=None`, `target_valid=False`
and an existing approved source reason such as `next_missing`. An entirely
absent view, pre-closure input or contradictory valid-null/nonfinite target
raises `ValueError`. No reason, return value or publication timestamp is
invented. Mathematical closure does not prove exchange publication.

## Classification decision table

All entries assume valid typed synthetic identities and resolved required
anomaly associations/linkage.

| Forecast | Closed target/sample state | Final classification |
| --- | --- | --- |
| Abstained | Valid or invalid-null target | `not_scored_no_forecast` |
| Emitted | Valid finite target, A-primary, with or without endpoint anomalies | `scored` |
| Emitted | Valid finite target, A-sensitivity, no endpoint anomalies | `scored` |
| Emitted | Invalid-null target under either sample | `emitted_but_not_scored` |
| Emitted | Valid target with any endpoint anomaly, A-sensitivity | `emitted_but_not_scored` |

Source, policy or integrity failures raise `ValueError`, preserving the input
records. They are not converted into additional forecast/score statuses or
model abstentions. Required unresolved associations or unmatched linkage reject
classification; contradictory linkage is an integrity error. Recorded evidence
references remain unverified even when the supplied linkage is consistent.

## Reasons, diagnostics and anomaly retention

The exclusion set combines immutable forecast abstention reasons and original
target-invalid reasons, adding `target_manifest_anomaly` only for
A-sensitivity endpoint anomalies. The existing `SCORE_PRIORITY` and
`ordered_reasons` produce canonical order. Original target-reason order is
preserved separately. The first exclusion is the exclusive primary reason;
`scored` is used when none exists. The first immutable forecast abstention
reason remains its exclusive abstention reason.

All exclusions remain overlapping diagnostics, followed by
`unknown_historical_availability`. That diagnostic does not exclude otherwise
eligible Lane A synthetic scores. Feature-window-only anomalies do not create
an endpoint exclusion; existing AR/Ridge input effects remain outside this
kernel. No numeric validity is inferred from field tokens.

`ScoreClassification.forecast_id` references the exact supplied forecast.
Prediction/status/reasons are copied unchanged; target is retained only for
`scored`. The approved classification schema does not duplicate anomaly arrays.
Their exact roles, raw values, absent/null keys, original strings, order and
multiplicity remain in the unchanged immutable input outcome. Literal `candle`
and `unknown` are never translated. Repeated equivalent inputs produce
byte-identical canonical classifications using Stage A serialization. Signed
zero is preserved, and no runtime clock enters the output.

## Authority and execution boundary

The output properties are fixed and have no constructor switches:

```text
authenticated_historical_score = false
historical_execution_completed = false
point_in_time_verified = false
decision_eligible = false
```

This milestone issues only `ScoreClassification`, never an authenticated
`HistoricalScore`, completed historical accounting or a closed-outcome
capability. No historical I/O, models, forecasts, tuning, live clocks, networks,
databases, metrics, reporting, artifact writing, dashboards, signals or trading
are executed by the kernel. Stages C–F require separate authorization.

## Synthetic validation

The dedicated [tests](../tests/test_native_scoring.py) use invented records to
check the decision table, exact parent/context binding, closure, existing reason
precedence, literal anomaly retention, determinism, nonfinite rejection and
side-effect isolation.

Run in Conda `pqta`:

```bash
python -m pytest -q tests/test_native_scoring.py
python -m pytest -q
ruff check .
ruff format --check src tests web
python -m pip check
git diff --check
```
