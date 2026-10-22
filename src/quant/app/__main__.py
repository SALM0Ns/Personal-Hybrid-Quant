"""Start the local PQTA-001 historical preview."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant.app.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only BTC/USDT chart preview")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 1 <= args.limit <= 2000:
        parser.error("--limit must be between 1 and 2000")
    serve(args.data_root, port=args.port, limit=args.limit)


if __name__ == "__main__":
    main()
