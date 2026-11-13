"""Explicit UTC adapter from external candles into the existing causal engine.

The underlying engine operates on naive clock coordinates. Here they are created
only after validating UTC input, then every output timestamp is explicitly marked
UTC. Provider data is never joined to the MT5 broker-clock series.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from .terminal_analysis import AnalysisConfig, analyze_bars


def _mark_utc(value):
    if isinstance(value, list):
        return [_mark_utc(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                item + "Z"
                if isinstance(item, str)
                and (key == "timestamp" or key.endswith("_timestamp"))
                and not item.endswith("Z")
                else _mark_utc(item)
            )
            for key, item in value.items()
        }
    return value


def analyze_external(
    candles: list[dict], timeframe: str, config: AnalysisConfig
) -> dict:
    """Analyze validated completed provider candles without broker assumptions."""
    rows = []
    for candle in candles:
        text = candle.get("timestamp_utc")
        if not isinstance(text, str) or not text.endswith("Z"):
            raise ValueError("External candle timestamp must be explicit UTC")
        timestamp = datetime.fromisoformat(text)
        if timestamp.utcoffset() != UTC.utcoffset(timestamp):
            raise ValueError("External candle timestamp must be UTC")
        rows.append({**candle, "timestamp": timestamp.replace(tzinfo=None)})
    result = _mark_utc(
        analyze_bars(rows, timeframe, config=replace(config, contract_size=None))
    )
    if result["analysis"] is not None:
        analysis = result["analysis"]
        reasons = [
            "Massive free data is end-of-day, not a current market or Exness quote.",
            "Provider publication timing, execution quotes and broker requirements are unverified.",
        ]
        reasons.extend(
            reason
            for reason in analysis["blocking_reasons"]
            if not reason.startswith("Historical broker-clock")
            and not reason.startswith("Broker contract")
        )
        if any(
            analysis.get(name) is None for name in ("ema20", "ema50", "atr14", "adx14")
        ):
            reasons.append(
                "Indicator context is unavailable or still warming up after missing data."
            )
        analysis["blocking_reasons"] = reasons
        analysis["execution_eligibility"] = "BLOCKED_UNVERIFIED"
        analysis["overall_action"] = "WAIT"
        risk = analysis["risk"]
        # Broker-specific contract/lot assumptions are not portable across feeds.
        for field in ("minimum_lot", "lot_step", "contract_size_assumption"):
            risk[field] = None
        risk["feasibility"] = "UNVERIFIED"
        risk["risk_check"] = "UNVERIFIED"
        risk["assumptions"] = (
            "Illustrative account budget only. Provider data is not an Exness quote; "
            "contract size, lot rules, costs, margin and stop constraints are unverified."
        )
    return result
