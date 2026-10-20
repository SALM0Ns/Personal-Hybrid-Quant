"""Run local-only, read-only BTC/USDT exploratory analysis."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant.research.charts import render_charts
from quant.research.eda import (
    HOUR,
    SILVER_RELATIVE_PATH,
    add_returns,
    add_rolling_volatility,
    build_timeline,
    load_silver,
    summarize,
    timeline_frame,
)
from quant.research.report import render_report, write_tables

DEFAULT_OUTPUT = Path("data/gold/qnt-002a/btc_usdt_1h")
DEFAULT_REPORT = Path("docs/QNT-002A_EDA_REPORT.md")


def run(
    *,
    silver_path: Path = SILVER_RELATIVE_PATH,
    output_dir: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    now: datetime | None = None,
) -> dict:
    """Regenerate deterministic Gold artifacts without writing to Silver."""
    candles, schema, digest = load_silver(silver_path)
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ValueError("now must be timezone-aware UTC")
    if candles[-1].timestamp + HOUR > current:
        raise ValueError("Silver includes an incomplete hourly candle")
    hours = build_timeline(candles)
    add_returns(hours)
    for window in (24, 168):
        add_rolling_volatility(hours, window)
    summary = summarize(hours, schema=schema, sha256=digest)
    output_dir.mkdir(parents=True, exist_ok=True)
    timeline_frame(hours).write_parquet(output_dir / "timeline.parquet")
    table_files = write_tables(summary, output_dir / "tables")
    chart_files = render_charts(hours, summary, output_dir / "charts")
    (output_dir / "results.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(summary, chart_files, table_files), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only BTC/USDT Silver 1h gap-aware descriptive EDA"
    )
    parser.add_argument("--silver", type=Path, default=SILVER_RELATIVE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = run(
        silver_path=args.silver, output_dir=args.output, report_path=args.report
    )
    print(
        json.dumps(
            {
                "input_sha256": summary["dataset"]["sha256"],
                "observed": summary["dataset"]["observed_candle_count"],
                "missing": summary["dataset"]["missing_hour_count"],
                "valid_returns": summary["returns"]["valid_count"],
                "output": str(args.output),
                "report": str(args.report),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
