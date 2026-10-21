# QNT-002B Stage 2B — BTC/USDT real-data feature audit

**Recommendation: CONDITIONAL PASS for offline descriptive research only.**
The pinned Gold snapshot passed the input, schema, continuity, calculation,
anomaly-propagation, availability, reproducibility, Parquet, and independent
DuckDB checks below. The condition is inherited from the Stage 2A manifest
audit: the 14 missing hours have verified archive/local absence but no
retained raw REST gap-window responses; anomaly root causes and historical
publication times remain unknown. The full regression suite could not
complete during import while installed CCXT files were offloaded; the
passing subset and data audit are reported separately below. This snapshot
is **not trading-ready, historically point-in-time verified, or eligible
for a backtest**.

## Pinned inputs, output, and run boundary

| Item | Value |
| --- | --- |
| Silver input | `data/silver/binance/1h/BTC-USDT.parquet` |
| Exact Silver SHA-256 | `edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3` |
| Candidate manifest | `configs/qnt-002b-btc-anomalies.candidate.v1.json` |
| Canonical manifest SHA-256 | `86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4` |
| Feature / manifest versions | `qnt-002b-v1` / `qnt-002b-btc-candidate-v1` |
| Fixed `analysis_as_of` | `2026-10-20 13:00:00 UTC` (exclusive candle-end boundary) |
| Last Silver candle open | `2026-10-20 12:00:00 UTC`; closes exactly at the boundary |
| `generated_at` | `2026-10-21 07:08:33.977512 UTC` (processing time, not market availability) |
| Local-only Gold output | `data/gold/qnt-002b/btc_usdt_1h/candidate_v1/features.parquet` |
| Gold SHA-256 | `18f70e22ce189787e74fad2d8f7d14202625e09f355bf81792f2aac7bcd1a66d` |
| Parquet serializer | Polars 2.0.0; Zstandard level 3; statistics enabled; row groups of 8,192 |
| Independent query reader | DuckDB 1.5.6 |

The fail-closed offline run is reproducible with
`PYTHONPATH=src .venv/bin/python scripts/qnt_002b_stage2b.py` from the
repository root, **provided its exclusive output path does not already
exist**. The utility rejects an unexpected Silver or manifest digest,
missing or mismatched referenced evidence, a noncanonical or differently
ordered 19-record manifest, a changed version or analysis boundary, and an
existing output file. It validates in memory and queries a temporary
Parquet before creating the final local file with exclusive-write mode.
No exchange connection or network fetch is part of this workflow. The
candidate retains all 19 records with `severity=unrated`,
`review_status=unresolved`, and `version_available_at=null`.

## Dataset and statistical checks

| Check | Result |
| --- | ---: |
| Observed Silver candles | 50,831 |
| Expected Gold hourly rows, `[2021-01-01 00:00, 2026-10-20 13:00)` UTC | 50,845 |
| Gold rows / unique primary keys | 50,845 / 50,845 |
| First / last Gold open | 2021-01-01 00:00 / 2026-10-20 12:00 UTC |
| Explicit missing-hour rows | 14, the exact candidate missing-open set |
| Documented source-discrepancy rows at `t` | 1 |
| Documented shortened-close rows at `t` | 4 |
| Non-finite feature values | 0 |
| Decision-eligible rows | 0 |

Every timestamp is timezone-aware UTC, strictly increasing by exactly one
hour, with the fixed `(exchange, symbol, timeframe)` identity
`(binance, BTC/USDT, 1h)`. `candle_end_at = timestamp + 1h` on every row.
All seven feature columns are nullable Float64. Every null has exactly one
approved reason; every non-null has a null reason of null. Missing rows have
all seven values null and no source candle. No forward fill, interpolation,
archive substitution, or source correction was applied.

| Feature | Non-null | Null | `missing_candle` | `gap_in_window` | `insufficient_history` | `zero_denominator` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `log_return_1h` | 50,823 | 22 | 14 | 7 | 1 | 0 |
| `volatility_24h` | 50,639 | 206 | 14 | 168 | 24 | 0 |
| `volatility_168h` | 49,534 | 1,311 | 14 | 1,129 | 168 | 0 |
| `momentum_24h` | 50,639 | 206 | 14 | 168 | 24 | 0 |
| `momentum_168h` | 49,534 | 1,311 | 14 | 1,129 | 168 | 0 |
| `volume_change_1h` | 50,823 | 22 | 14 | 7 | 1 | 0 |
| `normalized_range_1h` | 50,831 | 14 | 14 | 0 | 0 | 0 |

These counts were independently reconstructed from a complete UTC timeline,
the Silver present/missing mask, and the contract's lookbacks and null-reason
priority—not copied from the feature engine's null output. The two
zero-volume Silver candles open at 2021-02-11 03:00 and 2023-03-24 12:00
UTC; each immediately precedes a missing hour, so neither produces a
calculable next-hour volume ratio. There are therefore no
`zero_denominator` nulls in this pinned snapshot; the approved rule remains
tested by synthetic fixtures.

Gap-adjacent spot checks at 2021-02-11 04:00/05:00 UTC confirmed an explicit
all-null missing row and, at 05:00, a valid `normalized_range_1h` but null
one-hour changes and 24h/168h windows with `gap_in_window`. After 24 and
168 contiguous hours, the corresponding features first resume at
2021-02-12 05:00 and 2021-02-18 05:00 UTC. All rows were checked against
the exact elapsed-hour dependency sets: no rolling or momentum calculation
crosses a missing candle, and no required candle opens after its feature
row's timestamp.

### Separate calculation path

The audit utility uses standard-library `math` and `statistics.stdev`
(`ddof=1`) over independently selected Silver rows, not feature-engine
calculations. It checked 183 distinct targeted/seeded rows, including 64
random indices selected with fixed seed `20261021`, all seven feature
formulas where non-null, every gap and anomaly neighborhood, and the
24h/168h warm-up boundaries. The simple endpoint ratio was used for both
momentum features, and the **close** denominator for normalized range.
For illustration, at the fully warmed-up 2021-02-18 05:00 UTC row:

| Feature | Independently calculated | Gold value |
| --- | ---: | ---: |
| `log_return_1h` | 0.000319199813836 | 0.000319199813836 |
| `volatility_24h` (`ddof=1`) | 0.00560433329137 | 0.00560433329137 |
| `volatility_168h` (`ddof=1`) | 0.00778007358481 | 0.00778007358481 |
| `momentum_24h` | 0.0495547892844 | 0.0495547892844 |
| `momentum_168h` | 0.168637991547 | 0.168637991547 |
| `volume_change_1h` | -0.259971224655 | -0.259971224655 |
| `normalized_range_1h` | 0.00541153816148 | 0.00541153816148 |

All sampled comparisons met `rel_tol=1e-10`, `abs_tol=1e-12`; the tiny
log/volatility differences are floating-point evaluation-order effects,
not formula changes. All non-null feature values were finite.

## Anomaly, availability, and eligibility checks

For **every Gold row**, a separate dependency-window calculation compared
`anomaly_involved_features`, `value_sensitive_features`, sorted
`involved_anomalies`, source flags, recorded shortened close times, and
quality flags against the 19 manifest records. Every record propagated to
at least one row. The per-feature row counts were:

| Feature | Anomaly involved | Numerically value-sensitive |
| --- | ---: | ---: |
| `log_return_1h` | 27 | 6 |
| `volatility_24h` | 211 | 29 |
| `volatility_168h` | 1,146 | 3 |
| `momentum_24h` | 211 | 6 |
| `momentum_168h` | 1,146 | 3 |
| `volume_change_1h` | 27 | 6 |
| `normalized_range_1h` | 19 | 5 |

At the disputed 2021-04-23 01:00 UTC candle, Gold preserves Silver's
numeric values and records `source_discrepancy_fields=[close, volume]`.
`log_return_1h` is value-sensitive both on the 01:00 row (return ending at
01:00) and on the 02:00 row (return ending at 02:00); both adjacent volume
changes are likewise marked. A window with an earlier gap can remain null
while still carrying anomaly provenance. The four shortened-close records
also propagate without repairing OHLCV; the unresolved 999 ms August case
remains flagged.

Because `version_available_at=null`, all 50,845 rows have
`quality_evidence_available_at=null`, `available_at=null`, and
`availability_basis=unverified`. The 50,831 source-present rows can retain
`max_source_ingested_at` from local observations, but that is not an exchange
publication timestamp and cannot replace the missing manifest-availability
evidence. All 50,845 rows correctly have `decision_eligible=false`.
Availability inequalities involving non-null `available_at` are vacuous for
this snapshot; no 2021 decision-time claim is made.

## Reproducibility, data integrity, and limitations

Two complete in-memory builds with the same Silver bytes, manifest bytes,
versions, `analysis_as_of`, and injected `generated_at` produced equal rows,
metadata, and byte-identical Parquet under the pinned serializer settings.
Changing only `generated_at` by one microsecond left all other columns
unchanged but changed Parquet bytes, as expected. DuckDB read a temporary
copy before publication and independently confirmed 50,845 rows, 50,845
unique timestamps, 14 missing rows, and zero eligible rows; a post-build
query of the final local file confirmed the same counts.

All existing Bronze/Silver SHA-256 hashes matched before and after:

| Dataset | BTC/USDT | ETH/USDT | SOL/USDT |
| --- | --- | --- | --- |
| Bronze | `c72ed6df50df0c777e47505c9eed4c8d282cdc9d2125d51d5b56b28e43e7a212` | `dd7063869ac65a7cd6652807c69d019d655c098d81ff2bc874625cfc8142802d` | `83a101a49fea1cd3737ef28791b6115c11e2efbb4a976ed9283fdab85c36f710` |
| Silver | `edc38a28308b7f8e8d8080f78dafd80ae68632a00f791794df05f676217855c3` | `38aa913ac8fafc40c817502e5357e3a2d142a655ed098a6b58ba445ef3dafd5f` | `a6e0fc4eb56ad6eb594f6dccfd14f43bb6db78ea4b883c3a565ab0241f8a790e` |

The aggregate hash of the 18 existing QNT-002A Gold files remained
`5dc4b85a6186c174f43ee523ecf3c2ef99af4599f547eb2309bfd4ebfd661fb5`.
The new QNT-002B Parquet is ignored by Git under `/data/**` and does not
overlap QNT-002A. No source or pre-existing Gold artifact was modified;
no exchange/API request, market-data download, new dependency, trading
signal, backtest, or model was introduced.

The remaining limitations are material: direct raw REST evidence of the 14
gap-window absences was not retained; the candidate remains unresolved;
the selected Silver snapshot and quality manifest were assembled
retrospectively, without historical as-of versions or proven publication
times. The universal eligibility veto is therefore an intended safety
outcome, not a pipeline failure. Owner review is required before any later
use or a new manifest policy/version.

## Validation run results

- The focused feature/manifest suite passed: **27 passed in 8.15s** using
  the existing project packages and local system pytest with plugin autoload
  disabled. The non-CCXT regression subset (feature, research EDA, archive
  verification, and project smoke tests) passed: **53 passed in 31.49s**.
  The 27 focused tests are included in the 53; do not add these counts.
- A full-suite retry was interrupted after **176.84s with no tests run**,
  during dependency import/test collection. It is **not** a passing full
  suite. The project `.venv`'s direct pytest entry point also stalled
  before collection. macOS marked many installed CCXT package files
  `dataless`, and local file access was slow. The exact file-provider
  mechanism was not independently verified. No package was installed,
  upgraded, replaced, or deleted. The 31 ingestion tests were not executed
  in this run. A later full-suite rerun is needed once the existing
  environment is locally available.
- `ruff check .` passed; `ruff format --check .` reported all 40 files
  formatted. `git diff --check` passed. The new report and script were also
  checked for whitespace/formatting, and the Parquet output is ignored by
  `.gitignore`.
