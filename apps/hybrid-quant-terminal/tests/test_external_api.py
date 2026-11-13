"""HTTP boundary tests use synthetic cached candles and never access a provider."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from mt5_market_data.external_market import ProviderError
from mt5_market_data.terminal_api import HistoricalService, create_app


def _snapshot():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(60):
        time = start + timedelta(hours=i)
        rows.append(
            {
                "timestamp_utc": time.isoformat().replace("+00:00", "Z"),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "provider_volume": 3,
            }
        )
    observed = {
        **rows[-1],
        "timestamp_utc": (start + timedelta(hours=60))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    return {
        "snapshot_sha256": "b" * 64,
        "symbol": "EURUSDm",
        "timeframe": "H1",
        "candles": rows,
        "provider": "massive",
        "last_successful_fetch_utc": "2025-01-05T00:00:00Z",
        "latest_observed_candle": observed,
        "latest_nominally_closed_candle_utc": rows[-1]["timestamp_utc"],
        "latest_completed_candle_utc": None,
        "freshness": "DELAYED_EOD",
        "error": None,
    }


class FakeExternal:
    def __init__(self, snapshot=None, error=None):
        self.snapshot = snapshot
        self.error = error
        self.fetches = []
        self.cache_reads = 0

    def get(self, symbol, timeframe, *, force=False):
        self.fetches.append((symbol, timeframe, force))
        if self.error:
            raise self.error
        return self.snapshot

    def read_cached(self, symbol, timeframe):
        self.cache_reads += 1
        if timeframe == "H4":
            raise ProviderError("unsupported_timeframe", "H4 is unavailable.")
        return self.snapshot


def _historical():
    def loader(symbol, timeframe):
        row = {
            "timestamp": datetime(2025, 1, 1),
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "tick_volume": 4,
            "spread_points": 1,
            "real_volume": 0,
        }
        return [row], {"snapshot_sha256": "a" * 64}

    return HistoricalService(loader=loader)


def test_chart_reads_only_external_cache_and_isolates_source_and_time():
    external = FakeExternal(_snapshot())
    client = TestClient(create_app(_historical(), external))
    result = client.get(
        "/api/candles", params={"source": "massive", "timeframe": "H1", "limit": 3}
    )
    assert result.status_code == 200
    body = result.json()
    assert body["source"] == "massive"
    assert body["snapshot_sha256"] == "b" * 64
    assert len(body["candles"]) == 3
    assert body["candles"][-1]["timestamp"].endswith("Z")
    assert external.fetches == [] and external.cache_reads == 1
    legacy = client.get("/api/candles", params={"timeframe": "H1"}).json()
    assert legacy["source"] == "exness"
    assert legacy["snapshot_sha256"] == "a" * 64
    assert not legacy["candles"][-1]["timestamp"].endswith("Z")


def test_external_analysis_never_inherits_broker_contract_or_eligibility():
    external = FakeExternal(_snapshot())
    client = TestClient(create_app(_historical(), external))
    result = client.get(
        "/api/analysis", params={"source": "massive", "timeframe": "H1"}
    )
    assert result.status_code == 200
    body = result.json()
    assert body["analysis_config"]["contract_size"] is None
    assert (
        body["analysis"]["timestamp"]
        == external.snapshot["candles"][-1]["timestamp_utc"]
    )
    assert (
        body["analysis"]["timestamp"]
        < external.snapshot["latest_observed_candle"]["timestamp_utc"]
    )
    assert body["analysis"]["overall_action"] == "WAIT"
    assert body["analysis"]["execution_eligibility"] == "BLOCKED_UNVERIFIED"
    assert body["analysis"]["risk"]["minimum_lot"] is None
    assert external.fetches == []


def test_status_labels_unverified_finality_and_refresh_is_explicit():
    external = FakeExternal(_snapshot())
    client = TestClient(create_app(_historical(), external))
    status = client.get("/api/external/status", params={"timeframe": "H1"}).json()
    assert status["freshness"] == "DELAYED_EOD"
    assert status["latest_completed_candle"] is None
    assert status["provider_finality_verified"] is False
    assert status["latest_observed_candle"] == "2025-01-03T12:00:00Z"
    assert status["latest_nominally_closed_candle"] == "2025-01-03T11:00:00Z"
    assert external.fetches[-1] == ("EURUSDm", "H1", False)
    refreshed = client.post("/api/external/refresh", params={"timeframe": "H1"})
    assert refreshed.status_code == 200
    assert external.fetches[-1] == ("EURUSDm", "H1", True)
    assert (
        client.post(
            "/api/external/refresh", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_missing_credentials_and_unsupported_timeframes_are_explicit():
    external = FakeExternal(
        error=ProviderError("missing_api_key", "Set MASSIVE_API_KEY locally.")
    )
    client = TestClient(create_app(_historical(), external))
    status = client.get("/api/external/status").json()
    assert status["freshness"] == "UNAVAILABLE"
    assert "missing_api_key" in status["error"]
    assert client.get("/api/candles", params={"source": "massive"}).status_code == 409
    h4 = client.get("/api/candles", params={"source": "massive", "timeframe": "H4"})
    assert h4.status_code == 409 and "unsupported_timeframe" in h4.json()["detail"]
    assert client.get("/api/candles", params={"source": "other"}).status_code == 422


def test_public_errors_never_echo_untrusted_message_or_code():
    external = FakeExternal(error=ProviderError("missing_api_key", "private-token-123"))
    client = TestClient(create_app(_historical(), external))
    response = client.get("/api/external/status")
    assert "private-token-123" not in response.text
    external.error = ProviderError("private-token-123", "private-token-123")
    response = client.get("/api/external/status")
    assert "private-token-123" not in response.text
    assert "provider_error" in response.text


def test_mock_provider_fetch_to_verified_cache_to_analysis(tmp_path):
    import json

    from mt5_market_data.external_market import ExternalMarketService

    start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=5)
    rows = [
        {
            "t": int((start + timedelta(hours=i)).timestamp() * 1000),
            "o": 1.0,
            "h": 1.1,
            "l": 0.9,
            "c": 1.0,
            "v": 1,
        }
        for i in range(80)
    ]
    payload = json.dumps(
        {"ticker": "C:EURUSD", "status": "OK", "results": rows}
    ).encode()
    calls = []

    def transport(url, headers, timeout):
        calls.append((url, headers, timeout))
        return 200, payload, {}

    service = ExternalMarketService(
        cache_root=tmp_path,
        transport=transport,
        key_provider=lambda: "synthetic-private-key",
    )
    client = TestClient(create_app(_historical(), service))
    response = client.get(
        "/api/external/status", params={"symbol": "EURUSDm", "timeframe": "H1"}
    )
    assert response.status_code == 200
    status = response.json()
    assert status["snapshot_sha256"]
    assert status["latest_completed_candle"] is None
    assert status["latest_observed_candle"] > status["latest_nominally_closed_candle"]
    assert "synthetic-private-key" not in response.text
    params = {"source": "massive", "symbol": "EURUSDm", "timeframe": "H1"}
    candles = client.get("/api/candles", params=params).json()["candles"]
    assert len(candles) == 79  # newest has no provider finality evidence
    analysis = client.get("/api/analysis", params=params).json()["analysis"]
    assert analysis["timestamp"] == candles[-1]["timestamp"]
    assert analysis["overall_action"] == "WAIT"
    assert analysis["risk"]["contract_size_assumption"] is None
    assert len(calls) == 1  # chart/analysis only read the verified cache


def test_manual_refresh_cooldown_is_explicit_and_sanitized():
    external = FakeExternal(
        error=ProviderError("refresh_throttled", "private-token-123")
    )
    response = TestClient(create_app(_historical(), external)).post(
        "/api/external/refresh"
    )
    assert "refresh_throttled" in response.json()["error"]
    assert "private-token-123" not in response.text


def test_gap_status_is_bounded_and_unknown_when_no_snapshot():
    snapshot = _snapshot()
    snapshot["gaps"] = [
        {
            "classification": "unknown",
            "after_utc": "2025-01-01T00:00:00Z",
            "before_utc": "2025-01-01T02:00:00Z",
            "missing_intervals": 1,
        }
    ] * 101
    client = TestClient(create_app(_historical(), FakeExternal(snapshot)))
    response = client.get("/api/external/status", params={"timeframe": "H1"}).json()
    assert response["gap_count"] == 101
    assert len(response["gaps"]) == 100
    assert response["gaps_truncated"] is True
    assert all(gap["classification"] == "unknown" for gap in response["gaps"])
    missing = FakeExternal(error=ProviderError("missing_api_key", "missing"))
    assert (
        TestClient(create_app(_historical(), missing))
        .get("/api/external/status")
        .json()["gap_count"]
        is None
    )


def test_external_indicator_numerical_failure_returns_sanitized_validation_error(
    monkeypatch,
):
    from mt5_market_data import terminal_api

    def failing(*args, **kwargs):
        raise OverflowError("private numerical details")

    monkeypatch.setattr(terminal_api, "analyze_external", failing)
    external = FakeExternal(_snapshot())
    client = TestClient(create_app(_historical(), external))
    response = client.get(
        "/api/analysis", params={"source": "massive", "timeframe": "H1"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "External snapshot failed validation"
    assert "private numerical details" not in response.text
    assert external.fetches == []
