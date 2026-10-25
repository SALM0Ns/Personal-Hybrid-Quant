"""Loopback-only application integration with injected synthetic market data."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest
from test_app_analysis import HOUR, NOW, _window

from quant.app import analysis, server
from quant.app.analysis import MarketDataError


@pytest.fixture
def local_server(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "utc_now", lambda: NOW)
    monkeypatch.setattr(server, "fetch_recent_market", _window)
    with ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(tmp_path)) as http:
        thread = Thread(
            target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            yield http, tmp_path
        finally:
            http.shutdown()
            thread.join(timeout=5)


def _request(
    local_server, *, route="/api/analyze", method="POST", body=b"{}", headers=None
):
    http, _ = local_server
    connection = HTTPConnection("127.0.0.1", http.server_port, timeout=5)
    try:
        connection.request(
            method,
            route,
            body=body,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read()), dict(response.getheaders())
    finally:
        connection.close()


@pytest.mark.parametrize(
    "growth,expected", [(1.001, "BUY"), (0.999, "SELL"), (1.0, "HOLD")]
)
def test_post_analysis_returns_informational_non_actionable_assessment(
    local_server, monkeypatch, growth, expected
):
    monkeypatch.setattr(server, "fetch_recent_market", lambda: _window(growth=growth))
    status, payload, headers = _request(local_server)
    assert status == 200
    assert payload["decision"] == expected
    assert payload["directional_assessment"] == expected
    assert payload["actionable"] is False
    assert payload["feature_decision_eligible"] is False
    assert payload["risk"]["status"] == "DISABLED"
    assert len(payload["candles"]) == 200
    assert payload["explanations"]
    assert payload["atr_14"] > 0
    if expected == "HOLD":
        assert payload["reference_levels"] is None
        assert payload["entry_reference"] is None
    else:
        levels = payload["reference_levels"]
        assert levels["entry"] == payload["candles"][-1]["close"]
        assert levels["risk_reward"] == "1:2"
        assert "not verified Exness" in levels["label"]
    assert headers["Cache-Control"] == "no-store"
    assert "confidence" not in payload and "position_size" not in payload
    assert list(local_server[1].iterdir()) == []


def test_market_route_loads_candles_without_running_directional_analysis(
    local_server, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Loading market data unexpectedly ran analysis")

    monkeypatch.setattr(server, "build_analysis", forbidden)
    status, payload, _ = _request(local_server, route="/api/market")
    assert status == 200
    assert len(payload["candles"]) == 200
    assert "strategy" not in payload
    assert "explanations" not in payload
    assert "indicators" not in payload
    assert payload["decision"] == "HOLD"
    assert payload["actionable"] is False


@pytest.mark.parametrize(
    "body,headers",
    [
        (b"{", {}),
        (b'{"unexpected":true}', {}),
        (b"[]", {}),
        (b"", {}),
        (b"{}", {"Content-Type": "text/plain"}),
        (b" " * 1025, {}),
    ],
)
def test_invalid_requests_fail_before_market_access(
    local_server, monkeypatch, body, headers
):
    def forbidden(*args, **kwargs):
        pytest.fail("Malformed request reached market retrieval")

    monkeypatch.setattr(server, "fetch_recent_market", forbidden)
    status, payload, _ = _request(local_server, body=body, headers=headers)
    assert status == 400
    assert payload["decision"] == "HOLD"
    assert payload["actionable"] is False
    assert payload["candles"] == []


def test_foreign_browser_origin_is_rejected_before_market_access(
    local_server, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Foreign-origin request reached market retrieval")

    monkeypatch.setattr(server, "fetch_recent_market", forbidden)
    status, payload, _ = _request(
        local_server, headers={"Origin": "https://external.invalid"}
    )
    assert status == 403
    assert payload["decision"] == "HOLD"


def test_same_loopback_browser_origin_is_accepted(local_server):
    status, payload, _ = _request(
        local_server,
        headers={"Origin": f"http://127.0.0.1:{local_server[0].server_port}"},
    )
    assert status == 200
    assert payload["actionable"] is False


@pytest.mark.parametrize("failure", ["provider", "stale", "unexpected"])
def test_failed_refresh_clears_previous_direction_and_candles(
    local_server, monkeypatch, failure
):
    status, first, _ = _request(local_server)
    assert status == 200 and first["decision"] == "BUY"
    if failure == "stale":
        monkeypatch.setattr(
            server, "fetch_recent_market", lambda: _window(observed_at=NOW - HOUR)
        )
    else:

        def unavailable():
            if failure == "provider":
                raise MarketDataError("Synthetic provider unavailable")
            raise RuntimeError("Internal detail must not escape")

        monkeypatch.setattr(server, "fetch_recent_market", unavailable)
    status, rejected, _ = _request(local_server)
    assert status == (500 if failure == "unexpected" else 422)
    assert rejected["decision"] == "HOLD"
    assert rejected["directional_assessment"] == "HOLD"
    assert rejected["actionable"] is False
    assert rejected["candles"] == []
    assert "indicators" not in rejected
    assert rejected["reference_levels"] is None
    assert rejected["entry_reference"] is None
    assert "Internal detail" not in str(rejected)


def test_failed_atr_rejects_assessment_and_clears_reference_levels(
    local_server, monkeypatch
):
    status, first, _ = _request(local_server)
    assert status == 200 and first["reference_levels"] is not None

    def invalid_atr(*args, **kwargs):
        raise MarketDataError("Synthetic missing ATR history")

    monkeypatch.setattr(analysis, "calculate_atr", invalid_atr)
    status, rejected, _ = _request(local_server)
    assert status == 422
    assert rejected["decision"] == "HOLD"
    assert rejected["reference_levels"] is None
    assert rejected["entry_reference"] is None
    assert rejected["atr_14"] is None


@pytest.mark.parametrize(
    "method,route",
    [("GET", "/api/analyze"), ("POST", "/api/order"), ("POST", "/api/trade")],
)
def test_no_get_analysis_or_order_execution_routes(
    local_server, monkeypatch, method, route
):
    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported route reached market retrieval")

    monkeypatch.setattr(server, "fetch_recent_market", forbidden)
    status, _, _ = _request(local_server, method=method, route=route)
    assert status == 404
