"""Synthetic engine-to-API level checks: no real market data or broker access."""

import hashlib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from mt5_market_data.terminal_analysis import AnalysisConfig, analyze_bars
from mt5_market_data.terminal_api import create_app

TOP = [101, 103, 107, 103, 100, 96, 94, 96, 100, 104, 107, 104, 99, 93, 92]
BOTTOM = [99, 97, 93, 97, 100, 104, 106, 104, 100, 96, 93, 96, 101, 107, 108]
STEPS = {
    "M15": timedelta(minutes=15),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
}


class SyntheticBridge:
    def __init__(self, prices):
        self.prices = prices
        self.status = "LIVE"

    def rows(self, timeframe):
        start = datetime(2024, 1, 1)
        return [
            {
                "timestamp": start + i * STEPS[timeframe],
                "open": float(value),
                "high": float(value + 1),
                "low": float(value - 1),
                "close": float(value),
                "tick_volume": 3,
                "spread_points": 1,
                "real_volume": 0,
            }
            for i, value in enumerate(self.prices)
        ]

    def get(self, symbol, timeframe):
        rows = self.rows(timeframe)
        identity = hashlib.sha256(
            f"synthetic:{symbol}:{timeframe}".encode()
        ).hexdigest()
        return {
            "candles": rows,
            "snapshot_sha256": identity,
            "health": {
                "status": self.status,
                "unresolved_gap_count": 0,
                "unresolved_revision_count": 0,
                "history_count": len(rows),
                "current_segment_count": len(rows),
            },
        }


@pytest.mark.parametrize("symbol", ["EURUSDm", "XAUUSDm"])
@pytest.mark.parametrize("timeframe", ["M15", "H1", "H4"])
@pytest.mark.parametrize("prices,direction", [(TOP, "SELL"), (BOTTOM, "BUY")])
def test_engine_values_reach_matching_api_snapshot(
    symbol, timeframe, prices, direction
):
    bridge = SyntheticBridge([100] * 55 + prices)
    client = TestClient(create_app(bridge_service=bridge))
    config = AnalysisConfig(left=1, right=1)
    expected = analyze_bars(bridge.rows(timeframe), timeframe, config=config)[
        "analysis"
    ]
    assert expected["direction"] == direction
    params = {
        "source": "mt5",
        "symbol": symbol,
        "timeframe": timeframe,
        "left": 1,
        "right": 1,
    }
    responses = [
        client.get(f"/api/{path}", params=params)
        for path in ("candles", "indicators", "patterns", "analysis")
    ]
    assert all(response.status_code == 200 for response in responses)
    bodies = [response.json() for response in responses]
    assert len({body["snapshot_sha256"] for body in bodies}) == 1
    assert all(
        (body["source"], body["symbol"], body["timeframe"])
        == ("mt5", symbol, timeframe)
        for body in bodies
    )
    result = bodies[-1]["analysis"]
    for name in (
        "direction",
        "entry",
        "stop_loss",
        "take_profit",
        "risk_reward",
        "timestamp",
        "available_at_timestamp",
    ):
        assert result[name] == expected[name]
    assert result["overall_action"] == "WAIT"
    assert result["execution_eligibility"] == "BLOCKED_UNVERIFIED"
    assert result["timestamp"] == bodies[0]["candles"][-1]["timestamp"]
    bridge.status = "UNVERIFIED"
    blocked = client.get("/api/analysis", params=params).json()["analysis"]
    assert blocked["direction"] == "WAIT"
    assert all(blocked[name] is None for name in ("entry", "stop_loss", "take_profit"))
