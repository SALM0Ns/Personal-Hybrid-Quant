# PQTA-003C — Research-Only Origin Dataset Implementation

**Status:** Complete — Architecture Approved (Research Dataset Only).
This is retrospective dataset construction, not Lane A or Lane B evaluation.
No baseline, Ridge fit, forecast, score, model, signal, or backtest was run.
The governing protocol remains `qnt-003d-design-v1`; the dataset contract is
`pqta-003b-origin-ledger-v1`.

## Inputs and immutable output

The builder rejects any mismatch before reading Parquet or publishing output.
The candidate manifest digest uses its existing canonical JSON contract,
not a substituted raw-file hash.

| Pinned local input | Verified SHA-256 |
| --- | --- |
| `data/silver/binance/1h/BTC-USDT.parquet` | `edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3` |
| `data/gold/qnt-002b/btc_usdt_1h/candidate_v1/features.parquet` | `18f70e22ce189787e74fad2d8f7d14202625e09f355bf81792f2aac7bcd1a66d` |
| `configs/qnt-002b-btc-anomalies.candidate.v1.json` (canonical) | `86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4` |

The fixed `analysis_as_of` is `2026-10-20T13:00:00Z`. The published ignored
local directory is
`data/research/pqta-003/6d2d21257a00a5d1d49456b579ed00925df00667501ae84d8417fe393170e2c3/693697c2dc1ea82297959c39b2b6ec8da472f8bc74070e4cd4043d106246cc96/`.
With the approved local inputs present and the `pqta` environment active,
the offline builder runs from the repository root with:

```bash
python -m quant.research.forecast_dataset
```

Its `dataset_spec_id` is the first directory name; its `artifact_build_id`
is the second. The build ID pins the builder and reused validation-module
content hashes, Python and declared dependency versions, schema/column order,
UTC encoding, and Parquet writer settings. The spec ID pins only the eight
approved logical inputs, not processing time or dependency versions.

| Local output | Byte SHA-256 |
| --- | --- |
| `origin_ledger.parquet` | `15d177583efe09b4721da2bcf25356935b9263687f38384a52dbece76d338616` |
| `dataset_validation.json` | `5cebda24aa47525c2b900d954b0e31ad7f11186c26870441574e353e9e4e4520` |
| `provenance.json` | `7ce34fac38e9ed94540b428d8fe72016e3b94f7a6ed7416433735b516cff0d4f` |
| `provenance.sha256` | `91be3a024436a5b8dd247a0d6f026b7deb0dc68b66dcaf03b84a9fa0731af6cd` |

The JSON report contains dataset-quality counts, not predictive metrics.
`provenance.sha256` verifies the exact provenance JSON bytes. The builder
validates the complete ledger, stages on the same filesystem, checks byte
hashes and Parquet roundtrip, then publishes the directory atomically.
An identical pinned rerun verified and reused the same bytes. Conflicting
bytes under one immutable build ID fail closed without overwrite.

## Historical acceptance

| Audit measure | Verified count or boundary |
| --- | ---: |
| Silver observed candles | 50,831 |
| Gold and origin-ledger rows | 50,845 |
| First / last Gold candle open | 2021-01-01 00:00 / 2026-10-20 12:00 UTC |
| First / last research origin | 2021-01-01 01:00 / 2026-10-20 13:00 UTC |
| Training/history origins | 26,279 |
| Validation origins | 8,784 |
| Test origins | 15,781 |
| Outside approved evaluation window | 1 (final 13:00 origin) |
| Explicit missing-hour rows | 14 |
| Valid / null targets | 50,823 / 22 |
| All-seven-feature-complete rows | 49,534 |
| Feature-manifest-anomaly rows | 1,146 |
| Target-endpoint-anomaly rows | 27 |
| Target value-sensitive rows | 6 |
| AR current-lag valid / manifest-anomaly rows | 50,823 / 27 |
| A-primary / A-sensitivity target-eligible rows | 50,823 / 50,817 |
| Gold `available_at` null / Gold `decision_eligible` false | 50,845 / 50,845 |

Target-null reasons are **overlapping**: `current_missing=14`,
`next_missing=15`, `nonconsecutive_opens=7`, and `next_incomplete=1`.
Their sum is not the 22 null targets. Each row retains all applicable
reasons and one exclusive primary reason from QNT-003B §6. The final
out-of-split origin has `next_missing` and `next_incomplete`, with
`next_missing` primary; no next candle is fabricated.

### Architect-review contract checks

`ar_lag_valid` checks the exact Silver opens `t-1h` and `t`, validates both
OHLCV records, and requires candle `t` to have closed by the theoretical
forecast origin `t+1h`. A missing previous hour leaves the lag invalid;
no physically adjacent row is substituted. A malformed previous candle
fails the mandatory source-wide OHLCV audit, so no ledger is published.
The next candle, its anomalies, and the target are not inputs to this lag
mask. This checks dataset-side lag validity only; AR fitting is not run.

`target_manifest_anomaly` means any documented anomaly at either target
endpoint, including on a null target. Separately, `target_value_sensitive`
means a **computed valid target** whose close-based numeric value could be
affected by an endpoint close discrepancy or shortened-close uncertainty.
Thus an anomalous endpoint can be recorded while a gap makes the target
null and `target_value_sensitive=false`. This follows QNT-003A's
"calculable target" language and QNT-002B's non-null-value sensitivity
convention; it does not alter A-primary or A-sensitivity eligibility.

Each row is keyed uniquely by `(exchange, symbol, timeframe,
forecast_origin_utc)`, with one strictly hourly UTC origin per Gold open.
The seven Float64 Gold features, null reasons, quality metadata, and original
availability/eligibility are copied, not recalculated. The target is
`ln(C_(t+1h)/C_t)` from exact adjacent validated Silver open keys. Missing
hours are never bridged or filled. Feature, target, and AR-lag masks remain
distinct. Target-endpoint anomaly metadata is ex-post outcome/audit data;
the allowlisted forecast-side view exposes no current target or next-candle
fields. A-primary retains valid anomaly-flagged targets; A-sensitivity's
target mask excludes any manifest record at either endpoint. Neither mask
performs model-specific training selection or historical eligibility.

## Verification and limitations

The initial 34 synthetic dataset tests passed; Architect-review hardening
added 10 focused cases for AR-lag boundaries, target sensitivity, and
tampered/missing/extra immutable artifacts. The complete local regression
suite passed **166 tests**. Ruff lint, Ruff format, and `pip check` passed. DuckDB
independently read 50,845 rows and unique origin keys, 50,823 valid targets,
and one outside-window origin. All previously recorded Bronze, Silver, and
Gold hashes remained unchanged. No network access or data regeneration was
used; the output is ignored by Git.

The source revision and candidate manifest remain retrospective. The 14
missing hours have archive/local absence but no retained raw REST gap-window
payloads, and the disputed close/volume and shortened-close causes remain
unresolved. Historical `available_at` is unknown and all Gold
`decision_eligible` values remain false. The ledger is therefore **not** a
point-in-time-verified training set or a trading/backtesting dataset.
Dataset publication does not authorize baseline execution, Ridge fitting,
Lane A scoring, Lane B, inference, signals, or execution.
