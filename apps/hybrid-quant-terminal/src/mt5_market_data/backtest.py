"""Offline bar simulation. Prices, costs and broker constraints are assumptions."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal

STEP = timedelta(minutes=15)


@dataclass(frozen=True)
class Assumptions:
    symbol: str
    initial_equity_usd: float
    risk_fraction: float
    max_risk_fraction: float
    max_lot: float
    max_notional_usd: float
    point_size: float
    spread_points: float
    slippage_points: float
    commission_usd_per_lot_roundtrip: float
    stop_atr: float
    session_start: time
    session_end: time
    allow_overnight: bool = False
    overnight_cost_usd_per_lot: float = 0.0
    exit_mode: str = "baseline"
    take_profit_atr: float = 3.0
    trailing_atr: float = 1.5
    minimum_lot: float = 0.01
    volume_step: float = 0.01
    margin_per_lot_usd: float | None = None
    available_margin_usd: float | None = None
    min_stop_distance_points: float | None = None
    spec_policy: str = "strict"

    def __post_init__(self):
        values = (
            self.initial_equity_usd,
            self.risk_fraction,
            self.max_risk_fraction,
            self.max_lot,
            self.max_notional_usd,
            self.point_size,
            self.spread_points,
            self.slippage_points,
            self.commission_usd_per_lot_roundtrip,
            self.stop_atr,
            self.overnight_cost_usd_per_lot,
            self.take_profit_atr,
            self.trailing_atr,
            self.minimum_lot,
            self.volume_step,
        )
        optional = (
            self.margin_per_lot_usd,
            self.available_margin_usd,
            self.min_stop_distance_points,
        )
        if any(
            not isinstance(x, (int, float))
            or isinstance(x, bool)
            or not math.isfinite(x)
            for x in (*values, *(x for x in optional if x is not None))
        ):
            raise ValueError("all numeric assumptions must be finite")
        if self.symbol not in {"EURUSDm", "XAUUSDm"}:
            raise ValueError("unsupported symbol")
        if (
            min(
                self.initial_equity_usd,
                self.point_size,
                self.stop_atr,
                self.max_notional_usd,
                self.take_profit_atr,
                self.trailing_atr,
                self.minimum_lot,
                self.volume_step,
            )
            <= 0
            or self.max_lot < self.minimum_lot
        ):
            raise ValueError("equity, size, stop and limits must be positive")
        if not 0 < self.risk_fraction <= self.max_risk_fraction <= 1:
            raise ValueError("risk fraction exceeds explicit maximum")
        if (
            min(
                self.spread_points,
                self.slippage_points,
                self.commission_usd_per_lot_roundtrip,
                self.overnight_cost_usd_per_lot,
            )
            < 0
        ):
            raise ValueError("costs must be nonnegative")
        if self.margin_per_lot_usd is not None and self.margin_per_lot_usd <= 0:
            raise ValueError("margin per lot must be positive")
        if self.available_margin_usd is not None and self.available_margin_usd < 0:
            raise ValueError("available margin must be nonnegative")
        if (
            self.min_stop_distance_points is not None
            and self.min_stop_distance_points < 0
        ):
            raise ValueError("stop distance must be nonnegative")
        if self.exit_mode not in {"baseline", "take_profit", "trailing", "reversal"}:
            raise ValueError("unsupported exit mode")
        if self.spec_policy not in {"strict", "illustrative"}:
            raise ValueError("unsupported broker-spec policy")
        if not self.session_start < self.session_end or any(
            t.second or t.microsecond or t.minute % 15 or t.tzinfo
            for t in (self.session_start, self.session_end)
        ):
            raise ValueError(
                "session times must be increasing naive 15-minute boundaries"
            )

    @property
    def contract_size(self):
        return 100_000 if self.symbol == "EURUSDm" else 100

    @property
    def spread(self):
        return self.point_size * self.spread_points

    @property
    def slip(self):
        return self.point_size * self.slippage_points


def size_lots(
    equity: float, entry: float, stop_distance: float, config: Assumptions
) -> tuple[float | None, str]:
    if (
        not all(math.isfinite(x) for x in (equity, entry, stop_distance))
        or min(equity, entry, stop_distance) <= 0
    ):
        return None, "invalid_risk_input"
    unit_risk = (
        stop_distance + config.slip
    ) * config.contract_size + config.commission_usd_per_lot_roundtrip
    if not math.isfinite(unit_risk) or unit_risk <= 0:
        return None, "invalid_unit_risk"
    raw = (
        Decimal(str(equity))
        * Decimal(str(config.risk_fraction))
        / Decimal(str(unit_risk))
    )
    step = Decimal(str(config.volume_step))
    value = float((raw / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    if value < config.minimum_lot:
        return None, "below_minimum_lot"
    if value > config.max_lot:
        return None, "above_maximum_lot"
    if value * config.contract_size * entry > config.max_notional_usd:
        return None, "above_maximum_notional"
    if value * unit_risk > equity * config.max_risk_fraction + 1e-9:
        return None, "above_maximum_risk"
    return value, "accepted"


def _assumptions_json(config: Assumptions):
    value = asdict(config)
    value["session_start"] = config.session_start.isoformat()
    value["session_end"] = config.session_end.isoformat()
    value["contract_size_units_per_lot"] = config.contract_size
    value["broker_specification_status"] = "not_independently_verified"
    return value


def simulate(
    bars: list[dict],
    decisions: list[dict],
    config: Assumptions,
    *,
    start: datetime,
    end: datetime,
) -> dict:
    """Simulate next-bar entries; unknown gaps never receive fabricated fills.

    At each bar: opening stop, opening TP, previously queued reversal, then
    intrabar stop before TP, then session/period close. A trailing update uses
    the completed bar's close/ATR and takes effect only on the next bar.
    """
    if start.tzinfo is not None or end.tzinfo is not None or end <= start:
        raise ValueError("simulation boundaries must be increasing broker-clock times")
    if len(bars) != len(decisions):
        raise ValueError("each bar requires exactly one decision")
    selected = [
        (bar, signal)
        for bar, signal in zip(bars, decisions)
        if start <= bar["timestamp"] and bar["timestamp"] + STEP <= end
    ]
    equity = peak = config.initial_equity_usd
    max_drawdown = 0.0
    position = pending = None
    reversal_pending = False
    previous = None
    trades, rejections = [], {}
    unresolved = None
    unknown_gap_count = unverified_spec_candidates = 0

    def reject(reason):
        rejections[reason] = rejections.get(reason, 0) + 1

    def exit_trade(fill, reason, exit_at):
        nonlocal equity, position, reversal_pending
        if not math.isfinite(fill) or fill <= 0:
            raise ValueError("invalid simulated exit price")
        direction = 1 if position["direction"] == "BUY" else -1
        quantity = position["lots"] * config.contract_size
        commission = config.commission_usd_per_lot_roundtrip * position["lots"]
        spread_cost = config.spread * quantity
        slippage_cost = 2 * config.slip * quantity
        financing = position["overnight_fees"]
        net = direction * (fill - position["entry"]) * quantity - commission - financing
        gross = net + spread_cost + slippage_cost + commission + financing
        equity += net
        trades.append(
            {
                "direction": position["direction"],
                "decision_at": position["decision_at"],
                "entry_at": position["entry_at"],
                "exit_at": exit_at,
                "entry": position["entry"],
                "exit": fill,
                "stop": position["stop"],
                "initial_stop": position["initial_stop"],
                "take_profit": position["take_profit"],
                "lots": position["lots"],
                "nominal_stop_risk_usd": position["nominal_stop_risk_usd"],
                "risk_budget_usd": position["risk_budget_usd"],
                "gross_pnl_usd": gross,
                "spread_cost_usd": spread_cost,
                "slippage_cost_usd": slippage_cost,
                "commission_usd": commission,
                "financing_usd": financing,
                "net_pnl_usd": net,
                "estimated_cost_usd": spread_cost
                + slippage_cost
                + commission
                + financing,
                "broker_feasibility": "unverified",
                "reason": reason,
                "holding_minutes": (exit_at - position["entry_at"]).total_seconds()
                / 60,
            }
        )
        position = None
        reversal_pending = False

    for bar, signal in selected:
        t = bar["timestamp"]
        if signal["bar_open"] != t or signal["decision_at"] != t + STEP:
            raise ValueError("decision/bar alignment mismatch")
        if signal["decision"] not in ("BUY", "SELL", "WAIT"):
            raise ValueError("unknown decision")
        if signal["decision"] in ("BUY", "SELL") and (
            not isinstance(signal.get("atr"), (int, float))
            or isinstance(signal.get("atr"), bool)
            or not math.isfinite(signal["atr"])
            or signal["atr"] <= 0
        ):
            raise ValueError("entry decision requires a finite positive ATR")
        if previous is not None and t <= previous:
            raise ValueError("bars must be strictly increasing")
        if previous is not None and t != previous + STEP:
            unknown_gap_count += 1
            if pending:
                reject("next_bar_missing")
                pending = None
            if position:
                unresolved = {
                    "reason": "missing_holding_bar",
                    "expected_bar": previous + STEP,
                    "position_direction": position["direction"],
                    "entry_at": position["entry_at"],
                    "entry": position["entry"],
                    "lots": position["lots"],
                    "stop": position["stop"],
                    "nominal_stop_risk_usd": position["nominal_stop_risk_usd"],
                }
                break
        if position and previous is not None and t.date() > previous.date():
            position["overnight_fees"] += (
                config.overnight_cost_usd_per_lot * position["lots"]
            )
        if pending:
            if t != pending["decision_at"]:
                reject("next_bar_missing")
            elif not config.session_start <= t.time() < config.session_end:
                reject("outside_configured_session")
            else:
                direction = pending["decision"]
                entry = (
                    bar["open"] + config.spread + config.slip
                    if direction == "BUY"
                    else bar["open"] - config.slip
                )
                stop_distance = pending["atr"] * config.stop_atr
                lots, reason = size_lots(equity, entry, stop_distance, config)
                stop = (
                    entry - stop_distance
                    if direction == "BUY"
                    else entry + stop_distance
                )
                tp = None
                if config.exit_mode == "take_profit":
                    tp = (
                        entry + pending["atr"] * config.take_profit_atr
                        if direction == "BUY"
                        else entry - pending["atr"] * config.take_profit_atr
                    )
                missing = [
                    name
                    for name in (
                        "margin_per_lot_usd",
                        "available_margin_usd",
                        "min_stop_distance_points",
                    )
                    if getattr(config, name) is None
                ]
                if lots is None:
                    reject(reason)
                elif stop <= 0 or entry <= 0 or (tp is not None and tp <= 0):
                    reject("invalid_stop_or_entry")
                elif (
                    config.min_stop_distance_points is not None
                    and (stop_distance - config.spread - config.slip)
                    < config.min_stop_distance_points * config.point_size
                ):
                    reject("below_minimum_stop_distance")
                elif (
                    config.margin_per_lot_usd is not None
                    and config.available_margin_usd is not None
                    and lots * config.margin_per_lot_usd
                    > min(config.available_margin_usd, equity)
                ):
                    reject("insufficient_available_margin")
                else:
                    unverified_spec_candidates += 1
                    if missing and config.spec_policy == "strict":
                        reject("missing_broker_specifications")
                    else:
                        position = {
                            "direction": direction,
                            "entry": entry,
                            "stop": stop,
                            "initial_stop": stop,
                            "take_profit": tp,
                            "lots": lots,
                            "entry_at": t,
                            "decision_at": pending["decision_at"],
                            "initial_atr": pending["atr"],
                            "nominal_stop_risk_usd": (stop_distance + config.slip)
                            * lots
                            * config.contract_size
                            + config.commission_usd_per_lot_roundtrip * lots,
                            "risk_budget_usd": equity * config.risk_fraction,
                            "overnight_fees": 0.0,
                        }
            pending = None
        if position:
            buy = position["direction"] == "BUY"
            bid_open = bar["open"]
            exit_open = bid_open if buy else bid_open + config.spread
            stop = position["stop"]
            tp = position["take_profit"]
            stop_open = exit_open <= stop if buy else exit_open >= stop
            tp_open = tp is not None and (exit_open >= tp if buy else exit_open <= tp)
            if stop_open:
                exit_trade(
                    exit_open - config.slip if buy else exit_open + config.slip,
                    "stop",
                    t,
                )
            elif tp_open:
                exit_trade(
                    tp - config.slip if buy else tp + config.slip, "take_profit", t
                )
            elif reversal_pending:
                exit_trade(
                    exit_open - config.slip if buy else exit_open + config.slip,
                    "reversal",
                    t,
                )
            else:
                stop_hit = (
                    bar["low"] <= stop if buy else bar["high"] + config.spread >= stop
                )
                tp_hit = tp is not None and (
                    bar["high"] >= tp if buy else bar["low"] + config.spread <= tp
                )
                if stop_hit:
                    exit_trade(
                        stop - config.slip if buy else stop + config.slip,
                        "stop",
                        t + STEP,
                    )
                elif tp_hit:
                    exit_trade(
                        tp - config.slip if buy else tp + config.slip,
                        "take_profit",
                        t + STEP,
                    )
        close_at = t + STEP
        if position and (
            (
                not config.allow_overnight
                and (
                    close_at.date() != t.date() or close_at.time() >= config.session_end
                )
            )
            or close_at >= end
        ):
            fill = (
                bar["close"] - config.slip
                if position["direction"] == "BUY"
                else bar["close"] + config.spread + config.slip
            )
            exit_trade(
                fill, "configured_close" if close_at < end else "period_end", close_at
            )
        if position:
            mark = (
                bar["close"] - config.slip
                if position["direction"] == "BUY"
                else bar["close"] + config.spread + config.slip
            )
            sign = 1 if position["direction"] == "BUY" else -1
            mark_equity = (
                equity
                + sign
                * (mark - position["entry"])
                * position["lots"]
                * config.contract_size
                - config.commission_usd_per_lot_roundtrip * position["lots"]
                - position["overnight_fees"]
            )
        else:
            mark_equity = equity
        peak = max(peak, mark_equity)
        max_drawdown = max(max_drawdown, (peak - mark_equity) / peak)
        if (
            position
            and config.exit_mode == "trailing"
            and signal.get("atr") is not None
            and math.isfinite(signal["atr"])
            and signal["atr"] > 0
        ):
            candidate = (
                bar["close"] - config.trailing_atr * signal["atr"]
                if position["direction"] == "BUY"
                else bar["close"] + config.spread + config.trailing_atr * signal["atr"]
            )
            if candidate > 0:
                position["stop"] = (
                    max(position["stop"], candidate)
                    if position["direction"] == "BUY"
                    else min(position["stop"], candidate)
                )
        if (
            position
            and config.exit_mode == "reversal"
            and signal["decision"] in ("BUY", "SELL")
            and signal["decision"] != position["direction"]
        ):
            reversal_pending = True
        if not position and signal["decision"] in ("BUY", "SELL") and close_at < end:
            if (
                close_at.date() != t.date()
                or not config.session_start <= close_at.time() < config.session_end
            ):
                reject("signal_outside_configured_session")
            else:
                pending = signal
        previous = t
    if pending:
        reject("no_next_bar_in_period")
    if position and unresolved is None:
        unresolved = {
            "reason": "no_terminal_bar_close",
            "position_direction": position["direction"],
            "entry_at": position["entry_at"],
        }
    wins = [x["net_pnl_usd"] for x in trades if x["net_pnl_usd"] > 0]
    losses = [x["net_pnl_usd"] for x in trades if x["net_pnl_usd"] < 0]
    total = len(trades)
    incomplete = bool(unresolved) or not selected or not total
    if not selected:
        status = "no_data"
    elif unresolved:
        status = "unresolved"
    elif not total and rejections.get("missing_broker_specifications", 0):
        status = "blocked_missing_broker_specifications"
    elif not total:
        status = "no_trades"
    else:
        status = "complete"
    return {
        "start": start,
        "end_exclusive": end,
        "status": status,
        "unresolved": unresolved,
        "coverage_status": "unverified_broker_calendar_and_publication",
        "gap_classification": {
            "verified_scheduled": 0,
            "verified_unexpected": 0,
            "unknown": unknown_gap_count,
            "verified_calendar_available": False,
        },
        "observed_bars_in_requested_period": len(selected),
        "last_processed_bar_open": previous,
        "closed_trade_count": total,
        "win_rate": len(wins) / total if total else None,
        "net_pnl_usd": None if incomplete else equity - config.initial_equity_usd,
        "gross_pnl_usd": None
        if incomplete
        else sum(x["gross_pnl_usd"] for x in trades),
        "closed_trade_pnl_usd": sum(x["net_pnl_usd"] for x in trades),
        "spread_cost_usd": None
        if unresolved
        else sum(x["spread_cost_usd"] for x in trades),
        "closed_spread_cost_usd": sum(x["spread_cost_usd"] for x in trades),
        "slippage_cost_usd": None
        if unresolved
        else sum(x["slippage_cost_usd"] for x in trades),
        "closed_slippage_cost_usd": sum(x["slippage_cost_usd"] for x in trades),
        "commission_usd": None
        if unresolved
        else sum(x["commission_usd"] for x in trades),
        "closed_commission_usd": sum(x["commission_usd"] for x in trades),
        "financing_usd": None
        if unresolved
        else sum(x["financing_usd"] for x in trades),
        "closed_financing_usd": sum(x["financing_usd"] for x in trades),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "max_drawdown_fraction": None if incomplete else max_drawdown,
        "average_win_usd": sum(wins) / len(wins) if wins else None,
        "average_loss_usd": sum(losses) / len(losses) if losses else None,
        "average_holding_minutes": sum(x["holding_minutes"] for x in trades) / total
        if total
        else None,
        "estimated_closed_trading_cost_usd": sum(
            x["estimated_cost_usd"] for x in trades
        ),
        "rejections": rejections,
        "unverified_spec_candidates": unverified_spec_candidates,
        "broker_feasibility": "unverified",
        "assumptions": _assumptions_json(config),
        "trades": trades,
    }
