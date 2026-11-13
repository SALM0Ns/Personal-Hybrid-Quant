"""Read-only comparisons against untrusted hypothetical MT5 probe exports."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import stat
from datetime import datetime
from pathlib import Path

from .broker_risk import compare_untrusted_native_profit, number

HEADER = [
    "instrument",
    "direction",
    "case",
    "volume",
    "open_price",
    "close_price",
    "quote_broker_time",
    "account_currency",
    "native_profit",
    "profit_status",
    "native_margin",
    "margin_status",
]


def parse_untrusted_native_probe(payload: bytes) -> list[dict[str, str]]:
    if not isinstance(payload, bytes) or not payload or len(payload) > 65536:
        raise ValueError("Probe must be bounded nonempty bytes")
    try:
        reader = csv.reader(
            io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True
        )
        if next(reader, None) != HEADER:
            raise ValueError("Unexpected native probe header")
        result, seen = [], set()
        for row in reader:
            if len(row) != len(HEADER) or any(
                len(v) > 200 or any(ord(c) < 32 for c in v) for v in row
            ):
                raise ValueError("Invalid native probe row")
            item = dict(zip(HEADER, row, strict=True))
            if item["instrument"] not in ("EURUSDm", "XAUUSDm"):
                raise ValueError("Unexpected instrument")
            key = (item["instrument"], item["direction"], item["case"])
            if key in seen:
                raise ValueError("Duplicate native probe scenario")
            seen.add(key)
            if item["case"] == "unavailable":
                if item["direction"] or item["native_profit"] or item["native_margin"]:
                    raise ValueError("Invalid unavailable probe")
            else:
                if item["direction"] not in ("BUY", "SELL") or item["case"] not in (
                    "stop",
                    "target",
                ):
                    raise ValueError("Unexpected native probe scenario")
                volume, entry, close = (
                    number(item[k], k) for k in ("volume", "open_price", "close_price")
                )
                if not item["account_currency"] or volume <= 0:
                    raise ValueError("Missing probe currency or volume")
                datetime.strptime(item["quote_broker_time"], "%Y.%m.%d %H:%M:%S")
                sign = close - entry if item["direction"] == "BUY" else entry - close
                if (item["case"] == "stop" and sign >= 0) or (
                    item["case"] == "target" and sign <= 0
                ):
                    raise ValueError("Probe direction and prices disagree")
            for value_field, status_field in (
                ("native_profit", "profit_status"),
                ("native_margin", "margin_status"),
            ):
                status, value = item[status_field], item[value_field]
                if status == "observed":
                    parsed = number(value, value_field, positive=False)
                    if value_field == "native_margin" and parsed < 0:
                        raise ValueError("Native margin cannot be negative")
                elif not status.startswith("unavailable:") or not status[12:] or value:
                    raise ValueError("Invalid native probe status")
            result.append(item)
        if not result:
            raise ValueError("Empty native probe")
        return result
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Invalid native probe CSV") from exc


def read_untrusted_native_probe(path: Path) -> tuple[bytes, list[dict[str, str]]]:
    path = Path(path)
    if (
        path.name != "broker_native_probe.csv"
        or path.parent.name != "runtime"
        or path.parent.is_symlink()
    ):
        raise ValueError("Unexpected native probe path")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise ValueError("Probe must be a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            payload = stream.read(65537)
    finally:
        os.close(fd)
    return payload, parse_untrusted_native_probe(payload)


def compare_probe_records(
    payload: bytes, records: list[dict[str, str]], snapshot, instrument: str
) -> dict:
    fields = {
        r.name: r.value
        for r in snapshot.properties
        if r.instrument == instrument and not r.status.startswith("unavailable")
    }
    global_fields = {
        r.name: r.value
        for r in snapshot.properties
        if not r.instrument and not r.status.startswith("unavailable")
    }
    comparisons = []
    for row in records:
        if row["instrument"] != instrument:
            continue
        result = {
            key: row[key]
            for key in (
                "direction",
                "case",
                "volume",
                "open_price",
                "close_price",
                "quote_broker_time",
                "account_currency",
                "native_profit",
                "profit_status",
                "native_margin",
                "margin_status",
            )
        }
        result["comparison"] = None
        result["comparison_blocker"] = None
        try:
            if row["profit_status"] != "observed":
                raise ValueError("Native profit unavailable")
            if (
                row["account_currency"] != global_fields.get("account_currency")
                or fields.get("profit_currency") != row["account_currency"]
            ):
                raise ValueError("Account/profit currency conversion is unverified")
            volume = number(row["volume"], "volume")
            minimum = number(fields["volume_min"], "volume_min")
            maximum = number(fields["volume_max"], "volume_max")
            step = number(fields["volume_step"], "volume_step")
            if (
                minimum > maximum
                or volume < minimum
                or volume > maximum
                or volume % step
            ):
                raise ValueError(
                    "Probe volume violates the recorded volume range or step"
                )
            result["comparison"] = compare_untrusted_native_profit(
                direction=row["direction"],
                volume=row["volume"],
                open_price=row["open_price"],
                close_price=row["close_price"],
                tick_size=fields["tick_size"],
                tick_value_profit=fields["tick_value_profit"],
                tick_value_loss=fields["tick_value_loss"],
                native_profit=row["native_profit"],
            )
        except (KeyError, ValueError, ArithmeticError) as exc:
            result["comparison_blocker"] = (
                "Missing or invalid comparison inputs: " + str(exc)
            )
        comparisons.append(result)
    return {
        "instrument": instrument,
        "verification_status": "UNVERIFIED",
        "snapshot_sha256": snapshot.payload_sha256,
        "probe_sha256": hashlib.sha256(payload).hexdigest(),
        "comparisons": comparisons,
        "warning": "Unauthenticated files; snapshot/probe timing, currency conversion, tick-value validity and broker provenance are unverified. Not execution evidence.",
    }
