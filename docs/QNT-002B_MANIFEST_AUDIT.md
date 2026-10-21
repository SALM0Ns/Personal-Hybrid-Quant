# QNT-002B Stage 2A — BTC anomaly-manifest evidence audit

Audit date: 2026-10-21 (offline). Scope: Binance Spot BTC/USDT, 1h, the
19-record candidate `configs/qnt-002b-btc-anomalies.candidate.v1.json` only.
No market data was fetched, rewritten, filled, or promoted to a Gold feature
snapshot.

## Recommendation: CONDITIONAL PASS

The candidate's structure and every claim that can be tested against retained
archive, Silver, and targeted REST bytes passed. The six relevant monthly
archives have matching local Binance `.CHECKSUM` digests. Their complete UTC
month grids have exactly the 14 missing opens in the candidate; those opens
are also absent from local Bronze and Silver. The four recorded shortened
closes match both archive and separately saved REST responses. At
2021-04-23 01:00 UTC, REST and Silver agree, and only `close` and `volume`
differ from the archive.

**Condition:** the 14 missing hours cannot be independently verified as
absent from *retained raw REST responses*: no REST page captures for those
seven gap windows are present locally. The saved backfill quality report says
they were unobserved after 51 pages, but it is a derived report, not the
individual response payloads. Thus each missing-hour record is
**archive-confirmed and locally unobserved, with direct REST absence
unverified**. This does not establish an exchange outage, instrument listing
date, or continuous exchange availability. Retain the candidate status; do
not use it to claim fully verified REST coverage.

## Methodology and manifest structure

1. Loaded the exact candidate bytes through `AnomalyManifest.load`; checked
   required schema fields, canonical JSON serialization, unique UTC
   hour-aligned timestamps, parent/record version agreement, sorted record
   order, and SHA-256. There are exactly 19 records: 14 `missing_hour`, four
   `shortened_close`, and one `source_discrepancy`. All have
   `severity=unrated`, `review_status=unresolved`, and the parent has
   `version_available_at=null`.
2. Resolved every `source_evidence` reference. Every referenced local
   artifact's SHA-256 matched; every URL resolved to the corresponding
   retained ZIP, whose bytes matched both the manifest digest and the local
   Binance `.CHECKSUM` companion. Reference evidence timestamps match the
   local verification metadata. Those are *retrieval/verification times*,
   not historical publication times. The discrepancy REST reference has
   `observed_at=null`; the saved response itself contains no auditable
   retrieval timestamp.
3. Parsed ZIP CSV members independently of the prior Markdown report and
   verification JSON. ZIP CRC, row shape, UTC hour alignment, unique opens,
   month membership, and OHLCV bounds passed. Compared every calendar hour
   of the six months with the actual archive opens; the set difference was
   exactly the 14 candidate gaps. Archive and Silver open-key sets agree for
   all 4,330 rows in these months. Inspected nearest observed archive
   boundaries around each gap, local Bronze raw candle opens, Silver rows,
   the backfill quality report, and targeted QNT-001C REST captures.
4. For shortened closes, compared archive and saved REST close-time
   milliseconds and all five OHLCV fields against Silver. For the disputed
   candle, compared the archive, saved four-hour REST response, and Silver
   field by field. The extra targeted REST captures are audit evidence but
   are **not referenced by the four shortened-close manifest records**.

The exact canonical candidate digest is
`86a1a76bed96416aba580d8e4468e1e406d8a36a33b68b4c9d6a6ad2a1d2f6f4`.
Its `manifest_version` is `qnt-002b-btc-candidate-v1`. No manifest bytes or
review statuses were changed.

## Evidence inventory

`Axx` means the file under `data/verification/qnt-001b/archives/`; the
candidate reference is the corresponding URL under
`https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/`.
The `.zip.CHECKSUM` file beside each ZIP independently contains the same
digest. The stated coverage is the full UTC calendar month; it does **not**
establish instrument availability or prove the archive was complete when
historical trading occurred.

| ID | Local ZIP filename | SHA-256 (ZIP, candidate, `.CHECKSUM`) | UTC month / rows | Recorded retrieval (UTC) |
| --- | --- | --- | ---: | --- |
| A02 | `BTCUSDT-1h-2021-02.zip` | `8cd20f5058dc7585cfa874a3ab0e5fd0096f369c182d8fda80dc16495050e018` | 2021-02 / 671 | 2026-10-20 14:39:12.887081 |
| A03 | `BTCUSDT-1h-2021-03.zip` | `748783e9715835dd334fbc0cbbff0518962ebbcbe0430acb65f2f506193bad2d` | 2021-03 / 743 | 2026-10-20 14:39:13.451796 |
| A04 | `BTCUSDT-1h-2021-04.zip` | `e5a33803814e6771c4c85e8f2e28e90e46d40f14ca3180a8c10c305cf07fab74` | 2021-04 / 715 | 2026-10-20 14:39:13.970129 |
| A08 | `BTCUSDT-1h-2021-08.zip` | `5cadb462255761842326a2c4b5fe2a91c8a2135c3ba6dd5f0969877f0722f4be` | 2021-08 / 740 | 2026-10-20 14:39:14.513392 |
| A09 | `BTCUSDT-1h-2021-09.zip` | `0d344f8ab39d910c148b89fada91256afcb3e8b20eb812ebc158ac8ac527ea07` | 2021-09 / 718 | 2026-10-20 14:39:15.270152 |
| A23 | `BTCUSDT-1h-2023-03.zip` | `7f2afb8e0179a57ac31eab5205660298ba5eb77039ac2e21aef9b715ff3d06ce` | 2023-03 / 743 | 2026-10-20 14:39:16.041224 |

Every record also references `data/verification/qnt-001b/verification.json`
(`52cbcb8bd545d2dd2bab2702d62fc16a4c81010fc57579c52c0a0c8c2e7a2603`;
verification completed 2026-10-20 14:45:51.667672 UTC). This derived
artifact was checked for provenance and consistency, **not used by itself as
proof** of any anomaly. The discrepancy record additionally references
`data/verification/qnt-001c/rest/BTCUSDT-2021-04-23-00-04.json`
(`f93f1dae3d24bddfe2a6e2c352bb9bbf4de5389268538eff3c9d079937dfb0a2`).
For context, the unreferenced local backfill quality report is
`data/reports/binance/1h/BTC-USDT.json`
(`9ecc010a7da954144d045fe25785366669f5df57b93b32a1a4921f3b7b5bbe5f`).
It requests `[2021-01-01 00:00, 2026-10-20 13:00)` UTC, records 51 fetched
pages, `ingestion_status=incomplete`, `coverage_status=unknown`, and places
all 14 opens in `unknown_coverage_periods`, not verified coverage.

## Record-by-record results

All opens below are UTC. `Gap` means absent from the checksum-verified ZIP,
Bronze raw observations, and Silver, and listed as unobserved in the derived
backfill report. The cited archive covers the entire indicated month, with
observed archive hours on both sides of each gap period. This is verified
**archive/local absence**, not directly verified raw REST absence. The
manifest's missing-hour `affected_fields=[candle]` and
`coverage_basis=verified_archive_and_silver_gap` describe this narrower
evidence; the backfill report still classifies the periods as unknown.

| # | Open | Candidate type / affected fields | Evidence | Direct finding | Audit result |
| ---: | --- | --- | --- | --- | --- |
| 1 | 2021-02-11 03:00 | shortened_close / unknown | A02 + verification JSON | Close 03:40:54.773; targeted REST and Silver corroborate OHLCV; next hour absent | Supported; cause unresolved |
| 2 | 2021-02-11 04:00 | missing_hour / candle | A02 + verification JSON | Gap; nearest archive opens 03:00 and 05:00 | Archive/local supported; raw REST unverified |
| 3 | 2021-03-06 02:00 | missing_hour / candle | A03 + verification JSON | Gap; nearest 01:00 and 03:00 | Archive/local supported; raw REST unverified |
| 4 | 2021-04-20 02:00 | missing_hour / candle | A04 + verification JSON | Gap; period boundaries 01:00 and 04:00 | Archive/local supported; raw REST unverified |
| 5 | 2021-04-20 03:00 | missing_hour / candle | A04 + verification JSON | Gap; period boundaries 01:00 and 04:00 | Archive/local supported; raw REST unverified |
| 6 | 2021-04-23 01:00 | source_discrepancy / close, volume | A04 + verification JSON + saved four-hour REST | Archive versus REST/Silver differs only in close and volume | Supported; cause unresolved |
| 7 | 2021-04-25 04:00 | shortened_close / unknown | A04 + verification JSON | Close 04:00:58.146; targeted REST and Silver corroborate OHLCV; next hour absent | Supported; cause unresolved |
| 8 | 2021-04-25 05:00 | missing_hour / candle | A04 + verification JSON | Gap; period boundaries 04:00 and 08:00 | Archive/local supported; raw REST unverified |
| 9 | 2021-04-25 06:00 | missing_hour / candle | A04 + verification JSON | Gap; period boundaries 04:00 and 08:00 | Archive/local supported; raw REST unverified |
| 10 | 2021-04-25 07:00 | missing_hour / candle | A04 + verification JSON | Gap; period boundaries 04:00 and 08:00 | Archive/local supported; raw REST unverified |
| 11 | 2021-08-13 01:00 | shortened_close / unknown | A08 + verification JSON | Close 01:59:59.000; targeted REST and Silver corroborate OHLCV; next hour absent | Timestamp supported; interpretation unresolved |
| 12 | 2021-08-13 02:00 | missing_hour / candle | A08 + verification JSON | Gap; period boundaries 01:00 and 06:00 | Archive/local supported; raw REST unverified |
| 13 | 2021-08-13 03:00 | missing_hour / candle | A08 + verification JSON | Gap; period boundaries 01:00 and 06:00 | Archive/local supported; raw REST unverified |
| 14 | 2021-08-13 04:00 | missing_hour / candle | A08 + verification JSON | Gap; period boundaries 01:00 and 06:00 | Archive/local supported; raw REST unverified |
| 15 | 2021-08-13 05:00 | missing_hour / candle | A08 + verification JSON | Gap; period boundaries 01:00 and 06:00 | Archive/local supported; raw REST unverified |
| 16 | 2021-09-29 07:00 | missing_hour / candle | A09 + verification JSON | Gap; period boundaries 06:00 and 09:00 | Archive/local supported; raw REST unverified |
| 17 | 2021-09-29 08:00 | missing_hour / candle | A09 + verification JSON | Gap; period boundaries 06:00 and 09:00 | Archive/local supported; raw REST unverified |
| 18 | 2023-03-24 12:00 | shortened_close / unknown | A23 + verification JSON | Close 12:39:41.646; targeted REST and Silver corroborate OHLCV; next hour absent | Supported; cause unresolved |
| 19 | 2023-03-24 13:00 | missing_hour / candle | A23 + verification JSON | Gap; nearest 12:00 and 14:00 | Archive/local supported; raw REST unverified |

The four shortened-close records have `affected_fields=[unknown]`: the
source close-time metadata is anomalous, but the evidence does not establish
that a particular OHLCV field is wrong. The exact saved REST evidence used as
an *additional* cross-check (not a candidate reference) is:

| Candle open (UTC) | REST artifact under `data/verification/qnt-001c/rest/` | SHA-256 | Expected close (UTC) | Early by |
| --- | --- | --- | --- | ---: |
| 2021-02-11 03:00 | `BTCUSDT-1613012400000.json` | `ee060c1cd90636dda30bf0e68b01dcb087c99a558dd21e20cd6660692f188b89` | 03:59:59.999 | 1,145,226 ms |
| 2021-04-25 04:00 | `BTCUSDT-1619323200000.json` | `2b475e3eedc794da2c380028d83f0ab6f44a72e0f9b747f05fa06edd0b46ea09` | 04:59:59.999 | 3,541,853 ms |
| 2021-08-13 01:00 | `BTCUSDT-1628816400000.json` | `8557591223d8402d7683adce62d6f5d2eee2acda3180442afea2efa66c400de3` | 01:59:59.999 | 999 ms |
| 2023-03-24 12:00 | `BTCUSDT-1679659200000.json` | `8549bc9a84e571c2118303d016191b555712d9135f56bec88e020872237f9bc7` | 12:59:59.999 | 1,218,353 ms |

The 999 ms difference on 2021-08-13 01:00 could reflect timestamp
precision or a materially shortened interval; the evidence does not decide
which. Each shortened-close candle immediately precedes a known missing
period, but temporal adjacency does not establish a cause.

For the source discrepancy at 2021-04-23 01:00 UTC:

| Field | Verified archive | Saved REST | Existing Silver | Absolute REST−archive difference |
| --- | ---: | ---: | ---: | ---: |
| Open | 51524.76 | 51524.76 | 51524.76 | 0 |
| High | 51725.74 | 51725.74 | 51725.74 | 0 |
| Low | 49722.22 | 49722.22 | 49722.22 | 0 |
| Close | 51080.59 | 51048.59 | 51048.59 | 32.00 |
| Base volume | 11667.632162 | 11815.248082 | 11815.248082 | 147.615920 |

The saved REST response also contains 00:00, 02:00, and 03:00 UTC candles;
their OHLCV agrees with archive and Silver. Neither the discrepancy's cause
nor which historical version was available at decision time is established.

## Unsupported claims, review status, and next decision

- **Unsupported from retained direct evidence:** per-gap REST response
  absence; an exchange outage; verified listing/availability start; actual
  historical publication time; root causes of shortened closes or revised
  values. The backfill's `unknown_coverage_periods` remain unknown rather
  than being reclassified as verified exchange coverage.
- **Provenance improvement proposed, not implemented:** add the four targeted
  REST file references and their checksums to shortened-close records in a
  future manifest version, if the owner approves. The source-discrepancy REST
  reference already exists. A future audit could retain paginated REST
  responses or bounded gap-window responses with request parameters and
  observation times; no network access or new data collection occurred here.
- **Review-state proposal, not implemented:** retain `severity=unrated` and
  `review_status=unresolved` for all 19. The present schema accepts arbitrary
  nonempty review-status strings but does not distinguish evidence
  verification from causal resolution. A separate evidence-review field or
  documented status vocabulary would require an approved schema/contract
  change. Under such a policy, only the four shortened closes and one
  discrepancy are candidates for full archive-plus-retained-REST evidence
  verification; the 14 gaps qualify only for archive/local verification
  until raw REST absence is auditable. Do not infer severity from anomaly
  type, and keep `version_available_at=null` without auditable publication
  evidence.

This recommendation authorizes neither source correction nor a production
Gold feature snapshot. The existing candidate remains suitable as a
conservative research anomaly mask, with unknown availability and unresolved
coverage carried forward rather than silently repaired.
