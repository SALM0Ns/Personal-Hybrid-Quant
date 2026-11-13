"""Gross risk arithmetic for synthetic broker specifications; never execution authority.

No caller-provided snapshot, digest, or flag authenticates a broker source. MT5
profit/margin rules vary by calculation mode and currency. The linear tick model
below is permitted only for explicitly synthetic fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation, localcontext
from typing import Literal


def number(value: object, name: str, *, positive: bool = True) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{name} must be finite and positive")
    return result


def utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class SpecificationSnapshot:
    """Untrusted data, even when fields have been structurally validated."""

    instrument: str
    account_currency: str
    profit_currency: str
    tick_size: object
    tick_value_loss: object
    tick_value_profit: object
    volume_min: object
    volume_max: object
    volume_step: object
    observed_at_utc: datetime
    source_kind: Literal["SYNTHETIC_FIXTURE"] = "SYNTHETIC_FIXTURE"
    contract_size: object | None = None
    volume_limit: object | None = None
    commission: object | None = None
    margin: object | None = None


@dataclass(frozen=True)
class GrossRisk:
    status: str
    gross_risk_reward: Decimal
    loss_per_minimum_volume: Decimal
    theoretical_volume: Decimal
    normalized_volume: Decimal | None
    expected_gross_loss: Decimal | None
    expected_gross_profit: Decimal | None
    risk_budget: Decimal
    warnings: tuple[str, ...]


def calculate_fixture_risk(
    snapshot: SpecificationSnapshot,
    *,
    instrument: str,
    direction: str,
    entry: object,
    stop_loss: object,
    take_profit: object,
    risk_budget: object,
    as_of: datetime,
    feed_status: str,
    setup_status: str,
    max_snapshot_age: timedelta = timedelta(minutes=5),
) -> GrossRisk:
    """Evaluate synthetic linear tick-value arithmetic; not broker verification.

    The fixture asserts its tick values apply to the specified account currency.
    Values are not inferred from contract size, nor are other instrument modes
    claimed to obey this formula. Execution remains blocked in every result.
    """
    if snapshot.source_kind != "SYNTHETIC_FIXTURE":
        raise ValueError("Only synthetic fixture calculations are supported")
    if instrument != snapshot.instrument or not instrument:
        raise ValueError("Instrument mismatch")
    if (
        not snapshot.account_currency
        or snapshot.account_currency != snapshot.profit_currency
    ):
        raise ValueError("Currency conversion is not verified")
    now, observed = (
        utc(as_of, "as_of"),
        utc(snapshot.observed_at_utc, "observed_at_utc"),
    )
    if (
        max_snapshot_age <= timedelta(0)
        or observed > now
        or now - observed > max_snapshot_age
    ):
        raise ValueError("Specification snapshot is stale or future-dated")
    if feed_status != "LIVE":
        raise ValueError("Market feed is unverified")
    if setup_status != "CURRENT":
        raise ValueError("Analytical setup is unavailable or stale")
    entry_d, stop, target = (
        number(v, n)
        for v, n in (
            (entry, "entry"),
            (stop_loss, "stop_loss"),
            (take_profit, "take_profit"),
        )
    )
    if direction == "BUY":
        loss_distance, profit_distance = entry_d - stop, target - entry_d
    elif direction == "SELL":
        loss_distance, profit_distance = stop - entry_d, entry_d - target
    else:
        raise ValueError("Direction must be BUY or SELL")
    if loss_distance <= 0 or profit_distance <= 0:
        raise ValueError("Stop or target is on the wrong side of entry")
    tick, loss_tick, profit_tick = (
        number(v, n)
        for v, n in (
            (snapshot.tick_size, "tick_size"),
            (snapshot.tick_value_loss, "tick_value_loss"),
            (snapshot.tick_value_profit, "tick_value_profit"),
        )
    )
    minimum, maximum, step = (
        number(v, n)
        for v, n in (
            (snapshot.volume_min, "volume_min"),
            (snapshot.volume_max, "volume_max"),
            (snapshot.volume_step, "volume_step"),
        )
    )
    budget = number(risk_budget, "risk_budget")
    if minimum > maximum or minimum % step or maximum % step:
        raise ValueError("Invalid volume range or step alignment")
    # Aggregate existing exposure is unavailable: don't claim limit compliance.
    if (
        snapshot.volume_limit is not None
        and number(snapshot.volume_limit, "volume_limit", positive=False) < 0
    ):
        raise ValueError("volume_limit must not be negative")
    with localcontext() as context:
        context.prec = 50
        loss_per_lot = loss_distance / tick * loss_tick
        profit_per_lot = profit_distance / tick * profit_tick
        theoretical = budget / loss_per_lot
        volume = min(
            (theoretical / step).to_integral_value(rounding=ROUND_FLOOR) * step, maximum
        )
        loss_min = minimum * loss_per_lot
        if volume < minimum:
            volume = None
        loss = volume * loss_per_lot if volume is not None else None
        profit = volume * profit_per_lot if volume is not None else None
        if loss is not None and loss > budget:
            raise ValueError("Normalized volume exceeds risk budget")
        return GrossRisk(
            status="SYNTHETIC_ONLY" if volume is not None else "NOT_FEASIBLE_SYNTHETIC",
            gross_risk_reward=profit_per_lot / loss_per_lot,
            loss_per_minimum_volume=loss_min,
            theoretical_volume=theoretical,
            normalized_volume=volume,
            expected_gross_loss=loss,
            expected_gross_profit=profit,
            risk_budget=budget,
            warnings=(
                "Synthetic linear tick-value assumptions; not broker authenticated.",
                "Commission, spread, slippage, financing, margin, stop-distance and existing exposure are not verified.",
                "Gross estimates only; execution remains blocked.",
            ),
        )


def illustrative_budget(value: object) -> float:
    """Validate an explicitly supplied USD budget without inferring account equity."""
    budget = number(value, "risk_budget_usd")
    if budget > Decimal(1000000):
        raise ValueError("risk_budget_usd exceeds the illustrative limit")
    result = float(budget)
    if result == 0:
        raise ValueError("risk_budget_usd is too small to represent")
    return result


def unavailable_broker_risk(
    analysis: dict, *, risk_budget_usd: object | None = None
) -> dict:
    """Expose an unverified analysis binding and optional owner-supplied budget."""
    setup = analysis.get("analysis") or {}
    health = analysis.get("feed_health") or {}
    direction = setup.get("direction", "WAIT")
    segment = health.get("current_segment_count")
    history = health.get("history_count")
    gaps = health.get("unresolved_gap_count")
    revisions = health.get("unresolved_revision_count")
    ready = (
        health.get("status") == "LIVE"
        and type(segment) is int
        and type(history) is int
        and 50 <= segment <= history
        and type(gaps) is int
        and gaps >= 0
        and type(revisions) is int
        and revisions == 0
        and direction in ("BUY", "SELL")
        and setup.get("pattern_status") == "CONFIRMED"
        and setup.get("target_reference_status") == "NOT_AT_OR_BEYOND"
    )
    try:
        entry, stop, target = (
            number(setup.get(name), name)
            for name in ("entry", "stop_loss", "take_profit")
        )
        ready = ready and (
            (direction == "BUY" and stop < entry < target)
            or (direction == "SELL" and target < entry < stop)
        )
    except (ValueError, TypeError):
        ready = False
    return {
        "instrument": analysis.get("symbol"),
        "timeframe": analysis.get("timeframe"),
        "snapshot_sha256": analysis.get("snapshot_sha256"),
        "analysis_config": analysis.get("analysis_config"),
        "broker_source": "exness-mt5",
        "account_type": "unverified",
        "specification_status": "UNAVAILABLE",
        "specification_snapshot_time": None,
        "feed_quality_status": health.get("status", "UNVERIFIED"),
        "analytical_direction": direction,
        "setup_status": "CURRENT" if ready else "UNAVAILABLE_OR_STALE",
        "verification_status": "UNVERIFIED",
        "overall_action_eligibility": "BLOCKED_UNVERIFIED",
        "entry": setup.get("entry") if ready else None,
        "stop_loss": setup.get("stop_loss") if ready else None,
        "take_profit": setup.get("take_profit") if ready else None,
        "gross_risk_reward": None,
        "price_distance_reward_risk": setup.get("risk_reward") if ready else None,
        "theoretical_volume": None,
        "normalized_volume": None,
        "expected_gross_loss": None,
        "expected_gross_profit": None,
        "margin_estimate": None,
        "risk_budget": (
            illustrative_budget(risk_budget_usd)
            if risk_budget_usd is not None
            else (setup.get("risk") or {}).get("risk_budget_usd")
        ),
        "risk_budget_basis": (
            "USER_PROVIDED_ILLUSTRATIVE_USD"
            if risk_budget_usd is not None
            else "ILLUSTRATIVE_USD_NOT_VERIFIED_ACCOUNT_BALANCE"
        ),
        "known_costs": {
            "commission": None,
            "spread": None,
            "slippage": None,
            "financing": None,
        },
        "blocking_reasons": [
            "Broker specifications and source authentication are unavailable.",
            "Margin, stop-distance rules, execution costs and conversion are unverified.",
        ],
        "warnings": [
            "Analytical research only; not an executable position size or trading instruction."
        ],
    }


@dataclass(frozen=True)
class UntrustedProperty:
    """A CSV property and its terminal-supplied claim; neither is authenticated."""

    instrument: str
    name: str
    value: str
    status: str


@dataclass(frozen=True)
class UntrustedBrokerSnapshot:
    payload_sha256: str
    properties: tuple[UntrustedProperty, ...]
    verification_status: Literal["UNVERIFIED"] = "UNVERIFIED"


def parse_untrusted_broker_snapshot(payload: bytes) -> UntrustedBrokerSnapshot:
    """Parse a bounded manually obtained MQL CSV, preserving claims verbatim.

    A digest identifies bytes but does not authenticate a terminal or source.
    No observation timestamp, quote, price, or numeric field is assumed valid.
    This deliberately does not feed the synthetic calculator or any live gate.
    """
    import csv
    import hashlib
    import io

    if not isinstance(payload, bytes) or not payload or len(payload) > 65536:
        raise ValueError("Snapshot must be nonempty bytes at most 65536 bytes")
    try:
        content = payload.decode("utf-8-sig")
        rows = csv.reader(io.StringIO(content, newline=""), strict=True)
        if next(rows, None) != ["instrument", "property", "value", "status"]:
            raise ValueError("Unexpected snapshot header")
        records = []
        seen = set()
        global_fields = {
            "server",
            "account_type",
            "account_currency",
            "broker_observed_at",
            "host_observed_at",
        }
        instrument_fields = {
            "contract_size",
            "selected",
            "synchronized",
            "tick_value",
            "margin_calculation_mode",
            "base_currency",
            "digits",
            "point",
            "tick_size",
            "tick_value_profit",
            "tick_value_loss",
            "volume_min",
            "volume_max",
            "volume_step",
            "volume_limit",
            "profit_calculation_mode",
            "trade_mode",
            "stops_level_points",
            "freeze_level_points",
            "spread_points",
            "profit_currency",
            "margin_currency",
            "swap_long",
            "swap_short",
            "bid",
            "ask",
            "tick_broker_time",
            "commission",
            "session_constraints",
            "margin_estimate",
        }
        statuses = {
            "observed",
            "observed_quote_not_verified_fresh",
            "broker_time_timezone_unverified",
            "self_reported_not_authenticated",
            "terminal_reported",
            "host_clock_not_authenticated",
            "unavailable_not_inferred",
            "unavailable_not_calculated",
        }
        non_numeric = {
            "server",
            "account_type",
            "account_currency",
            "broker_observed_at",
            "host_observed_at",
            "profit_currency",
            "margin_currency",
            "base_currency",
            "tick_broker_time",
            "session_constraints",
        }
        for row in rows:
            if len(row) != 4:
                raise ValueError("Unexpected snapshot row shape")
            instrument, name, value, status = row
            if instrument not in ("", "EURUSDm", "XAUUSDm"):
                raise ValueError("Unexpected snapshot instrument")
            if (
                not name
                or len(name) > 80
                or not status
                or len(status) > 120
                or len(value) > 200
            ):
                raise ValueError("Invalid snapshot property")
            if any(ord(c) < 32 for c in instrument + name + value + status):
                raise ValueError("Snapshot fields contain control characters")
            if name not in (global_fields if instrument == "" else instrument_fields):
                raise ValueError("Unknown or inappropriate snapshot property")
            if status not in statuses and not (
                status.startswith("unavailable:") and status[12:].isdigit()
            ):
                raise ValueError("Unknown snapshot status")
            if status.startswith("unavailable"):
                if value:
                    raise ValueError("Unavailable property must not include a value")
            elif not value:
                raise ValueError("Observed property must include a value")
            elif name not in non_numeric:
                number(value, name, positive=False)
            key = (instrument, name)
            if key in seen:
                raise ValueError("Duplicate snapshot property")
            seen.add(key)
            records.append(UntrustedProperty(instrument, name, value, status))
        if not records:
            raise ValueError("Snapshot contains no properties")
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Invalid snapshot CSV") from exc
    return UntrustedBrokerSnapshot(hashlib.sha256(payload).hexdigest(), tuple(records))


def read_untrusted_broker_snapshot(path):
    """Read one explicitly configured runtime file; never follow symlinks or search.

    The caller controls the fixed path; HTTP clients cannot provide it. This is
    an observation aid only and never confers source or broker authentication.
    """
    import os
    import stat
    from pathlib import Path

    path = Path(path)
    if path.name != "broker_spec_snapshot.csv" or path.parent.name != "runtime":
        raise ValueError("Unexpected broker specification snapshot path")
    if path.parent.is_symlink():
        raise ValueError("Snapshot directory must not be a symlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 65536:
            raise ValueError("Snapshot must be a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            payload = stream.read(65537)
        return parse_untrusted_broker_snapshot(payload)
    finally:
        os.close(fd)


def assess_untrusted_specification(
    snapshot: UntrustedBrokerSnapshot, instrument: str
) -> dict:
    """Assess field plausibility, never authenticate caller-controlled source bytes.

    Broker clock strings have no verified offset; without a trusted observation
    clock, freshness cannot be established and no live calculation is enabled.
    """
    if instrument not in ("EURUSDm", "XAUUSDm"):
        raise ValueError("Unsupported instrument")
    fields = {r.name: r for r in snapshot.properties if r.instrument == instrument}
    global_fields = {r.name: r for r in snapshot.properties if not r.instrument}
    required_positive = (
        "contract_size",
        "point",
        "tick_size",
        "tick_value_profit",
        "tick_value_loss",
        "volume_min",
        "volume_max",
        "volume_step",
        "bid",
        "ask",
    )
    problems = []
    for name in (
        "server",
        "account_type",
        "account_currency",
        "broker_observed_at",
        "host_observed_at",
    ):
        item = global_fields.get(name)
        if item is None or item.status.startswith("unavailable") or not item.value:
            problems.append(f"{name}: unavailable")
    if (
        "account_type" in global_fields
        and global_fields["account_type"].value != "demo"
    ):
        problems.append("account_type: not demo")
    values = {}
    for name in required_positive:
        item = fields.get(name)
        if item is None or item.status.startswith("unavailable"):
            problems.append(f"{name}: unavailable")
            continue
        try:
            parsed = number(item.value, name)
            if abs(parsed.adjusted()) > 100 or len(parsed.as_tuple().digits) > 50:
                raise ValueError("numeric representation exceeds safe bounds")
            values[name] = parsed
        except ValueError:
            problems.append(f"{name}: nonpositive or invalid")
    for name in (
        "digits",
        "selected",
        "synchronized",
        "profit_currency",
        "margin_currency",
        "base_currency",
        "profit_calculation_mode",
        "stops_level_points",
        "freeze_level_points",
        "tick_broker_time",
    ):
        item = fields.get(name)
        if item is None or item.status.startswith("unavailable") or not item.value:
            problems.append(f"{name}: unavailable")
    for name in ("selected", "synchronized"):
        if name in fields and fields[name].value != "1":
            problems.append(f"{name}: not confirmed")
    if "digits" in fields:
        try:
            digits = int(fields["digits"].value)
            if digits < 0 or digits > 12 or str(digits) != fields["digits"].value:
                raise ValueError
        except ValueError:
            problems.append("digits: invalid")
    if all(k in values for k in ("volume_min", "volume_max", "volume_step")):
        minimum, maximum, step = (
            values[k] for k in ("volume_min", "volume_max", "volume_step")
        )
        try:
            if minimum > maximum or minimum % step or maximum % step:
                problems.append("volume range or step: inconsistent")
        except InvalidOperation:
            problems.append("volume range or step: numerically invalid")
    if "bid" in values and "ask" in values and values["ask"] < values["bid"]:
        problems.append("quote: ask below bid")
    return {
        "instrument": instrument,
        "assessment": "INCOMPLETE_OR_IMPLAUSIBLE"
        if problems
        else "OBSERVED_UNAUTHENTICATED",
        "verification_status": "UNVERIFIED",
        "freshness_status": "UNKNOWN_BROKER_CLOCK",
        "source_authentication": "UNVERIFIED",
        "native_calculation_status": "UNVERIFIED",
        "problems": problems,
        "warning": "Numeric plausibility and file integrity do not authenticate the source, time, tick-value currency, or economic meaning.",
    }


def compare_untrusted_native_profit(
    *,
    direction: str,
    volume: object,
    open_price: object,
    close_price: object,
    tick_size: object,
    tick_value_profit: object,
    tick_value_loss: object,
    native_profit: object,
) -> dict:
    """Compare explicit values only; no source authentication or trading authority.

    Linear tick math is an illustrative hypothesis. Report exact decimal
    differences rather than declaring a tolerance-based verification.
    """
    if direction not in ("BUY", "SELL"):
        raise ValueError("direction must be BUY or SELL")
    vol = number(volume, "volume")
    entry = number(open_price, "open_price")
    close = number(close_price, "close_price")
    tick = number(tick_size, "tick_size")
    profit_tick = number(tick_value_profit, "tick_value_profit")
    loss_tick = number(tick_value_loss, "tick_value_loss")
    observed = number(native_profit, "native_profit", positive=False)
    price_change = close - entry if direction == "BUY" else entry - close
    with localcontext() as context:
        context.prec = 50
        estimated = (
            price_change
            / tick
            * (profit_tick if price_change >= 0 else loss_tick)
            * vol
        )
        difference = abs(estimated - observed)
        relative = None if observed == 0 else difference / abs(observed)
    return {
        "python_hypothetical": str(estimated),
        "reported_native_profit": str(observed),
        "absolute_difference": str(difference),
        "relative_difference": str(relative) if relative is not None else None,
        "calculation_status": "UNVERIFIED_UNTRUSTED_OBSERVATION",
        "assumption": "Linear tick-value hypothesis; tick-value currency and constancy are not authenticated.",
    }
