# Personal Hybrid Quant Trading System

A personal, multi-asset quantitative research system combining statistical and
machine-learning approaches. The initial development focus is historical market
data engineering for 1-hour (`1H`) research.

## Status

Historical Binance Spot OHLCV ingestion is implemented for BTC/USDT, ETH/USDT,
and SOL/USDT at `1h`. Research, signals, brokerage connections, and live
trading are not implemented.

## Planned flow

`Market Data → Bronze → Silver → Gold → Statistical/ML Research → Signal Generation → Risk Assessment → Dashboard → Manual Trading`

See the [project context](docs/PROJECT_CONTEXT.md),
[architecture](docs/ARCHITECTURE.md), and [decisions](docs/DECISIONS.md) before
adding functionality.

## Local setup

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[dev]'
python -m pytest
ruff check .
```

## Historical OHLCV ingestion

Review planned requests without fetching or writing anything:

```bash
python -m quant.ingestion --symbols BTC/USDT ETH/USDT SOL/USDT --backfill --dry-run
```

Run the approved backfill from 2021-01-01 UTC to the latest fully closed hour:

```bash
python -m quant.ingestion --symbols BTC/USDT ETH/USDT SOL/USDT --backfill
```

Resume from the latest stored Silver candle, rechecking the preceding 24 hours:

```bash
python -m quant.ingestion --symbols BTC/USDT ETH/USDT SOL/USDT --incremental --overlap-hours 24
```

`--start`, `--end`, and `--end-exclusive` accept UTC ISO 8601 timestamps on
hour boundaries. The existing `--end` denotes an **inclusive candle open**;
`--end-exclusive` uses `[start,end)` and is mutually exclusive with `--end`.
The last included candle must be fully closed. Only `1h` is supported.
`--page-size` (1 to 1000, default 1000) bounds each provider call. Exit status
2 means at least one requested window contains gaps; status 1 means a
fetch or storage failure. A dry run prints the intended window and page count,
without creating an exchange client or writing files.

Raw revision events are kept in `data/bronze/binance/1h/`; canonical
valid records are in `data/silver/binance/1h/`. Quality reports appear in
`data/reports/binance/1h/`. All data and reports are ignored by Git. Run from
the repository root or set `--data-root` explicitly. Bronze retains revisions
and value reversions; Silver chooses the latest observed valid revision. Empty
API pages and missing hours are reported as incomplete coverage, with no
forward filling.
Expected, observed, and legacy `missing_candle_count` cover the requested
window. The report also gives `requested_end_exclusive`, first and last valid
Silver candles, `unobserved_timestamps`, `missing_timestamps`, and separate
counts/periods for verified
gaps, pre-availability, and unknown coverage. `missing_candle_count` retains
its original meaning of **all unobserved requested hours** for compatibility;
`missing_timestamps` lists only gaps within verified availability.
`ingestion_status` remains `incomplete` whenever requested hours are
unobserved; `coverage_status` explains whether the gap is verified missing,
unknown, or before verified availability.

The per-symbol [availability file](configs/availability.json) starts with no
verified dates. A first API candle is not treated as a listing date. To enter
a verified first available hourly candle, record its UTC hour and a traceable
source in `verified_start_utc` and `evidence`. If listing occurred partway
through an hour, use the first *fully available* hourly candle. Without this
evidence, unobserved hours are classified as unknown. If data precedes the
recorded start, the report flags an availability conflict. You can select an
alternate evidence file using `--availability-config`.

For a bounded seven-day example, ending at the completed 2026-10-20 UTC day
boundary, use:

```bash
python -m quant.ingestion --symbols BTC/USDT --backfill \
  --start 2026-10-13T00:00:00Z --end-exclusive 2026-10-20T00:00:00Z \
  --page-size 48
```

The report records actual fetched page and observation counts. Duplicate,
revision, and rejected counts cover stored Bronze observations for the symbol
(plus exact repeats seen in the current fetch); the other coverage counts are
for the requested window.

Inspect Silver locally with DuckDB:

Set the DuckDB session timezone to UTC when displaying timestamp values;
the Parquet timestamp column has UTC timezone semantics.

```bash
python -c "import duckdb; db=duckdb.connect(); db.execute(\"SET TimeZone='UTC'\"); print(db.execute(\"SELECT min(timestamp), max(timestamp), count(*) FROM 'data/silver/binance/1h/BTC-USDT.parquet'\").fetchall())"
```

Offline tests use mocked exchange responses:

```bash
python -m pytest
ruff check .
```

## Layout

- `src/quant/`: future application packages.
- `data/bronze`, `data/silver`, `data/gold`: local data-lake layers; contents
  are ignored by Git.
- `docs/`: project constraints, architecture, decisions, and research notes.
- `notebooks/`: exploratory work only; production logic belongs in `src/`.
