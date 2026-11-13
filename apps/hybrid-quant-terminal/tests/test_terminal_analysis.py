"""Synthetic tests for causal historical chart analysis; no market data access."""

from datetime import datetime, timedelta

import pytest

from mt5_market_data.terminal_analysis import (
    AnalysisConfig,
    _advance_patterns,
    _make_pattern,
    _risk_setup,
    _zone_update,
    analyze_bars,
)

START = datetime(2024, 1, 1)


def candles(values):
    return [
        {
            "timestamp": START + timedelta(hours=i),
            "open": float(v),
            "high": float(v + 1),
            "low": float(v - 1),
            "close": float(v),
        }
        for i, v in enumerate(values)
    ]


def swing(index, price, kind):
    return {
        "pivot_timestamp": (START + timedelta(hours=index)).isoformat(),
        "confirmed_at_timestamp": (START + timedelta(hours=index + 4)).isoformat(),
        "pivot_price": float(price),
        "swing_type": kind,
        "_index": index,
    }


def pattern(top=True):
    first = swing(10, 100 if top else 80, "HIGH" if top else "LOW")
    middle = swing(15, 85 if top else 95, "LOW" if top else "HIGH")
    second = swing(20, 100.2 if top else 80.2, first["swing_type"])
    return _make_pattern(
        first, second, [first, middle], 2.0, "2024-01-02T00:00:00", AnalysisConfig()
    )


def test_swing_confirmation_requires_right_bars_and_strict_ties():
    rows = candles([10, 11, 12, 15, 12, 11, 10])
    assert not analyze_bars(rows[:-1], "H1")["swings"]
    result = analyze_bars(rows, "H1")
    pivot = result["swings"][0]
    assert pivot["pivot_timestamp"] == "2024-01-01T03:00:00"
    assert pivot["confirmed_at_timestamp"] == "2024-01-01T07:00:00"
    tied = candles([10, 11, 15, 15, 12, 11, 10])
    assert not analyze_bars(tied, "H1")["swings"]


@pytest.mark.parametrize("top", [True, False])
def test_double_pattern_requires_confirmed_pivots_and_close_break(top):
    p = pattern(top)
    assert p and p["status"] == "FORMING"
    assert p["type"] == ("DOUBLE_TOP" if top else "DOUBLE_BOTTOM")
    _advance_patterns([p], p["neckline"], "2024-01-02T01:00:00")
    assert p["status"] == "FORMING"  # strict breakout, no equality
    _advance_patterns([p], p["neckline"] + (-1 if top else 1), "2024-01-02T02:00:00")
    assert p["status"] == "CONFIRMED"
    assert p["confirmation_timestamp"] == "2024-01-02T02:00:00"
    _advance_patterns([p], 103 if top else 77, "2024-01-02T03:00:00")
    assert p["status"] == "INVALIDATED"
    assert p["invalidation_timestamp"] == "2024-01-02T03:00:00"


def test_no_pattern_without_intervening_opposite_swing():
    first, second = swing(1, 100, "HIGH"), swing(8, 100, "HIGH")
    assert (
        _make_pattern(first, second, [], 2.0, "2024-01-02T00:00:00", AnalysisConfig())
        is None
    )


def test_zones_cluster_touches_and_do_not_publish_a_single_touch():
    zones = []
    _zone_update(zones, swing(1, 100, "HIGH"), 1, 2)
    assert zones[0]["confirmed_at_timestamp"] is None
    _zone_update(zones, swing(5, 100.5, "HIGH"), 1, 2)
    assert len(zones) == 1
    assert zones[0]["touches"] == 2
    assert (
        zones[0]["confirmed_at_timestamp"]
        == swing(5, 100.5, "HIGH")["confirmed_at_timestamp"]
    )
    assert zones[0]["lower"] <= 100 <= zones[0]["upper"]


@pytest.mark.parametrize("top", [True, False])
def test_setup_geometry_and_execution_remains_blocked(top):
    p = pattern(top)
    r = _risk_setup(p, 2.0, True, p["neckline"], AnalysisConfig(contract_size=100_000))
    assert r["direction"] == ("SELL" if top else "BUY")
    assert r["overall_action"] == "WAIT"
    assert r["execution_eligibility"] == "BLOCKED_UNVERIFIED"
    assert r["risk_reward"] == 2.0
    assert abs(r["entry"] - r["take_profit"]) == pytest.approx(
        2 * abs(r["entry"] - r["stop_loss"])
    )
    assert r["risk"]["feasibility"] == "UNVERIFIED"
    assert r["risk"]["estimated_trading_costs"] is None


def test_no_indicators_or_pattern_means_wait():
    assert _risk_setup(pattern(), 2, False, 90, AnalysisConfig())["direction"] == "WAIT"
    assert _risk_setup(None, 2, True, 90, AnalysisConfig())["entry"] is None


def test_gap_resets_indicator_warmup_and_prevents_cross_gap_pivots():
    rows = candles([100] * 55)
    rows.append({**rows[-1], "timestamp": rows[-1]["timestamp"] + timedelta(hours=2)})
    result = analyze_bars(rows, "H1")
    assert result["indicators"][-2]["ema50"] is not None
    assert result["indicators"][-1]["ema50"] is None
    assert result["analysis"]["direction"] == "WAIT"


def test_no_future_leakage_into_indicator_or_pivot_confirmation():
    rows = candles([100 + ((i % 9) - 4) ** 2 / 10 for i in range(80)])
    before = analyze_bars(rows[:60], "H1")
    after = analyze_bars(rows, "H1")
    assert before["indicators"] == after["indicators"][:60]
    assert before["swings"] == [
        s
        for s in after["swings"]
        if s["confirmed_at_timestamp"] <= (START + timedelta(hours=60)).isoformat()
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(high=0),
        lambda r: r.update(close=float("nan")),
        lambda r: r.pop("low"),
    ],
)
def test_invalid_bar_rejected(mutate):
    row = candles([100])[0]
    mutate(row)
    with pytest.raises(ValueError):
        analyze_bars([row], "H1")


def test_duplicate_and_out_of_order_rejected():
    rows = candles([100, 101])
    with pytest.raises(ValueError):
        analyze_bars([rows[0], rows[0]], "H1")
    with pytest.raises(ValueError):
        analyze_bars(rows[::-1], "H1")


def test_empty_input_and_determinism():
    assert analyze_bars([], "H1")["analysis"] is None
    rows = candles([100 + i % 5 for i in range(60)])
    assert analyze_bars(rows, "H1") == analyze_bars(rows, "H1")


def test_h4_does_not_assume_a_universal_four_hour_anchor():
    row = {**candles([100])[0], "timestamp": datetime(2024, 1, 1, 1)}
    assert analyze_bars([row], "H4")["analysis"]["timestamp"] == "2024-01-01T01:00:00"


def test_nominal_position_size_never_exceeds_budget():
    p = pattern(False)
    result = _risk_setup(p, 2.0, True, 100, AnalysisConfig(contract_size=100))
    assert result["risk"]["estimated_risk_usd"] <= result["risk"]["risk_budget_usd"]
    assert result["trigger_condition"] == "completed close strictly above neckline"
    assert result["trigger_reached"] is True


@pytest.mark.parametrize(
    ("prices", "kind"),
    [
        (
            [101, 103, 107, 103, 100, 96, 94, 96, 100, 104, 107, 104, 99, 93, 92],
            "DOUBLE_TOP",
        ),
        (
            [99, 97, 93, 97, 100, 104, 106, 104, 100, 96, 93, 96, 101, 107, 108],
            "DOUBLE_BOTTOM",
        ),
    ],
)
def test_full_candle_pattern_only_appears_and_confirms_when_known(prices, kind):
    rows = candles([100] * 20 + prices)
    config = AnalysisConfig(left=1, right=1)
    assert not analyze_bars(rows[:31], "H1", config=config)["patterns"]
    forming = analyze_bars(rows[:32], "H1", config=config)["patterns"]
    assert len(forming) == 1 and forming[0]["status"] == "FORMING"
    full = analyze_bars(rows, "H1", config=config)["patterns"]
    assert (
        len(full) == 1 and full[0]["type"] == kind and full[0]["status"] == "CONFIRMED"
    )
    assert full[0]["detection_timestamp"] < full[0]["confirmation_timestamp"]


def test_gap_ends_pattern_tracking_without_fabricating_invalidation():
    rows = candles(
        [100] * 20 + [101, 103, 107, 103, 100, 96, 94, 96, 100, 104, 107, 104]
    )
    rows.append({**rows[-1], "timestamp": rows[-1]["timestamp"] + timedelta(hours=2)})
    result = analyze_bars(rows, "H1", config=AnalysisConfig(left=1, right=1))
    assert result["patterns"][0]["tracking_ended_reason"] == "unverified_gap"
    assert result["patterns"][0]["invalidation_timestamp"] is None
    assert result["patterns"][0]["tracking_ended_at_timestamp"] == (
        rows[-1]["timestamp"] + timedelta(hours=1)
    ).isoformat(timespec="seconds")
    assert result["analysis"]["direction"] == "WAIT"


def test_zone_current_geometry_gets_new_availability_timestamp():
    zones = []
    _zone_update(zones, swing(1, 100, "HIGH"), 1, 2)
    _zone_update(zones, swing(5, 100.5, "HIGH"), 1, 2)
    initial_confirmation = zones[0]["confirmed_at_timestamp"]
    original_upper = zones[0]["upper"]
    _zone_update(zones, swing(9, 101, "HIGH"), 1, 2)
    assert zones[0]["upper"] > original_upper
    assert zones[0]["confirmed_at_timestamp"] == initial_confirmation
    assert (
        zones[0]["last_updated_at_timestamp"]
        == swing(9, 101, "HIGH")["confirmed_at_timestamp"]
    )
    assert zones[0]["last_updated_at_timestamp"] > initial_confirmation


def test_indicator_theoretical_availability_is_candle_end():
    row = candles([100])[0]
    result = analyze_bars([row], "H1")
    assert result["indicators"][0]["available_at_timestamp"] == "2024-01-01T01:00:00"
    assert result["analysis"]["available_at_timestamp"] == "2024-01-01T01:00:00"


def test_nominal_risk_check_distinguishes_absent_failed_and_illustrative():
    assert (
        _risk_setup(None, 2, True, 100, AnalysisConfig())["risk"]["risk_check"]
        == "NOT_EVALUATED"
    )
    assert (
        _risk_setup(pattern(), 2, True, 100, AnalysisConfig())["risk"]["risk_check"]
        == "UNVERIFIED"
    )
    blocked = _risk_setup(
        pattern(), 2, True, 100, AnalysisConfig(contract_size=100_000)
    )
    assert blocked["risk"]["risk_check"] == "BLOCKED_MINIMUM_LOT"
    passed = _risk_setup(pattern(), 2, True, 100, AnalysisConfig(contract_size=1))
    assert passed["risk"]["risk_check"] == "PASS_ILLUSTRATIVE"
    assert passed["execution_eligibility"] == "BLOCKED_UNVERIFIED"


@pytest.mark.parametrize("top", [True, False])
def test_latest_close_target_status_is_directional_and_never_a_fill(top):
    p = pattern(top)
    config = AnalysisConfig()
    initial = _risk_setup(p, 2.0, True, p["neckline"], config)
    target = initial["take_profit"]
    assert initial["target_reference_status"] == "NOT_AT_OR_BEYOND"
    reached = _risk_setup(p, 2.0, True, target, config)
    assert reached["target_reference_status"] == "AT_OR_BEYOND"
    assert reached["overall_action"] == "WAIT"
    assert any("stale references" in reason for reason in reached["blocking_reasons"])
    further = target - 1 if top else target + 1
    assert (
        _risk_setup(p, 2.0, True, further, config)["target_reference_status"]
        == "AT_OR_BEYOND"
    )
    assert (
        _risk_setup(None, 2, True, 100, config)["target_reference_status"]
        == "NOT_APPLICABLE"
    )


def test_pattern_events_are_prefix_consistent_across_lifecycle():
    # Independent prefix runs must not reveal pivots, confirmation, or invalidation
    # before the closing boundary at which that event first becomes knowable.
    rows = candles(
        [100] * 20
        + [101, 103, 107, 103, 100, 96, 94, 96, 100, 104, 107, 104, 99, 93, 92, 115]
    )
    config = AnalysisConfig(left=1, right=1)
    final = analyze_bars(rows, "H1", config=config)
    by_id = {p["id"]: p for p in final["patterns"]}
    assert by_id
    assert any(p["confirmation_timestamp"] for p in by_id.values())
    assert any(p["invalidation_timestamp"] for p in by_id.values())
    assert len(by_id) == len(final["patterns"])
    stable_fields = (
        "id",
        "type",
        "anchor_1_timestamp",
        "anchor_1_price",
        "anchor_2_timestamp",
        "anchor_2_price",
        "neckline_timestamp",
        "neckline",
        "detection_timestamp",
        "price_tolerance",
        "relevant_atr",
    )
    for count in range(1, len(rows) + 1):
        boundary = (rows[count - 1]["timestamp"] + timedelta(hours=1)).isoformat(
            timespec="seconds"
        )
        actual = analyze_bars(rows[:count], "H1", config=config)["patterns"]
        assert {p["id"] for p in actual} == {
            p["id"] for p in final["patterns"] if p["detection_timestamp"] <= boundary
        }
        for p in actual:
            eventual = by_id[p["id"]]
            assert {k: p[k] for k in stable_fields} == {
                k: eventual[k] for k in stable_fields
            }
            confirmation = eventual["confirmation_timestamp"]
            invalidation = eventual["invalidation_timestamp"]
            assert p["confirmation_timestamp"] == (
                confirmation if confirmation and confirmation <= boundary else None
            )
            assert p["invalidation_timestamp"] == (
                invalidation if invalidation and invalidation <= boundary else None
            )
            expected = (
                "INVALIDATED"
                if invalidation and invalidation <= boundary
                else "CONFIRMED"
                if confirmation and confirmation <= boundary
                else "FORMING"
            )
            assert p["status"] == expected


def test_gap_termination_is_known_only_after_next_completed_bar():
    rows = candles(
        [100] * 20 + [101, 103, 107, 103, 100, 96, 94, 96, 100, 104, 107, 104]
    )
    config = AnalysisConfig(left=1, right=1)
    before = analyze_bars(rows, "H1", config=config)["patterns"][0]
    assert before["tracking_ended_reason"] is None
    assert before["tracking_ended_at_timestamp"] is None
    next_open = rows[-1]["timestamp"] + timedelta(hours=2)
    after = analyze_bars(
        rows + [{**rows[-1], "timestamp": next_open}], "H1", config=config
    )["patterns"][0]
    assert after["tracking_ended_reason"] == "unverified_gap"
    assert after["tracking_ended_at_timestamp"] == (
        next_open + timedelta(hours=1)
    ).isoformat(timespec="seconds")
    assert after["invalidation_timestamp"] is None


def test_swing_and_zone_availability_never_precedes_confirmation():
    rows = candles([100 + ((i % 9) - 4) ** 2 / 10 for i in range(90)])
    config = AnalysisConfig(left=2, right=2)
    full = analyze_bars(rows, "H1", config=config)
    assert full["swings"]
    assert full["zones"]
    for count in range(1, len(rows) + 1):
        snapshot = analyze_bars(rows[:count], "H1", config=config)
        boundary = (rows[count - 1]["timestamp"] + timedelta(hours=1)).isoformat(
            timespec="seconds"
        )
        assert snapshot["swings"] == [
            s for s in full["swings"] if s["confirmed_at_timestamp"] <= boundary
        ]
        for zone in snapshot["zones"]:
            assert (
                zone["first_detection_timestamp"]
                <= zone["confirmed_at_timestamp"]
                <= zone["last_updated_at_timestamp"]
                <= boundary
            )
            assert zone["touches"] >= config.min_touches
            assert zone["lower"] <= zone["price"] <= zone["upper"]
