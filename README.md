# Personal Hybrid Quant Trading System

A personal, multi-asset quantitative research system combining statistical and
machine-learning approaches. The initial development focus is historical market
data engineering for 1-hour (`1H`) research.

## Status

Repository initialization only. No ingestion, trading strategies, models,
market-data downloads, brokerage connections, or live trading functionality are
implemented.

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
python -m pip install -e '.[dev]'
pytest
ruff check .
```

## Layout

- `src/quant/`: future application packages.
- `data/bronze`, `data/silver`, `data/gold`: local data-lake layers; contents
  are ignored by Git.
- `docs/`: project constraints, architecture, decisions, and research notes.
- `notebooks/`: exploratory work only; production logic belongs in `src/`.
