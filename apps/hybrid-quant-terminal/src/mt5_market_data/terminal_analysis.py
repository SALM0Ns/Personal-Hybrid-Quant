"""Causal, offline chart analysis over completed broker-clock candles.

All events become knowable only at the close of their confirming candle.  The
returned status is a snapshot as of the last input bar, not a point-in-time feed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .indicators import ADX, ATR, EMA

STEPS = {
    "M15": timedelta(minutes=15),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
}


@dataclass(frozen=True)
class AnalysisConfig:
    left: int = 3
    right: int = 3
    tolerance_atr: float = 0.5
    min_touches: int = 2
    min_separation: int = 3
    buffer_atr: float = 0.1
    risk_reward: float = 2.0
    equity: float = 105.57
    risk_fraction: float = 0.01
    max_risk_fraction: float = 0.02
    min_lot: float = 0.01
    lot_step: float = 0.01
    contract_size: float | None = None

    def __post_init__(self):
        if (
            self.left < 1
            or self.right < 1
            or self.min_touches < 2
            or self.min_separation < 1
        ):
            raise ValueError("invalid pivot, touch or separation configuration")
        numeric = (
            self.tolerance_atr,
            self.buffer_atr,
            self.risk_reward,
            self.equity,
            self.risk_fraction,
            self.max_risk_fraction,
            self.min_lot,
            self.lot_step,
        )
        if not all(math.isfinite(v) and v > 0 for v in numeric):
            raise ValueError("configuration values must be positive and finite")
        if self.risk_fraction > self.max_risk_fraction or self.max_risk_fraction > 0.02:
            raise ValueError("risk fraction exceeds the 2% maximum")
        if self.contract_size is not None and (
            not math.isfinite(self.contract_size) or self.contract_size <= 0
        ):
            raise ValueError("invalid contract size")


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _valid_bar(row: dict, step: timedelta) -> None:
    t = row.get("timestamp")
    if not isinstance(t, datetime) or t.tzinfo is not None or t.second or t.microsecond:
        raise ValueError(
            "expected naive broker-clock timestamp aligned to a candle boundary"
        )
    # MT5 H4 anchors may vary with broker sessions; only the minute is fixed.
    minute_step = min(int(step.total_seconds() // 60), 60)
    if t.minute % minute_step:
        raise ValueError("candle timestamp is not aligned to its timeframe")
    try:
        o, h, lo, c = (row[k] for k in ("open", "high", "low", "close"))
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v <= 0
            for v in (o, h, lo, c)
        ):
            raise ValueError("invalid OHLC")
        if h < max(o, lo, c) or lo > min(o, h, c):
            raise ValueError("invalid OHLC geometry")
    except (KeyError, TypeError) as exc:
        raise ValueError("missing or invalid OHLC") from exc


def _new_indicators():
    return EMA(20), EMA(50), ATR(14), ADX(14)


def _zone_update(
    zones: list[dict], swing: dict, tolerance: float, min_touches: int
) -> None:
    """Add a confirmed pivot to at most one cluster, merging overlaps deterministically."""
    kind = "RESISTANCE" if swing["swing_type"] == "HIGH" else "SUPPORT"
    price = swing["pivot_price"]
    matching = [
        z
        for z in zones
        if z["kind"] == kind
        and price + tolerance >= z["lower"]
        and price - tolerance <= z["upper"]
    ]
    if matching:
        zone = matching[0]
        for other in matching[1:]:
            zone["_prices"].extend(other["_prices"])
            zone["lower"] = min(zone["lower"], other["lower"])
            zone["upper"] = max(zone["upper"], other["upper"])
            zone["first_detection_timestamp"] = min(
                zone["first_detection_timestamp"], other["first_detection_timestamp"]
            )
            if other["confirmed_at_timestamp"] is not None:
                zone["confirmed_at_timestamp"] = min(
                    filter(
                        None,
                        (
                            zone["confirmed_at_timestamp"],
                            other["confirmed_at_timestamp"],
                        ),
                    )
                )
            zones.remove(other)
        zone["_prices"].append(price)
        zone["lower"] = min(zone["lower"], price - tolerance)
        zone["upper"] = max(zone["upper"], price + tolerance)
    else:
        zone = {
            "kind": kind,
            "lower": price - tolerance,
            "upper": price + tolerance,
            "first_detection_timestamp": swing["confirmed_at_timestamp"],
            "confirmed_at_timestamp": None,
            "_prices": [price],
        }
        zones.append(zone)
    # Current geometry includes this pivot and is not valid before its confirmation.
    zone["last_updated_at_timestamp"] = swing["confirmed_at_timestamp"]
    zone["price"] = math.fsum(zone["_prices"]) / len(zone["_prices"])
    zone["touches"] = len(zone["_prices"])
    if zone["touches"] >= min_touches and zone["confirmed_at_timestamp"] is None:
        zone["confirmed_at_timestamp"] = swing["confirmed_at_timestamp"]


def _make_pattern(
    first: dict,
    second: dict,
    middle: list[dict],
    atr: float,
    now: str,
    config: AnalysisConfig,
) -> dict | None:
    if second["_index"] - first["_index"] < config.min_separation:
        return None
    tol = config.tolerance_atr * atr
    if abs(first["pivot_price"] - second["pivot_price"]) > tol:
        return None
    opposite = "LOW" if second["swing_type"] == "HIGH" else "HIGH"
    candidates = [
        x
        for x in middle
        if x["swing_type"] == opposite
        and first["_index"] < x["_index"] < second["_index"]
    ]
    if not candidates:
        return None
    neck = (
        min(candidates, key=lambda x: x["pivot_price"])
        if opposite == "LOW"
        else max(candidates, key=lambda x: x["pivot_price"])
    )
    if (
        abs(neck["pivot_price"] - (first["pivot_price"] + second["pivot_price"]) / 2)
        <= tol
    ):
        return None
    pattern_type = "DOUBLE_TOP" if second["swing_type"] == "HIGH" else "DOUBLE_BOTTOM"
    return {
        "id": f"{pattern_type}:{first['pivot_timestamp']}:{second['pivot_timestamp']}",
        "type": pattern_type,
        "status": "FORMING",
        "anchor_1_timestamp": first["pivot_timestamp"],
        "anchor_1_price": first["pivot_price"],
        "anchor_2_timestamp": second["pivot_timestamp"],
        "anchor_2_price": second["pivot_price"],
        "neckline_timestamp": neck["pivot_timestamp"],
        "neckline": neck["pivot_price"],
        "detection_timestamp": now,
        "confirmation_timestamp": None,
        "invalidation_timestamp": None,
        "price_tolerance": tol,
        "relevant_atr": atr,
        "tracking_ended_reason": None,
        "tracking_ended_at_timestamp": None,
    }


def _advance_patterns(patterns: list[dict], close: float, now: str) -> None:
    for p in patterns:
        if p["status"] == "INVALIDATED" or p["tracking_ended_reason"]:
            continue
        top = p["type"] == "DOUBLE_TOP"
        invalid = (
            close > max(p["anchor_1_price"], p["anchor_2_price"]) + p["price_tolerance"]
            if top
            else close
            < min(p["anchor_1_price"], p["anchor_2_price"]) - p["price_tolerance"]
        )
        confirmed = close < p["neckline"] if top else close > p["neckline"]
        if invalid:
            p["status"], p["invalidation_timestamp"] = "INVALIDATED", now
        elif confirmed and p["status"] == "FORMING":
            p["status"], p["confirmation_timestamp"] = "CONFIRMED", now


def _risk_setup(
    pattern: dict | None,
    atr: float | None,
    indicators_ready: bool,
    close: float,
    config: AnalysisConfig,
) -> dict:
    reasons = [
        "Historical broker-clock data; exchange publication time is unverified.",
        "Broker contract, spread, margin, stop-distance and executable quote are unverified.",
    ]
    direction, entry, stop, target, rr, trigger = "WAIT", None, None, None, None, None
    trigger_condition = None
    target_reference_status = "NOT_APPLICABLE"
    if pattern is None:
        reasons.append("No active confirmed pattern in the current contiguous segment.")
    elif not indicators_ready or atr is None or atr <= 0:
        reasons.append("Indicator context is unavailable or still warming up.")
    else:
        bullish = pattern["type"] == "DOUBLE_BOTTOM"
        entry = pattern["neckline"]
        stop = (
            min(pattern["anchor_1_price"], pattern["anchor_2_price"])
            - config.buffer_atr * atr
            if bullish
            else max(pattern["anchor_1_price"], pattern["anchor_2_price"])
            + config.buffer_atr * atr
        )
        distance = abs(entry - stop)
        if (
            stop <= 0
            or distance <= 0
            or (bullish and stop >= entry)
            or (not bullish and stop <= entry)
        ):
            entry, stop = None, None
            reasons.append("Proposed entry and stop do not have valid geometry.")
        else:
            direction = "BUY" if bullish else "SELL"
            target = entry + config.risk_reward * distance * (1 if bullish else -1)
            if (
                target <= 0
                or not math.isfinite(target)
                or (bullish and target <= entry)
                or (not bullish and target >= entry)
            ):
                # Floating-point rounding can collapse a tiny target to entry.
                direction, entry, stop, target = "WAIT", None, None, None
                reasons.append("Proposed target is invalid.")
            else:
                rr = config.risk_reward
                trigger = close > entry if bullish else close < entry
                target_passed = close >= target if bullish else close <= target
                target_reference_status = (
                    "AT_OR_BEYOND" if target_passed else "NOT_AT_OR_BEYOND"
                )
                if target_passed:
                    reasons.append(
                        "Latest historical close is already at or beyond the proposed target; levels are stale references, not evidence of a fill."
                    )
                trigger_condition = (
                    "completed close strictly above neckline"
                    if bullish
                    else "completed close strictly below neckline"
                )
    budget = config.equity * config.risk_fraction
    distance = abs(entry - stop) if entry is not None and stop is not None else None
    theoretical = (
        budget / (distance * config.contract_size)
        if distance and config.contract_size
        else None
    )
    rounded = (
        math.floor(theoretical / config.lot_step) * config.lot_step
        if theoretical is not None
        else None
    )
    if rounded is not None and rounded * distance * config.contract_size > budget:
        rounded = max(0.0, rounded - config.lot_step)
    if distance is None:
        risk_check = "NOT_EVALUATED"
    elif rounded is None:
        risk_check = "UNVERIFIED"
    elif rounded < config.min_lot:
        risk_check = "BLOCKED_MINIMUM_LOT"
    else:
        risk_check = "PASS_ILLUSTRATIVE"
    if rounded is not None and rounded < config.min_lot:
        reasons.append(
            "Theoretical size falls below the illustrative minimum lot; no upward rounding."
        )
    return {
        "direction": direction,
        "overall_action": "WAIT",
        "execution_eligibility": "BLOCKED_UNVERIFIED",
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "target_reference_status": target_reference_status,
        "target_reference_scope": "latest completed historical close only; no fill inferred",
        "risk_reward": rr,
        "trigger_reached": trigger,
        "trigger_condition": trigger_condition,
        "trigger_scope": "latest completed candle close only; not an executed order",
        "blocking_reasons": reasons,
        "risk": {
            "equity_usd": config.equity,
            "risk_fraction": config.risk_fraction,
            "risk_budget_usd": budget,
            "max_risk_fraction": config.max_risk_fraction,
            "entry_stop_distance": distance,
            "theoretical_lots": theoretical,
            "rounded_lots": rounded,
            "estimated_risk_usd": (
                rounded * distance * config.contract_size
                if rounded is not None and distance is not None and config.contract_size
                else None
            ),
            "contract_size_assumption": config.contract_size,
            "minimum_lot": config.min_lot,
            "lot_step": config.lot_step,
            "estimated_trading_costs": None,
            "feasibility": "UNVERIFIED",
            "risk_check": risk_check,
            "risk_check_scope": "Illustrative nominal stop risk only; excludes costs, margin, gap risk and broker verification.",
            "assumptions": "Illustrative only; broker specifications and quote are not verified.",
        },
    }


def analyze_bars(
    rows: list[dict], timeframe: str, *, config: AnalysisConfig | None = None
) -> dict:
    """Analyze ordered completed bars. Naive timestamps represent unverified broker time."""
    if timeframe not in STEPS:
        raise ValueError("unsupported timeframe")
    config = config or AnalysisConfig()
    step = STEPS[timeframe]
    indicators, swings, zones, patterns = [], [], [], []
    segment = []
    segment_swings = []
    fast, slow, atr, adx = _new_indicators()
    previous = None
    for index, bar in enumerate(rows):
        _valid_bar(bar, step)
        t = bar["timestamp"]
        if previous is not None and t <= previous:
            raise ValueError("bars must be unique and strictly chronological")
        if previous is not None and t - previous != step:
            for p in patterns:
                if p["status"] != "INVALIDATED" and p["tracking_ended_reason"] is None:
                    p["tracking_ended_reason"] = "unverified_gap"
                    # The gap is observed only when this later completed bar arrives.
                    p["tracking_ended_at_timestamp"] = _iso(t + step)
            segment, segment_swings, zones = [], [], []
            fast, slow, atr, adx = _new_indicators()
        segment.append(bar)
        values = {
            "timestamp": _iso(t),
            "available_at_timestamp": _iso(t + step),
            "availability_basis": "theoretical broker-clock bar close; publication unverified",
            "ema20": fast.update(bar["close"]),
            "ema50": slow.update(bar["close"]),
            "atr14": atr.update(bar["high"], bar["low"], bar["close"]),
            "adx14": adx.update(bar["high"], bar["low"], bar["close"]),
        }
        indicators.append(values)
        now = _iso(t + step)
        if len(segment) >= config.left + config.right + 1:
            pivot = segment[-config.right - 1]
            left = segment[-config.right - 1 - config.left : -config.right - 1]
            right = segment[-config.right :]
            neighbours = left + right
            for kind, field, compare in (
                ("HIGH", "high", lambda a, b: a > b),
                ("LOW", "low", lambda a, b: a < b),
            ):
                if all(compare(pivot[field], x[field]) for x in neighbours):
                    s = {
                        "pivot_timestamp": _iso(pivot["timestamp"]),
                        "confirmed_at_timestamp": now,
                        "pivot_price": pivot[field],
                        "swing_type": kind,
                        "_index": index - config.right,
                    }
                    prior = next(
                        (
                            x
                            for x in reversed(segment_swings)
                            if x["swing_type"] == kind
                        ),
                        None,
                    )
                    if prior is not None and values["atr14"] and values["atr14"] > 0:
                        p = _make_pattern(
                            prior, s, segment_swings, values["atr14"], now, config
                        )
                        if p:
                            patterns.append(p)
                    swings.append(s)
                    segment_swings.append(s)
                    if values["atr14"] and values["atr14"] > 0:
                        _zone_update(
                            zones,
                            s,
                            config.tolerance_atr * values["atr14"],
                            config.min_touches,
                        )
        _advance_patterns(patterns, bar["close"], now)
        previous = t
    if not rows:
        return {
            "indicators": [],
            "swings": [],
            "zones": [],
            "patterns": [],
            "analysis": None,
        }
    last = indicators[-1]
    active = [
        p
        for p in patterns
        if p["status"] == "CONFIRMED" and p["tracking_ended_reason"] is None
    ]
    active.sort(key=lambda p: (p["confirmation_timestamp"], p["id"]))
    chosen = active[-1] if active else None
    ready = all(
        last[k] is not None and math.isfinite(last[k])
        for k in ("ema20", "ema50", "atr14", "adx14")
    )
    setup = _risk_setup(chosen, last["atr14"], ready, rows[-1]["close"], config)
    trend = (
        "UNAVAILABLE"
        if not ready
        else (
            "BULLISH"
            if last["ema20"] > last["ema50"]
            else "BEARISH"
            if last["ema20"] < last["ema50"]
            else "NEUTRAL"
        )
    )
    analysis = {
        **last,
        "close": rows[-1]["close"],
        "trend": trend,
        "pattern_id": chosen["id"] if chosen else None,
        "pattern_status": chosen["status"] if chosen else None,
        **setup,
    }
    return {
        "indicators": indicators,
        "swings": [
            {k: v for k, v in s.items() if not k.startswith("_")} for s in swings
        ],
        "zones": [
            {k: v for k, v in z.items() if not k.startswith("_")}
            for z in zones
            if z["confirmed_at_timestamp"]
        ],
        "patterns": patterns,
        "analysis": analysis,
    }
