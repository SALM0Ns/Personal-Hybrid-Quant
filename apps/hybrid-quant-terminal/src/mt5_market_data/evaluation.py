"""Offline historical evaluations using explicitly hypothetical broker assumptions."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime, time
from pathlib import Path

from .backtest import Assumptions, simulate
from .indicators import IndicatorConfig
from .market import load_market
from .pipeline import PROJECT_ROOT, digest, within, write_once
from .strategies import generate_decisions

WARNING = (
    "RETROSPECTIVE SIMULATION ONLY: broker time, availability, point size, spread, "
    "slippage, commission and sessions are not verified. Supplied margin and stop "
    "constraints are user assumptions, not broker verification. No broker execution, "
    "market impact or live trading is modeled. Do not use as trading advice."
)


def _time(value: str) -> time:
    try:
        result = time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use broker-clock HH:MM") from exc
    if result.tzinfo is not None:
        raise argparse.ArgumentTypeError(
            "session must be broker-clock time without offset"
        )
    return result


def _date(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "use broker-clock YYYY-MM-DD or ISO datetime"
        ) from exc
    if result.tzinfo is not None:
        raise argparse.ArgumentTypeError(
            "broker-clock boundary must not include an offset"
        )
    return result


def _indicator_arguments(parser):
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--adx-period", type=int, default=14)
    parser.add_argument("--adx-threshold", type=float, default=20)
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--donchian-period", type=int, default=20)
    parser.add_argument("--h4-confirm", action="store_true")


def _financial_arguments(parser):
    parser.add_argument("--train-start", type=_date, required=True)
    parser.add_argument("--split", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--equity-usd", type=float, required=True)
    parser.add_argument("--risk-fraction", type=float, required=True)
    parser.add_argument("--max-risk-fraction", type=float, required=True)
    parser.add_argument("--max-lot", type=float, required=True)
    parser.add_argument("--max-notional-usd", type=float, required=True)
    parser.add_argument("--point-size", type=float, required=True)
    parser.add_argument("--spread-points", type=float, required=True)
    parser.add_argument("--slippage-points", type=float, required=True)
    parser.add_argument("--commission-usd-per-lot-roundtrip", type=float, required=True)
    parser.add_argument("--stop-atr", type=float, default=1.5)
    parser.add_argument("--session-start", type=_time, required=True)
    parser.add_argument("--session-end", type=_time, required=True)
    parser.add_argument(
        "--exit-mode",
        choices=("baseline", "take_profit", "trailing", "reversal"),
        default="baseline",
    )
    parser.add_argument("--take-profit-atr", type=float, default=3.0)
    parser.add_argument("--trailing-atr", type=float, default=1.5)
    parser.add_argument("--minimum-lot", type=float, default=0.01)
    parser.add_argument("--volume-step", type=float, default=0.01)
    parser.add_argument("--margin-per-lot-usd", type=float)
    parser.add_argument("--available-margin-usd", type=float)
    parser.add_argument("--min-stop-distance-points", type=float)
    parser.add_argument(
        "--spec-policy", choices=("strict", "illustrative"), default="strict"
    )
    parser.add_argument("--allow-overnight", action="store_true")
    parser.add_argument("--overnight-cost-usd-per-lot", type=float)
    parser.add_argument(
        "--acknowledge-unverified-assumptions", action="store_true", required=True
    )
    parser.add_argument("--output", type=Path)


def _indicator_config(args):
    return IndicatorConfig(
        ema_fast=args.ema_fast,
        ema_slow=args.ema_slow,
        adx_period=args.adx_period,
        atr_period=args.atr_period,
        donchian_period=args.donchian_period,
        adx_threshold=args.adx_threshold,
        h4_confirm=args.h4_confirm,
    )


def _assumptions(args):
    if args.allow_overnight and args.overnight_cost_usd_per_lot is None:
        raise ValueError(
            "overnight mode requires an explicit per-lot calendar-day cost"
        )
    return Assumptions(
        symbol=args.symbol,
        initial_equity_usd=args.equity_usd,
        risk_fraction=args.risk_fraction,
        max_risk_fraction=args.max_risk_fraction,
        max_lot=args.max_lot,
        max_notional_usd=args.max_notional_usd,
        point_size=args.point_size,
        spread_points=args.spread_points,
        slippage_points=args.slippage_points,
        commission_usd_per_lot_roundtrip=args.commission_usd_per_lot_roundtrip,
        stop_atr=args.stop_atr,
        session_start=args.session_start,
        session_end=args.session_end,
        allow_overnight=args.allow_overnight,
        overnight_cost_usd_per_lot=args.overnight_cost_usd_per_lot or 0.0,
        exit_mode=args.exit_mode,
        take_profit_atr=args.take_profit_atr,
        trailing_atr=args.trailing_atr,
        minimum_lot=args.minimum_lot,
        volume_step=args.volume_step,
        margin_per_lot_usd=args.margin_per_lot_usd,
        available_margin_usd=args.available_margin_usd,
        min_stop_distance_points=args.min_stop_distance_points,
        spec_policy=args.spec_policy,
    )


def _json_default(value):
    if isinstance(value, (datetime, time)):
        return value.isoformat()
    raise TypeError("unsupported JSON value")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "backtest", "compare", "exit-comparison", "decisions"):
        sub = subs.add_parser(name)
        sub.add_argument("--symbol", choices=("EURUSDm", "XAUUSDm"), required=True)
        if name != "validate":
            _indicator_arguments(sub)
        if name in ("backtest", "decisions"):
            sub.add_argument("--strategy", choices=("ema", "donchian"), required=True)
        if name in ("backtest", "compare", "exit-comparison"):
            _financial_arguments(sub)
        if name == "decisions":
            sub.add_argument("--last", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        datasets, alignments, quality, identities = load_market(args.symbol)
        result = {
            "warning": WARNING,
            "symbol": args.symbol,
            "timestamp_semantics": "broker_server_clock_unverified",
            "dataset_identities": identities,
            "algorithm_version": "mt5-historical-mvp-v2",
            "code_sha256": {
                name: digest(
                    (PROJECT_ROOT / "src" / "mt5_market_data" / name).read_bytes()
                )
                for name in (
                    "market.py",
                    "indicators.py",
                    "strategies.py",
                    "backtest.py",
                    "evaluation.py",
                )
            },
            "alignment": quality,
            "row_counts": {k: len(v) for k, v in datasets.items()},
        }
        if args.command != "validate":
            config = _indicator_config(args)
            result["indicator_config"] = asdict(config)
            if args.command == "decisions":
                if not 1 <= args.last <= 100:
                    raise ValueError("--last must be between 1 and 100")
                result["strategy"] = args.strategy
                result["historical_decisions"] = generate_decisions(
                    datasets, alignments, args.strategy, config
                )[-args.last :]
            else:
                if not args.train_start < args.split < args.end:
                    raise ValueError("require train-start < split < end")
                assumptions = _assumptions(args)
                strategies = (
                    (args.strategy,)
                    if args.command == "backtest"
                    else ("ema", "donchian")
                )
                result["results"] = {}
                for strategy in strategies:
                    decisions = generate_decisions(
                        datasets, alignments, strategy, config
                    )
                    modes = (
                        ("baseline", "take_profit", "trailing", "reversal")
                        if args.command == "exit-comparison"
                        else (assumptions.exit_mode,)
                    )
                    variations = {}
                    for mode in modes:
                        settings = replace(assumptions, exit_mode=mode)
                        variations[mode] = {
                            "training": simulate(
                                datasets["M15"],
                                decisions,
                                settings,
                                start=args.train_start,
                                end=args.split,
                            ),
                            "evaluation": simulate(
                                datasets["M15"],
                                decisions,
                                settings,
                                start=args.split,
                                end=args.end,
                            ),
                        }
                    result["results"][strategy] = (
                        variations
                        if args.command == "exit-comparison"
                        else variations[assumptions.exit_mode]
                    )
        body = (
            json.dumps(
                result, default=_json_default, sort_keys=True, indent=2, allow_nan=False
            )
            + "\n"
        ).encode()
        if getattr(args, "output", None):
            path = within(args.output, PROJECT_ROOT)
            if not path.is_relative_to(PROJECT_ROOT / "outputs"):
                raise ValueError("output must be inside project outputs/")
            write_once(path, body)
        print(body.decode(), end="")
        return 0
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
