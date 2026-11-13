"""Read-only terminal routes use validated, bounded synthetic snapshots."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_pipeline import make_export

from mt5_market_data.market import load_snapshot
from mt5_market_data.pipeline import ingest
from mt5_market_data.terminal_api import HistoricalService, create_app


def _bar(hour):
    return {
        "timestamp": datetime(2024, 1, 1) + timedelta(hours=hour),
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "tick_volume": 10,
        "spread_points": 2,
        "real_volume": 0,
    }


def _empty_analysis(rows, timeframe, config):
    return {
        "indicators": [],
        "swings": [],
        "zones": [],
        "patterns": [],
        "analysis": {"close": rows[-1]["close"]},
    }


def test_api_responses_are_bounded_and_broker_naive():
    service = HistoricalService(
        lambda s, t: ([_bar(i) for i in range(5)], {"snapshot_sha256": "a" * 64}),
        _empty_analysis,
    )
    client = TestClient(create_app(service))
    assert client.get("/api/health").json()["broker_time_verified"] is False
    assert client.get("/api/symbols").json()["symbols"] == ["EURUSDm", "XAUUSDm"]
    payload = client.get("/api/candles", params={"limit": 2}).json()
    assert len(payload["candles"]) == 2
    assert payload["candles"][-1]["timestamp"] == "2024-01-01T04:00:00"
    assert payload["broker_time_label"].endswith("timezone unverified)")
    for endpoint in ("indicators", "patterns", "analysis"):
        assert client.get(f"/api/{endpoint}").status_code == 200
    assert client.get("/api/candles", params={"limit": 2001}).status_code == 422
    assert client.get("/api/candles", params={"symbol": "../../etc"}).status_code == 422
    assert client.post("/api/candles").status_code == 405


def test_missing_and_invalid_snapshot_errors_are_clear_and_sanitized():
    def loader(symbol, timeframe):
        raise ValueError("private filesystem path")

    client = TestClient(create_app(HistoricalService(loader, _empty_analysis)))
    response = client.get("/api/candles")
    assert response.status_code == 409
    assert "private filesystem path" not in response.text

    def missing(symbol, timeframe):
        raise FileNotFoundError

    client = TestClient(create_app(HistoricalService(missing, _empty_analysis)))
    assert client.get("/api/candles").status_code == 404


def test_cache_follows_validated_snapshot_identity_and_revalidates_every_request():
    state = {"snapshot": "a" * 64, "loads": 0, "calls": 0}

    def loader(symbol, timeframe):
        state["loads"] += 1
        return [_bar(1)], {"snapshot_sha256": state["snapshot"]}

    def analyzer(rows, timeframe, config):
        state["calls"] += 1
        return _empty_analysis(rows, timeframe, config)

    client = TestClient(create_app(HistoricalService(loader, analyzer)))
    assert client.get("/api/analysis").status_code == 200
    assert client.get("/api/analysis").status_code == 200
    assert state["calls"] == 1 and state["loads"] == 2
    state["snapshot"] = "b" * 64
    assert client.get("/api/analysis").json()["snapshot_sha256"] == "b" * 64
    assert state["calls"] == 2 and state["loads"] == 3
    changed = client.get("/api/analysis", params={"risk_reward": 3, "left": 5})
    assert changed.json()["analysis_config"]["risk_reward"] == 3
    assert changed.json()["analysis_config"]["left"] == 5
    assert changed.json()["analysis_config"]["contract_size"] == 100_000
    assert state["calls"] == 3
    assert client.get("/api/analysis", params={"risk_reward": "nan"}).status_code == 422
    assert client.get("/api/analysis", params={"left": 21}).status_code == 422


def test_real_synthetic_parquet_tampering_fails_even_after_cached_analysis(tmp_path):
    data, meta = make_export(tmp_path)
    report = ingest(data, meta, root=tmp_path)

    def loader(symbol, timeframe):
        return load_snapshot(symbol, timeframe, root=tmp_path)

    client = TestClient(create_app(HistoricalService(loader, _empty_analysis)))
    assert client.get("/api/analysis", params={"timeframe": "H1"}).status_code == 200
    base = (
        tmp_path
        / "data/silver/symbol=EURUSDm/timeframe=H1/snapshots"
        / report["silver_snapshot_sha256"]
    )
    part = base / next(iter(report["parquet_sha256"]))
    part.write_bytes(part.read_bytes() + b"tampered")
    assert client.get("/api/analysis", params={"timeframe": "H1"}).status_code == 409


def test_configured_historical_root_is_read_only_and_confined(tmp_path, monkeypatch):
    from mt5_market_data import terminal_api
    from mt5_market_data.market import load_snapshot
    from mt5_market_data.validation import InputError

    data, meta = make_export(tmp_path)
    ingest(data, meta, root=tmp_path)
    monkeypatch.setenv("MT5_HISTORICAL_ROOT", str(tmp_path))
    service = terminal_api.HistoricalService()
    result = service.read("EURUSDm", "H1")
    assert result["historical"] is True
    assert len(result["candles"]) == 2
    with pytest.raises(InputError):
        load_snapshot("EURUSDm", "H1", root=tmp_path.parent, permitted_root=tmp_path)


def test_runtime_identity_reports_source_without_promoting_execution():
    class SyntheticBridge:
        state_dir = "/synthetic/state"
        handoff_dir = "/synthetic/handoff"

    client = TestClient(create_app(bridge_service=SyntheticBridge()))
    response = client.get("/api/runtime-identity")
    assert response.status_code == 200
    body = response.json()
    assert body["api_module"].endswith("/src/mt5_market_data/terminal_api.py")
    assert body["runtime_state"] == "/synthetic/state"
    assert body["handoff"] == "/synthetic/handoff"
    assert body["execution_eligibility"] == "BLOCKED_UNVERIFIED"
    assert client.post("/api/runtime-identity", json={}).status_code == 405


def test_runtime_identity_keeps_missing_paths_null():
    client = TestClient(create_app(bridge_service=object()))
    body = client.get("/api/runtime-identity").json()
    assert body["runtime_state"] is None
    assert body["handoff"] is None
    assert body["execution_eligibility"] == "BLOCKED_UNVERIFIED"


def test_historical_indicator_overflow_returns_sanitized_validation_error():
    def loader(symbol, timeframe):
        return [_bar(0)], {"snapshot_sha256": "a" * 64}

    def failing(*args, **kwargs):
        raise OverflowError("private numerical details")

    client = TestClient(create_app(HistoricalService(loader, failing)))
    response = client.get("/api/analysis")
    assert response.status_code == 409
    assert response.json()["detail"] == "Historical analysis failed validation"
    assert "private numerical details" not in response.text
