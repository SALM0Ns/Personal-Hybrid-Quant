"""Command line entry point for historical Binance Spot ingestion."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from quant.ingestion.pipeline import DEFAULT_START, SYMBOLS, Request, ingest


def _utc_hour(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Use ISO 8601 UTC, such as 2021-01-01T00:00:00Z"
        ) from exc
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(result):
        raise argparse.ArgumentTypeError(
            "Timestamp must include the UTC offset (+00:00 or Z)"
        )
    return result.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", required=True, choices=SYMBOLS)
    parser.add_argument("--timeframe", choices=["1h"], default="1h")
    parser.add_argument("--start", type=_utc_hour, default=DEFAULT_START)
    end_options = parser.add_mutually_exclusive_group()
    end_options.add_argument(
        "--end", type=_utc_hour, help="Inclusive, fully closed candle open (UTC)"
    )
    end_options.add_argument(
        "--end-exclusive", type=_utc_hour, help="Exclusive UTC boundary for [start,end)"
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--backfill", action="store_true")
    modes.add_argument("--incremental", action="store_true")
    parser.add_argument("--overlap-hours", type=int, default=24)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--availability-config",
        type=Path,
        default=Path("configs/availability.json"),
        help="Per-symbol verified availability evidence JSON",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    status = 0
    for symbol in args.symbols:
        request = Request(
            symbol=symbol,
            start=args.start,
            end=args.end,
            end_exclusive=args.end_exclusive,
            mode="backfill" if args.backfill else "incremental",
            overlap_hours=args.overlap_hours,
            page_size=args.page_size,
            data_root=args.data_root,
            availability_config=args.availability_config,
            dry_run=args.dry_run,
        )
        try:
            report = ingest(request)
        except Exception as exc:
            parser.exit(1, f"{symbol}: {type(exc).__name__}: {exc}\n")
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["ingestion_status"] == "incomplete":
            status = 2
    return status


if __name__ == "__main__":
    raise SystemExit(main())
