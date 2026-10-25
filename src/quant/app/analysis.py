"""On-demand public BTC candles and an informational deterministic assessment.

No model training, historical execution, broker connection or dataset writer.
Existing ingestion readers/validators and shared feature formulas are reused.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from quant.features.adapter import _validate_observations, prepare_shared_features
from quant.features.engine import FEATURES
from quant.features.manifest import AnomalyManifest
from quant.ingestion.ohlcv import HOUR_MS, binance_spot, fetch_pages
from quant.ingestion.pipeline import latest_closed
from quant.validation.ohlcv import normalize

HOUR = timedelta(hours=1)
WINDOW_HOURS = 200
SOURCE = "Binance BTC/USDT Spot — Analysis Reference"
STRATEGY = "Momentum agreement v1 — deterministic, unvalidated"
ATR_PERIOD = 14
ATR_METHOD = "Wilder RMA (14)"
REFERENCE_LABEL = (
    "Binance Spot reference estimates — not verified Exness CFD execution prices"
)
WARNINGS = [
    "Informational only; not validated for Exness execution or profitability.",
    "Binance Spot USDT prices are not Exness BTC CFD prices or execution terms.",
    "Position sizing, margin checks, trading costs and order execution are disabled.",
    "Observed now; historical publication/PIT availability is not established.",
    "Mechanical data checks do not independently verify all source anomalies.",
]


class MarketDataError(ValueError):
    """A current, complete, valid analysis window could not be established."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MarketDataError("A timezone-aware clock is required")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MarketWindow:
    observations: tuple[dict, ...]
    observed_at: datetime

    @property
    def latest(self) -> datetime:
        return self.observations[-1]["timestamp"]


def validate_market_rows(
    raw_rows, *, observed_at: datetime, window: int = WINDOW_HOURS
) -> tuple[dict, ...]:
    """Validate exactly one bounded, consecutive, completed hourly window.

    Invalid, duplicate or extra candles reject the request; none are dropped.
    This is in-memory retrieval, never the historical ingestion writer.
    """
    observed_at = _utc(observed_at)
    if type(window) is not int or not 169 <= window <= 500:
        raise MarketDataError("The analysis window must contain 169..500 hours")
    if not isinstance(raw_rows, (list, tuple)) or not raw_rows:
        raise MarketDataError("No BTC/USDT candles returned")
    expected = latest_closed(observed_at)
    closed_ms = int(expected.timestamp() * 1000)
    rows = []
    for raw in raw_rows:
        if (
            not isinstance(raw, (list, tuple))
            or len(raw) != 6
            or type(raw[0]) is not int
            or any(type(v) not in (int, float) for v in raw[1:])
        ):
            raise MarketDataError("Malformed candle timestamp or OHLCV fields")
        try:
            finite = all(math.isfinite(v) for v in raw[1:])
        except (OverflowError, ValueError):
            finite = False
        if not finite:
            raise MarketDataError("Nonfinite OHLCV value")
        if raw[0] > closed_ms:
            raise MarketDataError(
                "Incomplete or future candle returned; analysis rejected"
            )
        row = normalize(
            {
                "raw_ohlcv": json.dumps(list(raw)),
                "observed_at": observed_at,
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "observation_id": "on-demand-public-observation",
            },
            closed_ms,
        )
        if row is None:
            raise MarketDataError("Invalid OHLCV or non-hour-aligned candle")
        rows.append(
            {
                name: row[name]
                for name in (
                    "timestamp",
                    "ingested_at",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                )
            }
        )
    rows.sort(key=lambda row: row["timestamp"])
    timestamps = tuple(row["timestamp"] for row in rows)
    if len(set(timestamps)) != len(timestamps):
        raise MarketDataError("Duplicate hourly candles returned")
    if timestamps[-1] != expected:
        raise MarketDataError("Stale data: latest completed UTC hour is missing")
    if len(rows) != window or any(
        timestamp != expected - (window - index - 1) * HOUR
        for index, timestamp in enumerate(timestamps)
    ):
        raise MarketDataError(
            "Missing or unexpected hourly observations; gaps are not filled"
        )
    return tuple(rows)


def fetch_recent_market(
    *, exchange=None, clock=utc_now, window: int = WINDOW_HOURS
) -> MarketWindow:
    """Fetch only a recent public Spot window with bounded retries/timeouts."""
    if type(window) is not int or not 169 <= window <= 500:
        raise MarketDataError("The analysis window must contain 169..500 hours")
    client = exchange if exchange is not None else binance_spot()
    if exchange is None:
        client.timeout = 8000
        client.options["fetchMarkets"] = {"types": ["spot"]}
        client.options["fetchCurrencies"] = False
    try:
        server_ms = client.fetch_time()
        requested_at = _utc(clock())
        if type(server_ms) is not int:
            raise MarketDataError("Invalid Binance server clock")
        server_at = datetime.fromtimestamp(server_ms / 1000, tz=UTC)
        if abs((server_at - requested_at).total_seconds()) > 60:
            raise MarketDataError(
                "Local clock and Binance clock differ by over 60 seconds"
            )
        if server_at.replace(minute=0, second=0, microsecond=0) != (
            requested_at.replace(minute=0, second=0, microsecond=0)
        ):
            raise MarketDataError(
                "UTC hour boundary differs from Binance; retry shortly"
            )
        expected = latest_closed(requested_at)
        end_ms = int(expected.timestamp() * 1000)
        start_ms = end_ms - (window - 1) * HOUR_MS
        raw = [
            row
            for page in fetch_pages(
                client,
                "BTC/USDT",
                start_ms,
                end_ms,
                page_size=window,
                max_retries=1,
            )
            for row in page
        ]
        observed_at = _utc(clock())
        if observed_at < requested_at or latest_closed(observed_at) != expected:
            raise MarketDataError("UTC hour changed during retrieval; refresh again")
        observations = validate_market_rows(raw, observed_at=observed_at, window=window)
        return MarketWindow(observations, observed_at)
    except MarketDataError:
        raise
    except Exception as exc:
        # Provider failures remain explicit; there is no alternate provider or
        # stale historical fallback pretending to be current market data.
        raise MarketDataError(
            f"Binance data unavailable ({type(exc).__name__}): {exc}"
        ) from exc


def assess_direction(indicators: dict[str, float]) -> tuple[str, list[str]]:
    """Fixed sign/volatility heuristic, not a forecast or estimated probability."""
    if set(indicators) != set(FEATURES) or any(
        type(v) not in (float, int) or not math.isfinite(v) for v in indicators.values()
    ):
        raise MarketDataError("All seven features must be present and finite")
    if any(
        indicators[name] < 0
        for name in ("volatility_24h", "volatility_168h", "normalized_range_1h")
    ):
        raise MarketDataError("Invalid negative volatility or normalized range")
    threshold = 0.5 * indicators["volatility_24h"]
    momentum = indicators["momentum_24h"]
    weekly = indicators["momentum_168h"]
    recent = indicators["log_return_1h"]
    if threshold == 0:
        return "HOLD", ["No measured 24h return volatility; no valid entry condition."]
    if momentum > threshold and weekly > 0 and recent > 0:
        return "BUY", [
            "24h momentum exceeds half the 24h hourly-return standard deviation.",
            "168h momentum and the latest completed hourly log return are positive.",
        ]
    if momentum < -threshold and weekly < 0 and recent < 0:
        return "SELL", [
            "24h momentum is below minus half the hourly-return standard deviation.",
            "168h momentum and the latest completed hourly log return are negative.",
        ]
    return "HOLD", [
        "24h momentum, 168h momentum and the latest hourly return "
        "do not meet the same directional condition."
    ]


def calculate_atr(window: MarketWindow) -> float:
    """ATR(14) in USDT: 14 true-range mean, then Wilder smoothing.

    Fifteen closed consecutive candles supply the first 14 true ranges. The
    first candle supplies only the previous close; no missing prior close is
    invented. All provided rows are checked as of the explicit observation
    time. Runtime freshness is also checked by the existing HTTP boundary.
    The normal 200-candle fetch is the deterministic seed/window, not a claim
    to reproduce a chart initialized with a longer historical series.
    """
    if not isinstance(window, MarketWindow) or not isinstance(
        window.observations, (tuple, list)
    ):
        raise MarketDataError("ATR requires a validated candle window")
    if not ATR_PERIOD + 1 <= len(window.observations) <= 500:
        raise MarketDataError("ATR(14) requires at least 15 completed hourly candles")
    observed_at = _utc(window.observed_at)
    try:
        rows = _validate_observations(window.observations, observed_at)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"Invalid ATR candles: {exc}") from exc
    if rows[-1]["timestamp"] != latest_closed(observed_at):
        raise MarketDataError("Stale ATR data: latest completed UTC hour is missing")
    true_ranges = []
    for previous, row in zip(rows, rows[1:]):
        if row["timestamp"] - previous["timestamp"] != HOUR:
            raise MarketDataError("Missing hourly ATR candles; gaps are not filled")
        true_range = max(
            row["high"] - row["low"],
            abs(row["high"] - previous["close"]),
            abs(row["low"] - previous["close"]),
        )
        if not math.isfinite(true_range):
            raise MarketDataError("Nonfinite ATR true range")
        true_ranges.append(true_range)
    # Scale before summation to avoid overflowing a representable mean.
    atr = math.fsum(value / ATR_PERIOD for value in true_ranges[:ATR_PERIOD])
    for true_range in true_ranges[ATR_PERIOD:]:
        atr = math.fsum((atr * (13 / 14), true_range / ATR_PERIOD))
    if not math.isfinite(atr) or atr <= 0:
        raise MarketDataError("ATR(14) must be finite and positive")
    return atr


def reference_levels(decision: str, *, entry: float, atr: float) -> dict | None:
    """Unrounded reference estimates only; never broker/executable prices."""
    if decision == "HOLD":
        return None
    if decision not in {"BUY", "SELL"}:
        raise MarketDataError("Unknown reference-level decision")
    try:
        valid = all(
            type(value) in (int, float) and math.isfinite(value) and value > 0
            for value in (entry, atr)
        )
    except OverflowError:
        valid = False
    if not valid:
        raise MarketDataError("Entry and ATR must be finite and positive")
    entry, atr = float(entry), float(atr)
    stop = entry - 1.5 * atr if decision == "BUY" else entry + 1.5 * atr
    take_profit = entry + 3.0 * atr if decision == "BUY" else entry - 3.0 * atr
    if (
        not all(math.isfinite(value) and value > 0 for value in (stop, take_profit))
        or (decision == "BUY" and not stop < entry < take_profit)
        or (decision == "SELL" and not take_profit < entry < stop)
    ):
        raise MarketDataError("ATR cannot produce positive distinct reference SL/TP")
    risk_distance = abs(entry - stop)
    reward_distance = abs(take_profit - entry)
    if not (
        math.isclose(risk_distance, 1.5 * atr, rel_tol=1e-10, abs_tol=0.0)
        and math.isclose(reward_distance, 3.0 * atr, rel_tol=1e-10, abs_tol=0.0)
        and math.isclose(reward_distance, 2.0 * risk_distance, rel_tol=1e-10)
    ):
        raise MarketDataError("Reference SL/TP precision cannot preserve 1:2 distances")
    return {
        "label": REFERENCE_LABEL,
        "entry": entry,
        "stop_loss": stop,
        "take_profit": take_profit,
        "risk_reward": "1:2",
        "currency": "USDT",
        "atr_period": ATR_PERIOD,
        "atr_method": "Wilder RMA",
    }


def market_payload(window: MarketWindow) -> dict:
    observed_at = _utc(window.observed_at)
    # Revalidate callers' in-memory input before exposing a current-data label.
    raw = [
        [
            int(row["timestamp"].timestamp() * 1000),
            *[row[name] for name in ("open", "high", "low", "close", "volume")],
        ]
        for row in window.observations
    ]
    rows = validate_market_rows(raw, observed_at=observed_at, window=len(raw))
    latest = rows[-1]["timestamp"]
    return {
        "source": SOURCE,
        "execution_instrument": "Exness BTC CFD — Demo (not validated)",
        "mode": "INFORMATIONAL / MANUAL EXECUTION ONLY",
        "generated_at": _iso(observed_at),
        "expires_at": _iso(
            min(
                observed_at + timedelta(minutes=5),
                observed_at.replace(minute=0, second=0, microsecond=0) + HOUR,
            )
        ),
        "latest_candle_timestamp": _iso(latest),
        "market_timestamp": _iso(latest),
        "candle_end_at": _iso(latest + HOUR),
        "quality_status": "VALIDATED CONTIGUOUS COMPLETED WINDOW",
        "data_freshness": {
            "status": "LATEST COMPLETED UTC HOUR",
            "age_seconds": (observed_at - latest - HOUR).total_seconds(),
        },
        "candle_count": len(rows),
        "candles": [
            {
                "time": int(row["timestamp"].timestamp()),
                **{name: row[name] for name in ("open", "high", "low", "close")},
            }
            for row in rows
        ],
        "decision": "HOLD",
        "actionable": False,
        "atr_14": None,
        "reference_levels": None,
        "entry_reference": None,
        "risk": {
            "status": "DISABLED",
            "actionable": False,
            "reasons": ["Position sizing, margin and broker costs are disabled."],
        },
        "warnings": WARNINGS,
    }


def build_analysis(window: MarketWindow) -> dict:
    payload = market_payload(window)
    try:
        frame = prepare_shared_features(
            window.observations,
            AnomalyManifest("pqta-personal-observation-v1", None, ()),
            analysis_as_of=window.observed_at,
            expected_latest_candle=window.latest,
            generated_at=window.observed_at,
        )
        latest = frame.row(-1, named=True)
        indicators = {name: latest[name] for name in FEATURES}
        decision, explanations = assess_direction(indicators)
    except ValueError as exc:
        raise MarketDataError(f"Feature validation failed: {exc}") from exc
    atr = calculate_atr(window)
    levels = reference_levels(decision, entry=window.observations[-1]["close"], atr=atr)
    return {
        **payload,
        "strategy": STRATEGY,
        "decision": decision,
        "directional_assessment": decision,
        "explanations": explanations,
        "indicators": indicators,
        "atr_14": atr,
        "atr_method": ATR_METHOD,
        "reference_levels": levels,
        "entry_reference": levels["entry"] if levels else None,
        "entry_reference_currency": "USDT (Binance reference only)" if levels else None,
        "feature_decision_eligible": latest["decision_eligible"],
        "feature_available_at": None,
    }


def failure_payload(message: str) -> dict:
    return {
        "source": SOURCE,
        "decision": "HOLD",
        "directional_assessment": "HOLD",
        "actionable": False,
        "quality_status": "REJECTED / UNAVAILABLE",
        "atr_14": None,
        "reference_levels": None,
        "entry_reference": None,
        "error": message,
        "explanations": [message],
        "risk": {"status": "DISABLED", "actionable": False},
        "warnings": WARNINGS,
        "candles": [],
        "candle_count": 0,
    }
