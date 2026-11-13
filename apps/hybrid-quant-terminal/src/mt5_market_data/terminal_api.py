"""Read-only, bounded HTTP access to integrity-checked historical Silver snapshots.

The terminal works in the broker's unverified clock; it never supplies broker
credentials or sends orders. Snapshot validation is repeated on each request.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from polars.exceptions import PolarsError

from .broker_native import compare_probe_records, read_untrusted_native_probe
from .broker_risk import (
    assess_untrusted_specification,
    illustrative_budget,
    read_untrusted_broker_snapshot,
    unavailable_broker_risk,
)
from .external_market import ExternalMarketService, ProviderError
from .external_terminal import analyze_external
from .market import load_snapshot
from .mt5_bridge import BridgeService, ConsumerOwnershipError
from .terminal_analysis import AnalysisConfig, analyze_bars
from .validation import MARKETS, PERIODS

# Bounded analytical context, including indicator warm-up and confirmed pivots.
CONTEXT_BARS = 2000
DEFAULT_BARS = 1000
MAX_BARS = 2000
BROKER_CLOCK = "Broker server time (timezone unverified)"

PUBLIC_EXTERNAL_ERRORS = {
    "missing_api_key": "Set MASSIVE_API_KEY locally to use external data.",
    "unsupported_symbol": "The external provider does not support this symbol.",
    "unsupported_timeframe": "External H4 is disabled until its session anchor is verified.",
    "authentication_or_entitlement": "Provider rejected the key or instrument entitlement.",
    "rate_limited": "Provider rate limit reached; retry later.",
    "refresh_throttled": "A recent refresh was attempted; retry after the cooldown.",
    "network_error": "External data request failed or timed out.",
    "cache_corrupt": "External cache failed integrity validation.",
    "malformed_data": "Provider returned malformed data.",
    "malformed_timestamp": "Provider returned an invalid timestamp.",
    "duplicate_timestamp": "Provider returned duplicate timestamps.",
    "invalid_ohlc": "Provider returned inconsistent OHLC values.",
    "unexpected_coverage": "Provider returned data outside the requested window.",
    "pagination_required": "Provider returned a partial page; no data was accepted.",
    "empty_response": "No conservatively completed candles are available.",
    "not_cached": "No validated external snapshot is available. Refresh the source first.",
    "provider_error": "External provider request failed.",
}


def public_external_error(code: object) -> str:
    # Do not forward network/server text: it may contain credentials or private paths.
    safe_code = (
        code
        if isinstance(code, str) and code in PUBLIC_EXTERNAL_ERRORS
        else "provider_error"
    )
    return f"{safe_code}: {PUBLIC_EXTERNAL_ERRORS[safe_code]}"


def _analyze(rows: list[dict], timeframe: str, config: AnalysisConfig) -> dict:
    return analyze_bars(rows, timeframe, config=config)


def analysis_config(
    left: int = Query(3, ge=1, le=20),
    right: int = Query(3, ge=1, le=20),
    tolerance_atr: float = Query(0.5, gt=0, le=5, allow_inf_nan=False),
    min_touches: int = Query(2, ge=2, le=20),
    min_separation: int = Query(3, ge=1, le=500),
    buffer_atr: float = Query(0.1, gt=0, le=5, allow_inf_nan=False),
    risk_reward: float = Query(2.0, gt=0, le=10, allow_inf_nan=False),
) -> AnalysisConfig:
    return AnalysisConfig(
        left=left,
        right=right,
        tolerance_atr=tolerance_atr,
        min_touches=min_touches,
        min_separation=min_separation,
        buffer_atr=buffer_atr,
        risk_reward=risk_reward,
    )


CONFIG_DEPENDENCY = Depends(analysis_config)


def _mt5_health_allows_current_analysis(health: dict) -> bool:
    """Reject missing or contradictory evidence; old unknown gaps remain visible."""
    gaps = health.get("unresolved_gap_count")
    revisions = health.get("unresolved_revision_count")
    segment = health.get("current_segment_count")
    history = health.get("history_count")
    return (
        health.get("status") == "LIVE"
        and type(gaps) is int
        and gaps >= 0
        and type(revisions) is int
        and revisions == 0
        and type(segment) is int
        and type(history) is int
        and 50 <= segment <= history
    )


class HistoricalService:
    """Verify every load; cache only calculations bound to snapshot identity."""

    def __init__(
        self,
        loader: Callable[..., tuple[list[dict], dict]] | None = None,
        analyzer: Callable[[list[dict], str, AnalysisConfig], dict] | None = None,
    ) -> None:
        historical_root = os.environ.get("MT5_HISTORICAL_ROOT")
        if loader is None and historical_root:
            configured_root = Path(historical_root).expanduser().resolve()

            def configured_loader(symbol: str, timeframe: str):
                return load_snapshot(
                    symbol,
                    timeframe,
                    root=configured_root,
                    permitted_root=configured_root,
                )

            self._loader = configured_loader
        else:
            self._loader = loader or load_snapshot
        self._analyzer = analyzer or _analyze
        self._cache: dict[tuple[str, str, str, AnalysisConfig], dict] = {}
        self._lock = Lock()

    def read(
        self,
        symbol: str,
        timeframe: str,
        *,
        analytical: bool = False,
        config: AnalysisConfig | None = None,
    ) -> dict:
        if symbol not in MARKETS or timeframe not in PERIODS:
            raise HTTPException(
                status_code=422, detail="Unsupported symbol or timeframe"
            )
        try:
            # This verifies all Parquet byte hashes, schema, source identities and
            # the logical snapshot hash before any cached result may be used.
            rows, identity = self._loader(symbol, timeframe)
            snapshot = identity["snapshot_sha256"]
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Historical snapshot is missing"
            ) from exc
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            PolarsError,
        ) as exc:
            raise HTTPException(
                status_code=409, detail="Historical snapshot failed validation"
            ) from exc
        result: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "snapshot_sha256": snapshot,
            "broker_time_label": BROKER_CLOCK,
            "historical": True,
        }
        if analytical:
            # The owner-provided contract sizes are illustrative, not broker-verified.
            config = replace(
                config or AnalysisConfig(),
                contract_size=100_000 if symbol == "EURUSDm" else 100,
            )
            key = (symbol, timeframe, snapshot, config)
            with self._lock:
                if key not in self._cache:
                    # Keep just one identity per market; changed snapshots invalidate
                    # previous calculations. History before the bound is not loaded
                    # into analysis and is not implied to be fully represented.
                    self._cache = {
                        k: v for k, v in self._cache.items() if k[:2] != key[:2]
                    }
                    try:
                        self._cache[key] = self._analyzer(
                            rows[-CONTEXT_BARS:], timeframe, config
                        )
                    except (ValueError, TypeError, KeyError, OverflowError) as exc:
                        raise HTTPException(
                            status_code=409,
                            detail="Historical analysis failed validation",
                        ) from exc
                result.update(self._cache[key])
            result["analysis_context_bars"] = min(len(rows), CONTEXT_BARS)
            result["analysis_config"] = asdict(config)
        else:
            result["candles"] = rows
        return result


# A single process may expose multiple app objects but owns only one live reader.
_default_bridge_lock = Lock()
_default_bridge = None
_default_bridge_factory = None
_default_bridge_pid = None


def _reset_bridge_after_fork() -> None:
    global \
        _default_bridge_lock, \
        _default_bridge, \
        _default_bridge_factory, \
        _default_bridge_pid
    _default_bridge_lock = Lock()
    _default_bridge = None
    _default_bridge_factory = None
    _default_bridge_pid = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_bridge_after_fork)


def _shared_default_bridge():
    global _default_bridge, _default_bridge_factory, _default_bridge_pid
    with _default_bridge_lock:
        if (
            _default_bridge is None
            or _default_bridge_factory is not BridgeService
            or _default_bridge_pid != os.getpid()
            or getattr(_default_bridge, "_closed", False)
        ):
            _default_bridge = BridgeService()
            _default_bridge_factory = BridgeService
            _default_bridge_pid = os.getpid()
        return _default_bridge


def create_app(
    service: HistoricalService | None = None,
    external_service: ExternalMarketService | None = None,
    bridge_service: BridgeService | None = None,
) -> FastAPI:
    app = FastAPI(title="Quant Terminal — Market Data", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    historical = service or HistoricalService()
    external = external_service or ExternalMarketService()
    try:
        bridge = (
            bridge_service
            if bridge_service is not None
            else (
                None
                if os.environ.get("MT5_DISABLE_LIVE_BRIDGE") == "1"
                else _shared_default_bridge()
            )
        )
    except ConsumerOwnershipError as exc:
        raise RuntimeError("MT5 consumer ownership unavailable") from exc
    except (OSError, ValueError):
        # A damaged live checkpoint must not take historical/external sources down.
        bridge = None
    bridge_analyses: dict[tuple[str, str, str, AnalysisConfig], dict] = {}
    bridge_analysis_lock = Lock()

    def external_status(symbol: str, timeframe: str, *, force: bool = False) -> dict:
        try:
            snapshot = external.get(symbol, timeframe, force=force)
        except ProviderError as exc:
            # Do not expose provider bodies, URLs, or credentials.
            return {
                "provider": "Massive",
                "source": "massive",
                "freshness": "UNAVAILABLE",
                "provider_delay": "END_OF_DAY",
                "last_successful_fetch": None,
                "latest_completed_candle": None,
                "latest_observed_candle": None,
                "latest_nominally_closed_candle": None,
                "provider_finality_verified": False,
                "gap_count": None,
                "gaps": [],
                "gaps_truncated": False,
                "snapshot_sha256": None,
                "error": public_external_error(exc.code),
            }
        error = snapshot.get("error")
        if isinstance(error, dict):
            error = public_external_error(error.get("code"))
        gaps = snapshot.get("gaps", [])
        return {
            "provider": "Massive",
            "source": "massive",
            "freshness": snapshot.get("freshness", "DELAYED_EOD"),
            "provider_delay": "END_OF_DAY",
            "last_successful_fetch": snapshot.get("last_successful_fetch_utc"),
            # Passing an elapsed-time check is not provider-verified finality.
            "latest_completed_candle": None,
            "latest_observed_candle": (
                snapshot.get("latest_observed_candle") or {}
            ).get("timestamp_utc"),
            "latest_nominally_closed_candle": snapshot.get(
                "latest_nominally_closed_candle_utc"
            ),
            "provider_finality_verified": False,
            "gap_count": len(gaps),
            "gaps": gaps[:100],
            "gaps_truncated": len(gaps) > 100,
            "snapshot_sha256": snapshot.get("snapshot_sha256"),
            "error": error,
        }

    def read_external(
        symbol: str,
        timeframe: str,
        *,
        analytical: bool = False,
        config: AnalysisConfig | None = None,
    ) -> dict:
        try:
            # Chart endpoints never contact the provider, and a snapshot is
            # integrity checked on every cache read.
            snapshot = external.read_cached(symbol, timeframe)
            if snapshot is None:
                raise ProviderError(
                    "not_cached",
                    "No validated external snapshot is available. Refresh the source first.",
                )
            rows = snapshot["candles"]
            result = {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": "massive",
                "provider": "Massive",
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "historical": True,
                "broker_time_label": "UTC (external provider)",
                "provider_delay": "END_OF_DAY",
            }
            if analytical:
                settings = replace(config or AnalysisConfig(), contract_size=None)
                result.update(
                    analyze_external(rows[-CONTEXT_BARS:], timeframe, settings)
                )
                result["analysis_context_bars"] = min(len(rows), CONTEXT_BARS)
                result["analysis_config"] = asdict(settings)
            else:
                result["candles"] = [
                    {
                        "timestamp": row["timestamp_utc"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "tick_volume": None,
                        "spread_points": None,
                        "real_volume": None,
                        "provider_volume": row.get("provider_volume"),
                    }
                    for row in rows
                ]
            return result
        except ProviderError as exc:
            raise HTTPException(
                status_code=409, detail=public_external_error(exc.code)
            ) from exc
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise HTTPException(
                status_code=409, detail="External snapshot failed validation"
            ) from exc

    def read_mt5(
        symbol: str,
        timeframe: str,
        *,
        analytical: bool = False,
        config: AnalysisConfig | None = None,
    ) -> dict:
        if symbol not in MARKETS or timeframe not in PERIODS:
            raise HTTPException(
                status_code=422, detail="Unsupported symbol or timeframe"
            )
        if bridge is None:
            raise HTTPException(
                status_code=409,
                detail="MT5 runtime checkpoint is unavailable or invalid.",
            )
        try:
            snapshot = bridge.get(symbol, timeframe)
            rows = snapshot["candles"]
            identity = snapshot["snapshot_sha256"]
            health = snapshot["health"]
            if not identity or not rows:
                raise HTTPException(
                    status_code=409, detail="No validated MT5 candles are available."
                )
            result: dict[str, Any] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": "mt5",
                "snapshot_sha256": identity,
                "broker_time_label": BROKER_CLOCK,
                "historical": False,
                "continuity": "INCREMENTAL_ONLY_UNVERIFIED",
                "feed_health": health,
            }
            if analytical:
                # MT5 connection health does not authenticate contract or lot sizes.
                settings = replace(config or AnalysisConfig(), contract_size=None)
                key = (symbol, timeframe, identity, settings)
                with bridge_analysis_lock:
                    if key not in bridge_analyses:
                        bridge_analyses.clear()
                        bridge_analyses[key] = analyze_bars(
                            rows[-CONTEXT_BARS:], timeframe, config=settings
                        )
                    calculated = deepcopy(bridge_analyses[key])
                analysis = calculated.get("analysis")
                if analysis is not None:
                    # The existing engine is conservative and always blocks execution.
                    analysis["overall_action"] = "WAIT"
                    analysis["execution_eligibility"] = "BLOCKED_UNVERIFIED"
                    analysis["target_reference_scope"] = (
                        "latest completed broker-clock candle close only; no fill inferred"
                    )
                    analysis["blocking_reasons"] = [
                        "Broker-clock timezone and execution specifications are unverified.",
                        "Incremental MT5 cache is separate from the historical snapshots.",
                    ] + [
                        reason
                        for reason in analysis["blocking_reasons"]
                        if not reason.startswith("Historical broker-clock")
                        and not reason.startswith("Broker contract")
                    ]
                    risk = analysis["risk"]
                    risk["minimum_lot"] = None
                    risk["lot_step"] = None
                    risk["contract_size_assumption"] = None
                    risk["risk_check"] = "UNVERIFIED"
                    risk["feasibility"] = "UNVERIFIED"
                    risk["assumptions"] = (
                        "Broker specifications, quote and execution remain unverified."
                    )
                    indicators_ready = all(
                        analysis.get(name) is not None
                        for name in ("ema20", "ema50", "atr14", "adx14")
                    )
                    if not indicators_ready:
                        analysis["blocking_reasons"].append(
                            "Insufficient consecutive validated history for indicator warm-up."
                        )
                    if (
                        not _mt5_health_allows_current_analysis(health)
                        or not indicators_ready
                    ):
                        # Prevent stale or unverified levels from appearing actionable.
                        analysis["direction"] = "WAIT"
                        for name in (
                            "entry",
                            "stop_loss",
                            "take_profit",
                            "risk_reward",
                            "trigger_reached",
                        ):
                            analysis[name] = None
                        analysis["blocking_reasons"].append(
                            "Feed health or indicator history is not verified for current analysis."
                        )
                result.update(calculated)
                result["analysis_context_bars"] = min(len(rows), CONTEXT_BARS)
                result["analysis_config"] = asdict(settings)
            else:
                result["candles"] = rows
            return result
        except HTTPException:
            raise
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise HTTPException(
                status_code=409, detail="MT5 runtime cache failed validation."
            ) from exc

    def read_source(
        source: str,
        symbol: str,
        timeframe: str,
        *,
        analytical: bool = False,
        config: AnalysisConfig | None = None,
    ) -> dict:
        if source == "mt5":
            return read_mt5(symbol, timeframe, analytical=analytical, config=config)
        if source == "massive":
            return read_external(
                symbol, timeframe, analytical=analytical, config=config
            )
        result = historical.read(
            symbol, timeframe, analytical=analytical, config=config
        )
        result["source"] = "exness"
        return result

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "mode": "local_read_only" if bridge is not None else "historical_offline",
            "broker_time_verified": False,
        }

    @app.get("/api/symbols")
    def symbols() -> dict:
        return {"symbols": sorted(MARKETS), "timeframes": list(PERIODS)}

    @app.get("/api/mt5/status")
    def mt5_status(symbol: str = "EURUSDm", timeframe: str = "M15") -> dict:
        if symbol not in MARKETS or timeframe not in PERIODS:
            raise HTTPException(
                status_code=422, detail="Unsupported symbol or timeframe"
            )
        if bridge is None:
            return {
                "source": "mt5",
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "UNVERIFIED",
                "reasons": ["MT5 runtime checkpoint is unavailable or invalid."],
                "snapshot_sha256": None,
                "latest_completed_candle": None,
                "last_ingestion_utc": None,
                "heartbeat_age_seconds": None,
                "target_quote_status": "UNVERIFIED",
                "connection_status": "UNVERIFIED",
                "unresolved_gap_count": None,
                "current_segment_count": 0,
                "history_count": 0,
                "continuity": "INCREMENTAL_ONLY_UNVERIFIED",
            }
        try:
            bridge.poll()
            result = bridge.get(symbol, timeframe)
            return {
                **result["health"],
                "source": "mt5",
                "symbol": symbol,
                "timeframe": timeframe,
                "snapshot_sha256": result["snapshot_sha256"],
                "continuity": "INCREMENTAL_ONLY_UNVERIFIED",
            }
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(
                status_code=409, detail="MT5 handoff validation failed."
            ) from exc

    @app.get("/api/external/status")
    def status(symbol: str = "EURUSDm", timeframe: str = "M15") -> dict:
        return external_status(symbol, timeframe)

    @app.post("/api/external/refresh")
    def refresh(
        request: Request, symbol: str = "EURUSDm", timeframe: str = "M15"
    ) -> dict:
        origin = request.headers.get("origin")
        if origin and origin not in {"http://localhost:5173", "http://127.0.0.1:5173"}:
            raise HTTPException(
                status_code=403, detail="External refresh origin is not allowed"
            )
        return external_status(symbol, timeframe, force=True)

    @app.get("/api/candles")
    def candles(
        symbol: str = "EURUSDm",
        timeframe: str = "M15",
        limit: int = Query(DEFAULT_BARS, ge=1, le=MAX_BARS),
        source: Literal["exness", "massive", "mt5"] = "exness",
    ) -> dict:
        result = read_source(source, symbol, timeframe)
        fields = (
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "tick_volume",
            "spread_points",
            "real_volume",
        )
        result["candles"] = [
            {key: row[key] for key in fields} for row in result["candles"][-limit:]
        ]
        return result

    def analysis_subset(
        symbol: str,
        timeframe: str,
        names: tuple[str, ...],
        config: AnalysisConfig,
        source: str,
    ) -> dict:
        result = read_source(source, symbol, timeframe, analytical=True, config=config)
        keys = (
            "symbol",
            "timeframe",
            "snapshot_sha256",
            "broker_time_label",
            "historical",
            "source",
            "analysis_context_bars",
            "analysis_config",
            *names,
        )
        response = {key: result[key] for key in keys}
        if source == "mt5":
            # Bind analytical output to the same observed health as its snapshot.
            response["feed_health"] = result["feed_health"]
            response["continuity"] = result["continuity"]
        if "analysis" in names:
            # Observation time is not publication time or model-computation time.
            response["analysis_observed_at_utc"] = datetime.now(UTC).isoformat()
            analysis = result.get("analysis")
            response["setup_reference_provenance"] = (
                {
                    "source_candle_open": analysis.get("timestamp"),
                    "theoretical_candle_end": analysis.get("available_at_timestamp"),
                    "entry_basis": "confirmed_pattern_neckline",
                    "stop_basis": "pattern_anchors_and_latest_snapshot_atr",
                    "target_basis": "current_entry_stop_distance_and_configured_ratio",
                    "historical_execution_record": False,
                }
                if isinstance(analysis, dict) and analysis.get("entry") is not None
                else None
            )
        return response

    @app.get("/api/indicators")
    def indicators(
        symbol: str = "EURUSDm",
        timeframe: str = "M15",
        config: AnalysisConfig = CONFIG_DEPENDENCY,
        source: Literal["exness", "massive", "mt5"] = "exness",
    ) -> dict:
        return analysis_subset(symbol, timeframe, ("indicators",), config, source)

    @app.get("/api/patterns")
    def patterns(
        symbol: str = "EURUSDm",
        timeframe: str = "M15",
        config: AnalysisConfig = CONFIG_DEPENDENCY,
        source: Literal["exness", "massive", "mt5"] = "exness",
    ) -> dict:
        return analysis_subset(
            symbol, timeframe, ("swings", "zones", "patterns"), config, source
        )

    @app.get("/api/analysis")
    def analysis(
        symbol: str = "EURUSDm",
        timeframe: str = "M15",
        config: AnalysisConfig = CONFIG_DEPENDENCY,
        source: Literal["exness", "massive", "mt5"] = "exness",
    ) -> dict:
        return analysis_subset(symbol, timeframe, ("analysis",), config, source)

    @app.get("/api/runtime-identity")
    def runtime_identity() -> dict:
        # Local operational evidence only; paths do not authenticate a source.
        return {
            "api_module": str(Path(__file__).resolve()),
            "project_root": str(Path(__file__).resolve().parents[2]),
            "runtime_state": str(bridge.state_dir)
            if getattr(bridge, "state_dir", None) is not None
            else None,
            "handoff": str(bridge.handoff_dir)
            if getattr(bridge, "handoff_dir", None) is not None
            else None,
            "historical_root": os.environ.get("MT5_HISTORICAL_ROOT")
            or str(Path(__file__).resolve().parents[2]),
            "execution_eligibility": "BLOCKED_UNVERIFIED",
        }

    @app.get("/api/broker-specification")
    def broker_specification(symbol: str = "EURUSDm") -> dict:
        if symbol not in MARKETS:
            raise HTTPException(status_code=422, detail="Unsupported symbol")
        path = (
            Path(__file__).resolve().parents[2] / "runtime" / "broker_spec_snapshot.csv"
        )
        try:
            snapshot = read_untrusted_broker_snapshot(path)
        except (OSError, ValueError):
            return {
                "instrument": symbol,
                "specification_status": "UNAVAILABLE",
                "verification_status": "UNVERIFIED",
                "snapshot_sha256": None,
                "properties": [],
                "warning": "No valid configured local snapshot is available.",
            }
        symbol_present = any(
            record.instrument == symbol for record in snapshot.properties
        )
        return {
            "instrument": symbol,
            "specification_status": (
                "OBSERVED_UNAUTHENTICATED" if symbol_present else "NO_SYMBOL_DATA"
            ),
            "verification_status": "UNVERIFIED",
            "snapshot_sha256": snapshot.payload_sha256,
            "assessment": assess_untrusted_specification(snapshot, symbol),
            "properties": [
                asdict(record)
                for record in snapshot.properties
                if record.instrument in ("", symbol)
            ],
            "warning": "Local CSV values and digest do not authenticate the broker, account, time or source.",
        }

    @app.get("/api/broker-native-comparison")
    def broker_native_comparison(symbol: str = "EURUSDm") -> dict:
        if symbol not in MARKETS:
            raise HTTPException(status_code=422, detail="Unsupported symbol")
        runtime = Path(__file__).resolve().parents[2] / "runtime"
        try:
            snapshot = read_untrusted_broker_snapshot(
                runtime / "broker_spec_snapshot.csv"
            )
            payload, records = read_untrusted_native_probe(
                runtime / "broker_native_probe.csv"
            )
        except (OSError, ValueError):
            return {
                "instrument": symbol,
                "verification_status": "UNVERIFIED",
                "comparisons": [],
                "warning": "Valid local snapshot and native probe are unavailable.",
            }
        return compare_probe_records(payload, records, snapshot, symbol)

    @app.get("/api/broker-risk")
    def broker_risk(
        symbol: str = "EURUSDm",
        timeframe: str = "M15",
        config: AnalysisConfig = CONFIG_DEPENDENCY,
        risk_budget_usd: str | None = Query(None, max_length=64),
    ) -> dict:
        # Parse as a string so NaN/Infinity cannot leak into JSON validation errors.
        try:
            budget = (
                illustrative_budget(risk_budget_usd)
                if risk_budget_usd is not None
                else None
            )
        except (ValueError, OverflowError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Risk budget must be finite, positive and no more than 1,000,000 USD.",
            ) from exc
        try:
            current = read_mt5(symbol, timeframe, analytical=True, config=config)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            current = {"symbol": symbol, "timeframe": timeframe}
        return unavailable_broker_risk(current, risk_budget_usd=budget)

    return app


app = create_app()
