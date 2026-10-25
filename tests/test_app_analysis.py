"""Offline checks for fresh reference analysis; no broker or market API calls."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from quant.app import analysis

NOW = datetime(2026, 10, 25, 10, 30, tzinfo=UTC)
HOUR = timedelta(hours=1)


def _rows(*, observed_at=NOW, count=200, growth=1.001):
    boundary = observed_at.replace(minute=0, second=0, microsecond=0)
    return [
        [
            int((boundary - (count - index) * HOUR).timestamp() * 1000),
            price,
            price * 1.01,
            price * 0.99,
            price,
            10.0 + index,
        ]
        for index in range(count)
        for price in (100.0 * growth**index,)
    ]


def _window(*, growth=1.001, observed_at=NOW):
    return analysis.MarketWindow(
        observations=analysis.validate_market_rows(
            _rows(growth=growth, observed_at=observed_at), observed_at=observed_at
        ),
        observed_at=observed_at,
    )


def _indicators(**changes):
    values = {
        "log_return_1h": 0.002,
        "volatility_24h": 0.01,
        "volatility_168h": 0.02,
        "momentum_24h": 0.03,
        "momentum_168h": 0.05,
        "volume_change_1h": 0.1,
        "normalized_range_1h": 0.02,
    }
    values.update(changes)
    return values


class Exchange:
    def __init__(self, *, rows=None, server_time=NOW):
        self.rows = _rows() if rows is None else rows
        self.server_time = server_time
        self.calls = []

    def fetch_time(self):
        return int(self.server_time.timestamp() * 1000)

    def fetch_ohlcv(self, symbol, timeframe, *, since, limit):
        self.calls.append((symbol, timeframe, since, limit))
        return [row for row in self.rows if row[0] >= since][:limit]


def test_recent_rows_are_sorted_and_exactly_complete_without_filling():
    raw = _rows()
    validated = analysis.validate_market_rows(list(reversed(raw)), observed_at=NOW)
    assert len(validated) == 200
    assert validated[-1]["timestamp"] == datetime(2026, 10, 25, 9, tzinfo=UTC)
    assert tuple(row["timestamp"] for row in validated) == tuple(
        sorted(row["timestamp"] for row in validated)
    )
    assert all(
        right["timestamp"] - left["timestamp"] == HOUR
        for left, right in zip(validated, validated[1:])
    )
    assert raw == _rows()


@pytest.mark.parametrize("count", [169, 200, 500])
def test_bounded_windows_support_feature_warmup(count):
    validated = analysis.validate_market_rows(
        _rows(count=count), observed_at=NOW, window=count
    )
    assert len(validated) == count


@pytest.mark.parametrize("count", [0, 168, 501, True])
def test_invalid_window_size_is_rejected(count):
    with pytest.raises((ValueError, TypeError)):
        analysis.validate_market_rows(_rows(), observed_at=NOW, window=count)


@pytest.mark.parametrize(
    "defect", ["empty", "gap", "duplicate", "incomplete", "stale", "extra"]
)
def test_incomplete_stale_or_noncontiguous_windows_fail_closed(defect):
    rows = _rows()
    if defect == "empty":
        rows = []
    elif defect == "gap":
        del rows[100]
    elif defect == "duplicate":
        rows[100] = list(rows[99])
    elif defect == "incomplete":
        rows[-1][0] += 3_600_000
    elif defect == "stale":
        for row in rows:
            row[0] -= 3_600_000
    else:
        rows = [list(rows[0]), *rows]
        rows[0][0] -= 3_600_000
    with pytest.raises(analysis.MarketDataError):
        analysis.validate_market_rows(rows, observed_at=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        (0, True),
        (0, 100.5),
        (1, True),
        (1, 0.0),
        (2, 1.0),
        (3, 100000.0),
        (4, None),
        (4, math.nan),
        (4, math.inf),
        (5, -1.0),
        (5, False),
    ],
)
def test_invalid_raw_ohlcv_is_not_silently_normalized(field, value):
    rows = _rows()
    rows[-1][field] = value
    with pytest.raises(analysis.MarketDataError):
        analysis.validate_market_rows(rows, observed_at=NOW)


@pytest.mark.parametrize("observed_at", [NOW.replace(tzinfo=None), "now", None])
def test_observation_clock_must_be_aware_utc(observed_at):
    with pytest.raises((ValueError, TypeError)):
        analysis.validate_market_rows(_rows(), observed_at=observed_at)


def test_provider_fetch_is_public_bounded_and_observed_after_fetch():
    exchange = Exchange()
    window = analysis.fetch_recent_market(exchange=exchange, clock=lambda: NOW)
    assert len(window.observations) == 200
    assert exchange.calls
    assert all(call[0:2] == ("BTC/USDT", "1h") for call in exchange.calls)
    assert sum(call[3] for call in exchange.calls) == 200
    assert not hasattr(exchange, "create_order")


def test_hour_rollover_during_fetch_does_not_accept_now_stale_window():
    before = NOW.replace(minute=59, second=59)
    after = before + timedelta(seconds=2)
    exchange = Exchange(rows=_rows(observed_at=before), server_time=before)
    with pytest.raises(analysis.MarketDataError):
        analysis.fetch_recent_market(
            exchange=exchange, clock=lambda: after if exchange.calls else before
        )


@pytest.mark.parametrize(
    "offset", [timedelta(seconds=61), -timedelta(seconds=61), HOUR]
)
def test_server_and_local_clock_disagreement_is_rejected(offset):
    with pytest.raises(analysis.MarketDataError):
        analysis.fetch_recent_market(
            exchange=Exchange(server_time=NOW + offset), clock=lambda: NOW
        )


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "BUY"),
        (
            {"momentum_24h": -0.03, "momentum_168h": -0.05, "log_return_1h": -0.002},
            "SELL",
        ),
        ({"momentum_24h": 0.005}, "HOLD"),
        (
            {"momentum_24h": -0.005, "momentum_168h": -0.05, "log_return_1h": -0.002},
            "HOLD",
        ),
        ({"momentum_168h": 0.0}, "HOLD"),
        ({"log_return_1h": 0.0}, "HOLD"),
        ({"momentum_24h": -0.03}, "HOLD"),
        ({"volatility_24h": 0.0}, "HOLD"),
    ],
)
def test_directional_baseline_has_explicit_deterministic_thresholds(changes, expected):
    indicators = _indicators(**changes)
    first = analysis.assess_direction(indicators)
    assert first == analysis.assess_direction(dict(indicators))
    decision, reasons = first
    assert decision == expected
    assert reasons and all(isinstance(reason, str) for reason in reasons)


@pytest.mark.parametrize("value", [None, math.nan, math.inf, True])
def test_invalid_indicator_cannot_become_a_signal(value):
    with pytest.raises(analysis.MarketDataError):
        analysis.assess_direction(_indicators(momentum_24h=value))


@pytest.mark.parametrize(
    "field", ["volatility_24h", "volatility_168h", "normalized_range_1h"]
)
def test_negative_volatility_or_range_is_rejected(field):
    with pytest.raises(analysis.MarketDataError):
        analysis.assess_direction(_indicators(**{field: -0.01}))


def test_missing_feature_schema_is_rejected():
    indicators = _indicators()
    del indicators["volume_change_1h"]
    with pytest.raises(analysis.MarketDataError):
        analysis.assess_direction(indicators)


def test_zero_previous_volume_blocks_missing_feature_instead_of_imputing():
    rows = _rows()
    rows[-2][5] = 0.0
    window = analysis.MarketWindow(
        analysis.validate_market_rows(rows, observed_at=NOW), NOW
    )
    with pytest.raises(analysis.MarketDataError):
        analysis.build_analysis(window)


@pytest.mark.parametrize(
    "growth,expected", [(1.001, "BUY"), (0.999, "SELL"), (1.0, "HOLD")]
)
def test_analysis_has_no_executable_trade_or_fabricated_confidence(growth, expected):
    window = _window(growth=growth)
    payload = analysis.build_analysis(window)
    assert payload["decision"] == expected
    assert payload["actionable"] is False
    assert payload["feature_decision_eligible"] is False
    assert "confidence" not in payload
    assert "expected_return" not in payload
    assert "position_size" not in payload
    assert analysis.build_analysis(window) == payload


def test_failure_payload_clears_actionability_and_previous_direction():
    payload = analysis.failure_payload("Provider unavailable")
    assert payload["decision"] == "HOLD"
    assert payload["actionable"] is False
    assert "Provider unavailable" in str(payload)


def test_offline_analysis_never_reads_historical_parquet_or_calls_exchange(monkeypatch):
    from pathlib import Path

    import polars as pl

    window = _window()

    def forbidden(*args, **kwargs):
        pytest.fail("in-memory analysis attempted historical I/O or market fetch")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(pl, "read_parquet", forbidden)
    monkeypatch.setattr(analysis, "fetch_recent_market", forbidden)
    payload = analysis.build_analysis(window)
    assert payload["actionable"] is False
