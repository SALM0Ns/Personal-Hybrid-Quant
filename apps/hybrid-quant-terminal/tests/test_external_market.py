"""Deterministic external FX adapter tests; no provider access."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mt5_market_data.external_market import (
    ExternalMarketService,
    ProviderError,
    parse_aggregates,
)

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
CUTOFF = NOW.replace(hour=0)
START = datetime(2026, 11, 3, 12, tzinfo=UTC)


def response(*, ticker="C:EURUSD", hours=(0, 1, 3), status="OK"):
    values = []
    for h in hours:
        values.append(
            {
                "t": int((START + timedelta(hours=h)).timestamp() * 1000),
                "o": 1.0,
                "h": 1.2,
                "l": 0.9,
                "c": 1.1,
                "v": 2,
            }
        )
    return json.dumps({"ticker": ticker, "status": status, "results": values}).encode()


def service(tmp_path: Path, transport, *, key="unit-test-key", clock=None, sleeps=None):
    tick = clock if clock is not None else [100.0]
    return ExternalMarketService(
        cache_root=tmp_path / "external",
        transport=transport,
        monotonic=lambda: tick[0],
        sleeper=(sleeps.append if sleeps is not None else lambda _: None),
        key_provider=lambda: key,
    )


def test_parsing_preserves_utc_and_excludes_newest_unverified():
    result = parse_aggregates(response(), "C:EURUSD", "H1", cutoff=CUTOFF)
    assert [c["timestamp_utc"] for c in result["candles"]] == [
        "2026-11-03T12:00:00Z",
        "2026-11-03T13:00:00Z",
    ]
    assert result["latest_observed_candle"]["timestamp_utc"] == "2026-11-03T15:00:00Z"
    assert (
        result["latest_observed_candle"]["completion"]
        == "THEORETICAL_CLOSED_UNVERIFIED"
    )
    assert result["excluded_unconfirmed_count"] == 1
    assert result["candles"][0]["source_timestamp_ms"] == int(START.timestamp() * 1000)


def test_gap_classification_never_claims_outage():
    result = parse_aggregates(
        response(hours=(0, 2, 3)), "C:EURUSD", "H1", cutoff=CUTOFF
    )
    assert result["gaps"][0]["missing_intervals"] == 1
    assert result["gaps"][0]["classification"] == "unknown"


def test_latest_current_day_is_excluded_from_analysis():
    payload = json.loads(response(hours=(0, 1)))
    payload["results"].append(
        {"t": int(CUTOFF.timestamp() * 1000), "o": 1, "h": 2, "l": 0.5, "c": 1}
    )
    result = parse_aggregates(
        json.dumps(payload).encode(), "C:EURUSD", "H1", cutoff=CUTOFF
    )
    assert len(result["candles"]) == 1
    assert result["excluded_unconfirmed_count"] == 2


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda x: x.update(ticker="C:XAUUSD"), "malformed_data"),
        (lambda x: x.update(status="ERROR"), "malformed_data"),
        (lambda x: x.update(results=[]), "empty_response"),
        (
            lambda x: x.update(next_url="https://other.example/page"),
            "pagination_required",
        ),
        (lambda x: x["results"].append(dict(x["results"][0])), "duplicate_timestamp"),
        (lambda x: x["results"][0].update(t=1), "malformed_timestamp"),
        (lambda x: x["results"][0].update(h=0.1), "invalid_ohlc"),
        (lambda x: x["results"][0].update(c=float("nan")), "malformed_data"),
    ],
)
def test_bad_responses_rejected(mutate, expected):
    value = json.loads(response())
    mutate(value)
    with pytest.raises(ProviderError) as exc:
        parse_aggregates(json.dumps(value).encode(), "C:EURUSD", "H1", cutoff=CUTOFF)
    assert exc.value.code == expected


def test_key_in_header_only_and_source_isolated(tmp_path):
    calls = []

    def transport(url, headers, timeout):
        calls.append((url, headers, timeout))
        return 200, response(), {}

    s = service(tmp_path, transport)
    result = s.get("EURUSDm", "H1", now=NOW)
    assert result["provider"] == "massive"
    assert result["source_timezone"] == "UTC"
    assert result["latest_completed_candle_utc"] is None
    assert result["latest_nominally_closed_candle_utc"] == "2026-11-03T13:00:00Z"
    assert result["execution_eligibility"] == "BLOCKED_UNVERIFIED"
    assert calls[0][1]["Authorization"] == "Bearer unit-test-key"
    assert "unit-test-key" not in calls[0][0]
    for f in (tmp_path / "external").rglob("*.json"):
        assert b"unit-test-key" not in f.read_bytes()
    assert (
        s.read_cached("EURUSDm", "H1", now=NOW)["snapshot_sha256"]
        == result["snapshot_sha256"]
    )
    assert s.read_cached("XAUUSDm", "H1", now=NOW) is None


def test_no_key_and_unsupported_are_explicit(tmp_path):
    s = service(tmp_path, lambda *_: pytest.fail("network called"), key=None)
    with pytest.raises(ProviderError, match="MASSIVE_API_KEY") as exc:
        s.get("EURUSDm", "M15", now=NOW)
    assert exc.value.code == "missing_api_key"
    with pytest.raises(ProviderError) as exc:
        s.get("XAUUSDm", "H4", now=NOW)
    assert exc.value.code == "unsupported_timeframe"
    with pytest.raises(ProviderError) as exc:
        s.get("EURUSDm", "D1", now=NOW)
    assert exc.value.code == "unsupported_timeframe"


def test_cache_24h_auto_and_manual_throttle(tmp_path):
    calls = []

    def transport(*args):
        calls.append(args)
        return 200, response(), {}

    clock = [100.0]
    s = service(tmp_path, transport, clock=clock)
    a = s.get("EURUSDm", "H1", now=NOW)
    clock[0] += 900
    assert (
        s.get("EURUSDm", "H1", now=NOW + timedelta(minutes=15))["snapshot_sha256"]
        == a["snapshot_sha256"]
    )
    assert len(calls) == 1
    b = s.get("EURUSDm", "H1", force=True, now=NOW + timedelta(minutes=15))
    assert len(calls) == 2 and b["snapshot_sha256"] != a["snapshot_sha256"]
    assert (
        s.get("EURUSDm", "H1", force=True, now=NOW + timedelta(minutes=16))["error"][
            "code"
        ]
        == "refresh_throttled"
    )
    assert len(calls) == 2


def test_stale_fallback_after_failure_and_corruption_rejected(tmp_path):
    calls = []

    def transport(*args):
        calls.append(args)
        return (200, response(), {}) if len(calls) == 1 else (503, b"", {})

    clock = [100.0]
    s = service(tmp_path, transport, clock=clock)
    a = s.get("EURUSDm", "H1", now=NOW)
    clock[0] += 901
    b = s.get("EURUSDm", "H1", force=True, now=NOW + timedelta(minutes=16))
    assert b["snapshot_sha256"] == a["snapshot_sha256"]
    assert (
        b["freshness"] == "STALE_AFTER_ERROR" and b["error"]["code"] == "provider_error"
    )
    assert len(calls) == 4
    s.get("EURUSDm", "H1", force=True, now=NOW + timedelta(minutes=17))
    assert len(calls) == 4
    path = tmp_path / "external" / "normalized" / (a["snapshot_sha256"] + ".json")
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ProviderError) as exc:
        s.read_cached("EURUSDm", "H1", now=NOW)
    assert exc.value.code == "cache_corrupt"


def test_retry_and_global_rate_cap(tmp_path):
    responses = iter([500, 500, 200, 200, 200])
    calls = []

    def transport(url, *_):
        calls.append(url)
        status = next(responses)
        return (
            status,
            response(ticker="C:XAUUSD" if "XAUUSD" in url else "C:EURUSD"),
            {},
        )

    s = service(tmp_path, transport)
    assert s.get("EURUSDm", "H1", now=NOW)["candles"]
    assert s.get("EURUSDm", "M15", now=NOW)["candles"]
    assert s.get("XAUUSDm", "H1", now=NOW)["candles"]
    with pytest.raises(ProviderError) as exc:
        s.get("XAUUSDm", "M15", now=NOW)
    assert exc.value.code == "rate_limited"
    assert len(calls) == 5


def test_429_never_retries_and_throttles_other_symbols(tmp_path):
    calls = []

    def transport(*args):
        calls.append(args)
        return 429, b"", {}

    s = service(tmp_path, transport)
    with pytest.raises(ProviderError) as exc:
        s.get("EURUSDm", "H1", now=NOW)
    assert exc.value.code == "rate_limited"
    with pytest.raises(ProviderError) as exc:
        s.get("XAUUSDm", "H1", now=NOW)
    assert exc.value.code == "rate_limited" and len(calls) == 1


def test_read_cached_never_requests_or_needs_credentials(tmp_path):
    calls = []

    def transport(*args):
        calls.append(args)
        return 200, response(), {}

    s = service(tmp_path, transport)
    s.get("EURUSDm", "H1", now=NOW)
    s.key_provider = lambda: None
    assert s.read_cached("EURUSDm", "H1", now=NOW)["candles"]
    assert len(calls) == 1
    assert s.get("EURUSDm", "H1", now=NOW)["freshness"] == "STALE_AFTER_ERROR"
    assert len(calls) == 1


def test_single_observation_is_never_offered_for_analysis(tmp_path):
    s = service(tmp_path, lambda *_: (200, response(hours=(0,)), {}))
    snap = s.get("EURUSDm", "H1", now=NOW)
    assert snap["candles"] == []
    assert snap["latest_observed_candle"] is not None
    assert snap["latest_completed_candle_utc"] is None
    assert snap["latest_nominally_closed_candle_utc"] is None


def test_failed_automatic_refresh_has_daily_backoff(tmp_path):
    calls = []

    def transport(*args):
        calls.append(args)
        return 403, b"", {}

    clock = [100.0]
    s = service(tmp_path, transport, clock=clock)
    with pytest.raises(ProviderError):
        s.get("EURUSDm", "H1", now=NOW)
    clock[0] += 3600
    with pytest.raises(ProviderError):
        s.get("EURUSDm", "H1", now=NOW + timedelta(hours=1))
    assert len(calls) == 1
    with pytest.raises(ProviderError):
        s.get("EURUSDm", "H1", force=True, now=NOW + timedelta(hours=1))
    assert len(calls) == 2


def test_retry_after_is_respected_across_all_markets(tmp_path):
    calls = []

    def transport(*args):
        calls.append(args)
        return 429, b"", {"Retry-After": "300"}

    clock = [100.0]
    s = service(tmp_path, transport, clock=clock)
    with pytest.raises(ProviderError):
        s.get("EURUSDm", "H1", now=NOW)
    clock[0] += 120
    with pytest.raises(ProviderError):
        s.get("XAUUSDm", "M15", now=NOW + timedelta(minutes=2))
    assert len(calls) == 1


def test_http_redirect_is_rejected():
    from mt5_market_data.external_market import _NoRedirect

    assert (
        _NoRedirect().redirect_request(
            None, None, 302, "Found", {}, "https://other.example"
        )
        is None
    )


def test_outside_requested_range_rejected():
    with pytest.raises(ProviderError) as exc:
        parse_aggregates(
            response(hours=(0, 1, 2)),
            "C:EURUSD",
            "H1",
            cutoff=CUTOFF,
            start=START + timedelta(hours=1),
        )
    assert exc.value.code == "unexpected_coverage"


def test_gap_includes_latest_unverified_observation_boundary():
    result = parse_aggregates(
        response(hours=(0, 1, 4)), "C:EURUSD", "H1", cutoff=CUTOFF
    )
    assert result["gaps"][-1]["after_utc"] == "2026-11-03T13:00:00Z"
    assert result["gaps"][-1]["before_utc"] == "2026-11-03T16:00:00Z"
    assert result["gaps"][-1]["missing_intervals"] == 2
    assert result["gaps"][-1]["classification"] == "unknown"


def test_base_aggregate_limit_saturation_fails_closed():
    payload = json.loads(response())
    payload["queryCount"] = 50_000
    with pytest.raises(ProviderError) as exc:
        parse_aggregates(json.dumps(payload).encode(), "C:EURUSD", "H1", cutoff=CUTOFF)
    assert exc.value.code == "pagination_required"
