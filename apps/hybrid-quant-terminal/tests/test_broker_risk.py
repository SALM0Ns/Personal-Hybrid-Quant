"""Offline tests use invented inputs and never claim actual broker specifications."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from mt5_market_data.broker_risk import SpecificationSnapshot, calculate_fixture_risk
from mt5_market_data.terminal_api import create_app

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def fixture(symbol="EURUSDm"):
    return SpecificationSnapshot(
        instrument=symbol,
        account_currency="USD",
        profit_currency="USD",
        tick_size="0.0001",
        tick_value_loss="10",
        tick_value_profit="12",
        volume_min="0.01",
        volume_max="10",
        volume_step="0.01",
        observed_at_utc=NOW,
        contract_size="100000",
    )


def calculate(spec=None, **kwargs):
    args = {
        "instrument": "EURUSDm",
        "direction": "BUY",
        "entry": "1.10",
        "stop_loss": "1.09",
        "take_profit": "1.12",
        "risk_budget": "10",
        "as_of": NOW,
        "feed_status": "LIVE",
        "setup_status": "CURRENT",
    }
    args.update(kwargs)
    return calculate_fixture_risk(spec or fixture(), **args)


def test_asymmetric_ticks_and_downward_rounding():
    result = calculate()
    assert result.theoretical_volume == Decimal("0.01")
    assert result.normalized_volume == Decimal("0.01")
    assert result.expected_gross_loss == Decimal(10)
    assert result.expected_gross_profit == Decimal(24)
    assert result.gross_risk_reward == Decimal("2.4")
    assert result.status == "SYNTHETIC_ONLY"
    assert calculate(risk_budget="19").normalized_volume == Decimal("0.01")


def test_xau_is_invented_fixture_with_nonstandard_step():
    gold = replace(
        fixture("XAUUSDm"),
        tick_size="0.1",
        tick_value_loss="1",
        tick_value_profit="1",
        volume_min="0.03",
        volume_step="0.03",
        volume_max="9.99",
        contract_size="100",
    )
    result = calculate(
        gold,
        instrument="XAUUSDm",
        direction="SELL",
        entry="2000",
        stop_loss="2010",
        take_profit="1980",
        risk_budget="10",
    )
    assert result.theoretical_volume == Decimal("0.1")
    assert result.normalized_volume == Decimal("0.09")
    assert result.expected_gross_loss == Decimal(9)
    assert result.expected_gross_profit == Decimal(18)


def test_minimum_never_rounds_up():
    result = calculate(risk_budget="9.99")
    assert result.status == "NOT_FEASIBLE_SYNTHETIC"
    assert result.loss_per_minimum_volume == Decimal(10)
    assert result.normalized_volume is None
    assert result.expected_gross_loss is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"stop_loss": "1.11"},
        {"stop_loss": "1.10"},
        {"take_profit": "1.09"},
        {"direction": "WAIT"},
        {"risk_budget": "nan"},
        {"entry": None},
        {"feed_status": "UNVERIFIED"},
        {"setup_status": "STALE"},
        {"instrument": "XAUUSDm"},
    ],
)
def test_invalid_setup_fails_closed(overrides):
    with pytest.raises(ValueError):
        calculate(**overrides)


@pytest.mark.parametrize(
    "changes",
    [
        {"tick_value_loss": None},
        {"tick_value_profit": "NaN"},
        {"tick_size": 0},
        {"volume_min": "0.015"},
        {"volume_step": 0},
        {"account_currency": "EUR"},
        {"observed_at_utc": NOW - timedelta(minutes=6)},
        {"observed_at_utc": NOW + timedelta(seconds=1)},
        {"observed_at_utc": NOW.replace(tzinfo=None)},
        {"source_kind": "LIVE"},
    ],
)
def test_invalid_or_unverified_specification_fails_closed(changes):
    with pytest.raises(ValueError):
        calculate(replace(fixture(), **changes))


def test_unknown_costs_margin_are_not_zero_or_verified():
    result = calculate()
    assert any("Commission" in warning for warning in result.warnings)
    assert any("margin" in warning for warning in result.warnings)
    assert result.status != "VERIFIED"


def test_live_api_fails_closed_without_bridge_and_does_not_accept_specification():
    class MissingBridge:
        def get(self, *_):
            raise ValueError("unavailable")

    client = TestClient(create_app(bridge_service=MissingBridge()))
    result = client.get(
        "/api/broker-risk",
        params={"symbol": "EURUSDm", "timeframe": "H1", "verified": "true"},
    )
    assert result.status_code == 200
    data = result.json()
    assert data["verification_status"] == "UNVERIFIED"
    assert data["overall_action_eligibility"] == "BLOCKED_UNVERIFIED"
    assert data["normalized_volume"] is None
    assert data["margin_estimate"] is None
    assert all(value is None for value in data["known_costs"].values())
    assert client.post("/api/broker-risk", json={"verified": True}).status_code == 405
    assert (
        client.get("/api/broker-risk", params={"symbol": "invalid"}).status_code == 422
    )


def test_untrusted_snapshot_preserves_unknowns_and_cannot_authenticate():
    from mt5_market_data.broker_risk import parse_untrusted_broker_snapshot

    payload = (
        b"instrument,property,value,status\r\n"
        b"EURUSDm,tick_size,0.0001,observed\r\n"
        b"EURUSDm,commission,,unavailable_not_inferred\r\n"
        b",broker_observed_at,2026.01.01 00:00:00,broker_time_timezone_unverified\r\n"
    )
    result = parse_untrusted_broker_snapshot(payload)
    assert result.verification_status == "UNVERIFIED"
    assert result.properties[1].value == ""
    assert result.properties[1].status == "unavailable_not_inferred"
    assert result.properties[2].value == "2026.01.01 00:00:00"
    assert result == parse_untrusted_broker_snapshot(payload)
    assert (
        result.payload_sha256
        != parse_untrusted_broker_snapshot(
            payload + b"EURUSDm,volume_min,1,observed\r\n"
        ).payload_sha256
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"bad,header\n",
        b"instrument,property,value,status\n",
        b"instrument,property,value,status\nEURUSDm,tick_size,1,observed\nEURUSDm,tick_size,2,observed\n",
        b"instrument,property,value,status\nOTHER,tick,1,observed\n",
        b"instrument,property,value,status\nEURUSDm,tick,1\n",
    ],
)
def test_untrusted_snapshot_invalid_data_rejected(payload):
    from mt5_market_data.broker_risk import parse_untrusted_broker_snapshot

    with pytest.raises(ValueError):
        parse_untrusted_broker_snapshot(payload)


def test_explicit_snapshot_path_is_read_only_and_does_not_follow_symlinks(tmp_path):
    from mt5_market_data.broker_risk import read_untrusted_broker_snapshot

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    path = runtime / "broker_spec_snapshot.csv"
    payload = b"instrument,property,value,status\nEURUSDm,tick_size,0.0001,observed\n"
    path.write_bytes(payload)
    assert read_untrusted_broker_snapshot(path).verification_status == "UNVERIFIED"
    assert path.read_bytes() == payload
    alias = runtime / "other.csv"
    alias.write_bytes(payload)
    with pytest.raises(ValueError):
        read_untrusted_broker_snapshot(alias)
    path.unlink()
    path.symlink_to(alias)
    with pytest.raises(OSError):
        read_untrusted_broker_snapshot(path)


def test_current_setup_requires_all_existing_quality_gates():
    from copy import deepcopy

    from mt5_market_data.broker_risk import unavailable_broker_risk

    current = {
        "symbol": "EURUSDm",
        "timeframe": "H1",
        "snapshot_sha256": "a" * 64,
        "feed_health": {
            "status": "LIVE",
            "current_segment_count": 50,
            "history_count": 50,
            "unresolved_gap_count": 0,
            "unresolved_revision_count": 0,
        },
        "analysis": {
            "direction": "BUY",
            "pattern_status": "CONFIRMED",
            "target_reference_status": "NOT_AT_OR_BEYOND",
            "entry": 2,
            "stop_loss": 1,
            "take_profit": 3,
            "risk_reward": 1,
        },
    }
    assert unavailable_broker_risk(current)["setup_status"] == "CURRENT"
    for key, value in [
        ("pattern_status", "INVALIDATED"),
        ("pattern_status", None),
        ("target_reference_status", None),
        ("target_reference_status", "AT_OR_BEYOND"),
        ("entry", float("nan")),
        ("stop_loss", 3),
        ("take_profit", None),
    ]:
        candidate = deepcopy(current)
        candidate["analysis"][key] = value
        result = unavailable_broker_risk(candidate)
        assert result["setup_status"] == "UNAVAILABLE_OR_STALE"
        assert result["entry"] is None
    for key, value in (
        ("current_segment_count", 49),
        ("history_count", 49),
        ("history_count", None),
        ("unresolved_gap_count", None),
        ("unresolved_revision_count", None),
        ("unresolved_revision_count", 1),
    ):
        candidate = deepcopy(current)
        candidate["feed_health"][key] = value
        assert (
            unavailable_broker_risk(candidate)["setup_status"] == "UNAVAILABLE_OR_STALE"
        )


@pytest.mark.parametrize(
    "row",
    [
        b"EURUSDm,password,abc,observed\n",
        b"EURUSDm,tick_size,1,made_up\n",
        b"EURUSDm,tick_size,NaN,observed\n",
        b"EURUSDm,tick_size,1,unavailable:5\n",
    ],
)
def test_untrusted_snapshot_rejects_unknown_or_conflicting_fields(row):
    from mt5_market_data.broker_risk import parse_untrusted_broker_snapshot

    with pytest.raises(ValueError):
        parse_untrusted_broker_snapshot(b"instrument,property,value,status\n" + row)


def test_api_never_labels_missing_symbol_observed(monkeypatch):
    from mt5_market_data import terminal_api
    from mt5_market_data.broker_risk import parse_untrusted_broker_snapshot

    payload = b"instrument,property,value,status\nEURUSDm,tick_size,0.0001,observed\n"
    monkeypatch.setattr(
        terminal_api,
        "read_untrusted_broker_snapshot",
        lambda path: parse_untrusted_broker_snapshot(payload),
    )

    class MissingBridge:
        def get(self, *_):
            raise ValueError("unavailable")

    client = TestClient(create_app(bridge_service=MissingBridge()))
    data = client.get("/api/broker-specification", params={"symbol": "XAUUSDm"}).json()
    assert data["specification_status"] == "NO_SYMBOL_DATA"
    assert data["verification_status"] == "UNVERIFIED"
    assert data["properties"] == []
    assert (
        client.get("/api/broker-specification", params={"symbol": "EURUSDm"}).json()[
            "specification_status"
        ]
        == "OBSERVED_UNAUTHENTICATED"
    )


def test_zero_volume_limit_is_allowed_but_exposure_remains_unverified():
    result = calculate(replace(fixture(), volume_limit=0))
    assert result.status == "SYNTHETIC_ONLY"
    assert any("existing exposure" in warning for warning in result.warnings)
    with pytest.raises(ValueError):
        calculate(replace(fixture(), volume_limit=-1))


def test_untrusted_snapshot_plausibility_does_not_establish_source_or_freshness():
    from mt5_market_data.broker_risk import (
        assess_untrusted_specification,
        parse_untrusted_broker_snapshot,
    )

    rows = {
        "contract_size": "100000",
        "point": "0.00001",
        "tick_size": "0.00001",
        "tick_value_profit": "1",
        "tick_value_loss": "1",
        "volume_min": "0.01",
        "volume_max": "10",
        "volume_step": "0.01",
        "bid": "1.1000",
        "ask": "1.1001",
        "digits": "5",
        "selected": "1",
        "synchronized": "1",
        "profit_currency": "USD",
        "margin_currency": "EUR",
        "base_currency": "EUR",
        "profit_calculation_mode": "0",
        "stops_level_points": "0",
        "freeze_level_points": "0",
        "tick_broker_time": "2026.01.01 00:00:00",
    }

    def snapshot(changes):
        lines = [
            "instrument,property,value,status",
            ",server,Exness-Demo,terminal_reported",
            ",account_type,demo,terminal_reported",
            ",account_currency,USD,terminal_reported",
            ",broker_observed_at,2026.01.01 00:00:00,broker_time_timezone_unverified",
            ",host_observed_at,2026.01.01 00:00:00,host_clock_not_authenticated",
        ]
        lines += [
            f"EURUSDm,{key},{value},observed" for key, value in (rows | changes).items()
        ]
        return parse_untrusted_broker_snapshot(("\n".join(lines) + "\n").encode())

    good = assess_untrusted_specification(snapshot({}), "EURUSDm")
    assert good["assessment"] == "OBSERVED_UNAUTHENTICATED"
    assert good["verification_status"] == "UNVERIFIED"
    assert good["freshness_status"] == "UNKNOWN_BROKER_CLOCK"
    for changes in (
        {"tick_size": "0"},
        {"contract_size": "-1"},
        {"ask": "1.0"},
        {"volume_step": "0.03"},
        {"synchronized": "0"},
        {"volume_step": "1e-999"},
    ):
        assert assess_untrusted_specification(snapshot(changes), "EURUSDm")["problems"]
    assert assess_untrusted_specification(snapshot({}), "XAUUSDm")["problems"]


def test_native_profit_comparison_reports_exact_mismatch_and_never_verifies():
    from mt5_market_data.broker_risk import compare_untrusted_native_profit

    args = {
        "direction": "BUY",
        "volume": "0.01",
        "open_price": "1.10",
        "close_price": "1.09",
        "tick_size": "0.0001",
        "tick_value_profit": "12",
        "tick_value_loss": "10",
    }
    matched = compare_untrusted_native_profit(**args, native_profit="-10")
    assert Decimal(matched["absolute_difference"]) == 0
    assert matched["calculation_status"] == "UNVERIFIED_UNTRUSTED_OBSERVATION"
    mismatch = compare_untrusted_native_profit(**args, native_profit="-8")
    assert Decimal(mismatch["absolute_difference"]) == 2
    assert Decimal(mismatch["relative_difference"]) == Decimal("0.25")
    assert (
        compare_untrusted_native_profit(**args, native_profit=0)["relative_difference"]
        is None
    )
    with pytest.raises(ValueError):
        compare_untrusted_native_profit(
            **(args | {"tick_size": 0}), native_profit="-10"
        )


def test_untrusted_native_probe_comparison_preserves_mismatch_and_blocks_authority():
    from mt5_market_data.broker_native import (
        compare_probe_records,
        parse_untrusted_native_probe,
    )
    from mt5_market_data.broker_risk import parse_untrusted_broker_snapshot

    spec = parse_untrusted_broker_snapshot(
        b"instrument,property,value,status\n"
        b",account_currency,USD,terminal_reported\n"
        b"EURUSDm,tick_size,0.0001,observed\n"
        b"EURUSDm,tick_value_profit,12,observed\n"
        b"EURUSDm,tick_value_loss,10,observed\n"
        b"EURUSDm,profit_currency,USD,observed\n"
        b"EURUSDm,volume_min,0.01,observed\n"
        b"EURUSDm,volume_max,10,observed\n"
        b"EURUSDm,volume_step,0.01,observed\n"
    )
    data = (
        b"instrument,direction,case,volume,open_price,close_price,quote_broker_time,account_currency,native_profit,profit_status,native_margin,margin_status\n"
        b"EURUSDm,BUY,stop,0.01,1.10,1.09,2026.01.01 00:00:00,USD,-8,observed,2,observed\n"
    )
    records = parse_untrusted_native_probe(data)
    result = compare_probe_records(data, records, spec, "EURUSDm")
    assert result["verification_status"] == "UNVERIFIED"
    assert Decimal(
        result["comparisons"][0]["comparison"]["absolute_difference"]
    ) == Decimal(2)
    assert result["comparisons"][0]["native_margin"] == "2"
    assert compare_probe_records(data, records, spec, "XAUUSDm")["comparisons"] == []
    invalid_volume = parse_untrusted_native_probe(
        data.replace(b",0.01,1.10", b",0.015,1.10")
    )
    assert (
        compare_probe_records(data, invalid_volume, spec, "EURUSDm")["comparisons"][0][
            "comparison"
        ]
        is None
    )
    mismatch_currency = parse_untrusted_native_probe(
        data.replace(b",USD,-8", b",EUR,-8")
    )
    assert (
        compare_probe_records(data, mismatch_currency, spec, "EURUSDm")["comparisons"][
            0
        ]["comparison"]
        is None
    )
    with pytest.raises(ValueError):
        parse_untrusted_native_probe(data + data.splitlines(keepends=True)[1])
    with pytest.raises(ValueError):
        parse_untrusted_native_probe(data.replace(b"1.09", b"1.11"))
    with pytest.raises(ValueError):
        parse_untrusted_native_probe(
            data.replace(b",observed,2,observed", b",unknown,2,observed")
        )


def test_native_comparison_api_is_read_only_and_fails_closed(monkeypatch):
    from mt5_market_data import terminal_api

    def unavailable(_path):
        raise FileNotFoundError("synthetic missing snapshot")

    monkeypatch.setattr(terminal_api, "read_untrusted_broker_snapshot", unavailable)

    class MissingBridge:
        def get(self, *_):
            raise ValueError("unavailable")

    client = TestClient(create_app(bridge_service=MissingBridge()))
    response = client.get("/api/broker-native-comparison?symbol=EURUSDm")
    assert response.status_code == 200
    assert response.json()["verification_status"] == "UNVERIFIED"
    assert response.json()["comparisons"] == []
    assert client.post("/api/broker-native-comparison", json={}).status_code == 405


def test_user_budget_is_illustrative_when_broker_and_setup_unavailable():
    class MissingBridge:
        def get(self, *_):
            raise ValueError("unavailable")

    client = TestClient(create_app(bridge_service=MissingBridge()))
    response = client.get(
        "/api/broker-risk",
        params={"symbol": "EURUSDm", "timeframe": "H1", "risk_budget_usd": "7.25"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["risk_budget"] == 7.25
    assert result["risk_budget_basis"] == "USER_PROVIDED_ILLUSTRATIVE_USD"
    assert result["verification_status"] == "UNVERIFIED"
    assert result["overall_action_eligibility"] == "BLOCKED_UNVERIFIED"
    assert result["normalized_volume"] is None
    assert result["margin_estimate"] is None
    assert all(value is None for value in result["known_costs"].values())


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "nan", "inf", "-Infinity", "1e999", "1e-9999", "1000000.01", "bad"],
)
def test_invalid_user_budget_is_rejected_without_accessing_market(value):
    class MustNotRead:
        def get(self, *_):
            raise AssertionError("invalid input must be rejected before market reads")

    client = TestClient(create_app(bridge_service=MustNotRead()))
    response = client.get("/api/broker-risk", params={"risk_budget_usd": value})
    assert response.status_code == 422
    assert "finite, positive" in response.json()["detail"]


def test_budget_upper_limit_is_accepted_but_does_not_verify_broker():
    class MissingBridge:
        def get(self, *_):
            raise ValueError("unavailable")

    client = TestClient(create_app(bridge_service=MissingBridge()))
    response = client.get("/api/broker-risk", params={"risk_budget_usd": "1000000"})
    assert response.status_code == 200
    assert response.json()["risk_budget"] == 1000000
    assert response.json()["overall_action_eligibility"] == "BLOCKED_UNVERIFIED"


def test_user_budget_does_not_modify_current_analysis_or_verify_live_risk(monkeypatch):
    from test_mt5_api import FakeBridge, _analysis

    from mt5_market_data import terminal_api

    def current_analysis(*args, **kwargs):
        result = _analysis(*args, **kwargs)
        result["analysis"]["pattern_status"] = "CONFIRMED"
        result["analysis"]["target_reference_status"] = "NOT_AT_OR_BEYOND"
        return result

    monkeypatch.setattr(terminal_api, "analyze_bars", current_analysis)
    client = TestClient(create_app(bridge_service=FakeBridge(status="LIVE")))
    params = {"symbol": "EURUSDm", "timeframe": "H1", "risk_budget_usd": "12.5"}
    response = client.get("/api/broker-risk", params=params)
    assert response.status_code == 200
    result = response.json()
    assert result["snapshot_sha256"] == "a" * 64
    assert result["setup_status"] == "CURRENT"
    assert result["entry"] == 1.0
    assert result["risk_budget"] == 12.5
    assert result["overall_action_eligibility"] == "BLOCKED_UNVERIFIED"
    assert result["normalized_volume"] is None
    assert result["margin_estimate"] is None
