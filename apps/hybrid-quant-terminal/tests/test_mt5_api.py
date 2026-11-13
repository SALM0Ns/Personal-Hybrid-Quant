"""Synthetic tests for source isolation and MT5 feed-health gating."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from mt5_market_data import terminal_api
from mt5_market_data.terminal_api import create_app


class FakeBridge:
    def __init__(self, status="UNVERIFIED", gaps=0, empty=False):
        self.status = status
        self.gaps = gaps
        self.current_segment_count = 60
        self.revision_count = 0
        self.empty = empty
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1
        return {"processed": 0, "errors": []}

    def get(self, symbol, timeframe):
        rows = [
            {
                "timestamp": datetime(2024, 1, 1) + timedelta(hours=i),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "tick_volume": 1,
                "spread_points": 1,
                "real_volume": 0,
            }
            for i in range(60)
        ]
        return {
            "candles": [] if self.empty else rows,
            "snapshot_sha256": None if self.empty else "a" * 64,
            "health": {
                "status": self.status,
                "reasons": ["Synthetic status"],
                "unresolved_gap_count": self.gaps,
                "unresolved_revision_count": self.revision_count,
                "current_segment_count": self.current_segment_count,
                "history_count": 0 if self.empty else len(rows),
            },
        }


def _analysis(*args, **kwargs):
    return {
        "indicators": [],
        "swings": [],
        "zones": [],
        "patterns": [],
        "analysis": {
            "ema20": 1.0,
            "ema50": 1.0,
            "atr14": 1.0,
            "adx14": 1.0,
            "direction": "BUY",
            "entry": 1.0,
            "stop_loss": 0.9,
            "take_profit": 1.2,
            "risk_reward": 2.0,
            "trigger_reached": True,
            "overall_action": "WAIT",
            "execution_eligibility": "BLOCKED_UNVERIFIED",
            "risk": {},
            "blocking_reasons": [],
        },
    }


def test_mt5_status_polls_but_candle_reads_do_not():
    bridge = FakeBridge()
    client = TestClient(create_app(bridge_service=bridge))
    status = client.get("/api/mt5/status", params={"timeframe": "H1"}).json()
    assert status["status"] == "UNVERIFIED"
    assert status["continuity"] == "INCREMENTAL_ONLY_UNVERIFIED"
    assert bridge.poll_count == 1
    result = client.get(
        "/api/candles", params={"source": "mt5", "timeframe": "H1", "limit": 2}
    ).json()
    assert result["source"] == "mt5" and len(result["candles"]) == 2
    assert not result["candles"][-1]["timestamp"].endswith("Z")
    assert bridge.poll_count == 1


def test_no_cache_and_bad_symbol_fail_closed():
    client = TestClient(create_app(bridge_service=FakeBridge(empty=True)))
    assert client.get("/api/mt5/status").json()["snapshot_sha256"] is None
    assert client.get("/api/candles", params={"source": "mt5"}).status_code == 409
    assert client.get("/api/mt5/status", params={"symbol": "../bad"}).status_code == 422


def test_unhealthy_or_gapped_feed_never_exposes_a_current_setup(monkeypatch):
    monkeypatch.setattr(terminal_api, "analyze_bars", _analysis)
    bridge = FakeBridge(status="STALE")
    client = TestClient(create_app(bridge_service=bridge))
    params = {"source": "mt5", "timeframe": "H1"}
    stale = client.get("/api/analysis", params=params).json()["analysis"]
    assert stale["direction"] == "WAIT" and stale["entry"] is None
    assert stale["execution_eligibility"] == "BLOCKED_UNVERIFIED"
    bridge.status = "LIVE"
    live = client.get("/api/analysis", params=params).json()["analysis"]
    assert live["direction"] == "BUY" and live["overall_action"] == "WAIT"
    assert live["target_reference_scope"] == (
        "latest completed broker-clock candle close only; no fill inferred"
    )
    assert client.get("/api/health").json()["mode"] == "local_read_only"
    assert live["risk"]["minimum_lot"] is None
    bridge.gaps = 1
    bridge.current_segment_count = 20
    gapped = client.get("/api/analysis", params=params).json()["analysis"]
    assert gapped["direction"] == "WAIT" and gapped["stop_loss"] is None


def test_corrupt_runtime_does_not_disable_existing_modes(monkeypatch):
    def broken_bridge():
        raise ValueError("private path")

    monkeypatch.setattr(terminal_api, "BridgeService", broken_bridge)
    client = TestClient(create_app())
    assert client.get("/api/health").status_code == 200
    status = client.get("/api/mt5/status").json()
    assert status["status"] == "UNVERIFIED"
    assert "private path" not in str(status)
    assert client.get("/api/candles", params={"source": "mt5"}).status_code == 409


def test_synthetic_handoff_to_api_and_restart(tmp_path):
    from test_mt5_bridge import publish

    from mt5_market_data.mt5_bridge import BridgeService

    start = datetime(2024, 1, 1)
    rows = [
        f"{(start + timedelta(hours=i)).strftime('%Y.%m.%d %H:%M:%S')},1,2,0.5,1.5,3,1,0"
        for i in range(60)
    ]
    incoming, state = tmp_path / "incoming", tmp_path / "state"
    publish(incoming, rows, exported_at_server="2024.01.04 00:00:00")
    bridge = BridgeService(incoming, state)
    client = TestClient(create_app(bridge_service=bridge))
    params = {"symbol": "EURUSDm", "timeframe": "H1"}
    status = client.get("/api/mt5/status", params=params).json()
    assert status["history_count"] == 60 and status["status"] == "UNVERIFIED"
    params["source"] = "mt5"
    result = client.get("/api/candles", params=params).json()
    assert len(result["candles"]) == 60
    assert result["source"] == "mt5"
    assert (
        client.get("/api/analysis", params=params).json()["analysis"]["direction"]
        == "WAIT"
    )
    restarted = BridgeService(incoming, state)
    assert restarted.poll()["processed"] == 0
    assert (
        restarted.get("EURUSDm", "H1")["snapshot_sha256"] == result["snapshot_sha256"]
    )


def test_analytical_responses_carry_snapshot_bound_mt5_health(monkeypatch):
    monkeypatch.setattr(terminal_api, "analyze_bars", _analysis)
    bridge = FakeBridge(status="LIVE", gaps=2)
    client = TestClient(create_app(bridge_service=bridge))
    for endpoint in ("indicators", "patterns", "analysis"):
        result = client.get(
            f"/api/{endpoint}", params={"source": "mt5", "timeframe": "H1"}
        ).json()
        assert result["snapshot_sha256"] == "a" * 64
        assert result["feed_health"]["unresolved_gap_count"] == 2
        assert result["feed_health"]["unresolved_revision_count"] == 0
        assert result["continuity"] == "INCREMENTAL_ONLY_UNVERIFIED"
        if endpoint == "analysis":
            provenance = result["setup_reference_provenance"]
            assert provenance["entry_basis"] == "confirmed_pattern_neckline"
            assert provenance["stop_basis"] == "pattern_anchors_and_latest_snapshot_atr"
            assert provenance["historical_execution_record"] is False
            assert result["analysis_observed_at_utc"].endswith("+00:00")


def test_contradictory_or_missing_live_health_cannot_expose_setup(monkeypatch):
    monkeypatch.setattr(terminal_api, "analyze_bars", _analysis)
    bridge = FakeBridge(status="LIVE")
    client = TestClient(create_app(bridge_service=bridge))
    params = {"source": "mt5", "timeframe": "H1"}
    for field, value in (
        ("revision_count", 1),
        ("revision_count", None),
        ("revision_count", False),
        ("gaps", None),
        ("gaps", -1),
        ("current_segment_count", 61),
        ("current_segment_count", True),
    ):
        setattr(bridge, field, value)
        analysis = client.get("/api/analysis", params=params).json()["analysis"]
        assert analysis["direction"] == "WAIT"
        assert analysis["entry"] is None
        assert analysis["overall_action"] == "WAIT"
        setattr(bridge, field, 0 if field in ("revision_count", "gaps") else 60)


def test_indicator_numerical_errors_are_sanitized_and_block_mt5_analysis(monkeypatch):
    bridge = FakeBridge(status="LIVE")
    client = TestClient(create_app(bridge_service=bridge))
    for error in (
        ValueError("private diagnostic"),
        OverflowError("private diagnostic"),
    ):

        def failing(*args, _error=error, **kwargs):
            raise _error

        monkeypatch.setattr(terminal_api, "analyze_bars", failing)
        result = client.get("/api/analysis", params={"source": "mt5"})
        assert result.status_code == 409
        assert result.json()["detail"] == "MT5 runtime cache failed validation."
        assert "private diagnostic" not in result.text
        risk = client.get("/api/broker-risk")
        assert risk.status_code == 200
        assert risk.json()["verification_status"] == "UNVERIFIED"
