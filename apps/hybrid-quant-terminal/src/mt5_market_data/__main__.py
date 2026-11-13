"""Ingest one MT5 export pair already copied inside this project."""

import argparse
import json
from pathlib import Path

from .pipeline import ingest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("metadata", type=Path)
    args = parser.parse_args()
    try:
        report = ingest(args.csv, args.metadata)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Ingestion failed: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
