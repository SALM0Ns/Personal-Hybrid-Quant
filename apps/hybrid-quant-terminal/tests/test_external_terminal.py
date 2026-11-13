"""Synthetic source-isolation checks; no network or real market data."""

from datetime import UTC, datetime, timedelta

import pytest

from mt5_market_data.external_terminal import analyze_external
from mt5_market_data.terminal_analysis import AnalysisConfig


def _bars(count):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        {
            "timestamp_utc": (start + timedelta(hours=i))
            .isoformat()
            .replace("+00:00", "Z"),
            "open": 1.0 + i / 1000,
            "high": 1.1 + i / 1000,
            "low": 0.9 + i / 1000,
            "close": 1.0 + i / 1000,
        }
        for i in range(count)
    ]


def test_external_analysis_remains_utc_and_drops_broker_contract_assumptions():
    result = analyze_external(_bars(60), "H1", AnalysisConfig(contract_size=100_000))
    assert result["indicators"][-1]["timestamp"].endswith("Z")
    assert result["indicators"][-1]["available_at_timestamp"].endswith("Z")
    assert result["analysis"]["risk"]["contract_size_assumption"] is None
    assert result["analysis"]["risk"]["minimum_lot"] is None
    assert result["analysis"]["execution_eligibility"] == "BLOCKED_UNVERIFIED"
    assert result["analysis"]["overall_action"] == "WAIT"
    assert all("broker-clock" not in r for r in result["analysis"]["blocking_reasons"])


def test_external_analysis_rejects_unzoned_or_offset_timestamp():
    bars = _bars(1)
    for timestamp in ("2024-01-01T00:00:00", "2024-01-01T00:00:00+01:00"):
        with pytest.raises(ValueError, match="UTC"):
            analyze_external(
                [{**bars[0], "timestamp_utc": timestamp}], "H1", AnalysisConfig()
            )


def test_future_bars_do_not_change_previous_indicators():
    bars = _bars(70)
    first = analyze_external(bars[:60], "H1", AnalysisConfig())
    full = analyze_external(bars, "H1", AnalysisConfig())
    assert first["indicators"] == full["indicators"][:60]


def test_short_history_explicitly_reports_indicator_warmup():
    result = analyze_external(_bars(10), "H1", AnalysisConfig())
    assert result["analysis"]["pattern_id"] is None
    assert any(
        "warming up" in reason for reason in result["analysis"]["blocking_reasons"]
    )
    assert result["analysis"]["overall_action"] == "WAIT"
