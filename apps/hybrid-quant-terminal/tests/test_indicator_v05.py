"""Independent, synthetic mathematical and time-boundary checks for v0.5."""

from copy import deepcopy
from datetime import datetime, timedelta
from fractions import Fraction

import pytest

from mt5_market_data.indicators import ADX, ATR, EMA, IndicatorConfig
from mt5_market_data.strategies import generate_decisions
from mt5_market_data.terminal_analysis import analyze_bars


def test_ema_against_exact_fraction_reference():
    ema = EMA(3)
    actual = [ema.update(v) for v in (1.0, 2.0, 4.0, 8.0, 16.0)]
    expected = [None, None, Fraction(7, 3), Fraction(31, 6), Fraction(127, 12)]
    assert actual[:2] == expected[:2]
    assert actual[2:] == pytest.approx([float(v) for v in expected[2:]], rel=1e-14)


def test_true_range_captures_price_jumps_and_wilder_smoothing():
    atr = ATR(3)
    bars = [(11, 9, 10), (12, 9, 11), (13, 10, 12), (8, 7, 7.5)]
    actual = [atr.update(*b) for b in bars]
    assert actual[:2] == [None, None]
    assert actual[2] == pytest.approx(Fraction(8, 3))
    assert actual[3] == pytest.approx(Fraction(31, 9))  # TR = |7 - 12| = 5


def test_adx_golden_mixed_direction_and_wilder_recursion():
    # n=3; first three DX values are 50, 50, 1300/17; fourth is 500/19.
    adx = ADX(3)
    bars = [
        (10, 8, 9),
        (12, 9, 11),
        (12, 8, 9),
        (13, 10, 12),
        (13, 11, 12),
        (15, 10, 14),
        (14, 9, 10),
    ]
    actual = [adx.update(*b) for b in bars]
    assert actual[:5] == [None] * 5
    assert actual[5] == pytest.approx(Fraction(1000, 17), rel=1e-14)
    assert actual[6] == pytest.approx(
        (2 * Fraction(1000, 17) + Fraction(500, 19)) / 3, rel=1e-14
    )


def test_flat_market_zero_range_atr_and_adx_are_finite():
    atr, adx = ATR(3), ADX(3)
    assert [atr.update(10.0, 10.0, 10.0) for _ in range(7)] == [
        None,
        None,
        0,
        0,
        0,
        0,
        0,
    ]
    assert [adx.update(10.0, 10.0, 10.0) for _ in range(7)] == [
        None,
        None,
        None,
        None,
        None,
        0,
        0,
    ]


@pytest.mark.parametrize("kind", ["ema", "atr", "adx"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_direct_indicator_inputs_fail_closed(kind, value):
    indicator = {"ema": EMA(2), "atr": ATR(2), "adx": ADX(2)}[kind]
    with pytest.raises(ValueError, match="nonfinite"):
        indicator.update(value) if kind == "ema" else indicator.update(value, 1.0, 1.0)


def test_finite_extreme_prices_cannot_return_nonfinite_indicator_values():
    rows = [
        {
            "timestamp": datetime(2024, 1, 1) + timedelta(hours=i),
            "open": 1e308,
            "high": 1.1e308,
            "low": 9e307,
            "close": 1e308,
        }
        for i in range(60)
    ]
    original = deepcopy(rows)
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_bars(rows, "H1")
    assert rows == original


@pytest.mark.parametrize(("timeframe", "step"), [("M15", 15), ("H1", 60), ("H4", 240)])
def test_gap_resets_all_indicator_warmups_and_matches_fresh_segment(timeframe, step):
    start = datetime(2024, 1, 1)

    def row(t, price):
        return {
            "timestamp": t,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
        }

    first = [
        row(start + timedelta(minutes=step * i), 100.0 + i / 10) for i in range(60)
    ]
    second = [
        row(start + timedelta(minutes=step * (61 + i)), 120.0 + i / 10)
        for i in range(52)
    ]
    full = analyze_bars(first + second, timeframe)
    fresh = analyze_bars(second, timeframe)
    assert full["indicators"][60:] == fresh["indicators"]
    assert all(
        full["indicators"][60][k] is None for k in ("ema20", "ema50", "atr14", "adx14")
    )
    assert full["indicators"][60 + 48]["ema50"] is None
    assert full["indicators"][60 + 49]["ema50"] is not None


@pytest.mark.parametrize(("timeframe", "step"), [("M15", 15), ("H1", 60), ("H4", 240)])
def test_indicator_prefix_invariance_across_timeframes(timeframe, step):
    start = datetime(2024, 1, 1)
    rows = [
        {
            "timestamp": start + timedelta(minutes=step * i),
            "open": 100 + i / 10,
            "high": 101 + i / 10,
            "low": 99 + i / 10,
            "close": 100 + i / 10,
        }
        for i in range(65)
    ]
    before = deepcopy(rows)
    assert (
        analyze_bars(rows[:55], timeframe)["indicators"]
        == analyze_bars(rows, timeframe)["indicators"][:55]
    )
    assert rows == before


def test_h1_context_enters_exactly_on_its_close_boundary():
    start = datetime(2024, 1, 1, 8)

    def bar(t, p):
        return {"timestamp": t, "open": p, "high": p + 1, "low": p - 1, "close": p}

    m15 = [bar(start + timedelta(minutes=15 * i), 100 + i / 10) for i in range(8)]
    h1 = [
        bar(start - timedelta(hours=1), 99),
        bar(start, 100),
        bar(start + timedelta(hours=1), 101),
    ]
    config = IndicatorConfig(
        ema_fast=1, ema_slow=2, adx_period=2, atr_period=1, donchian_period=1
    )
    output = generate_decisions(
        {"M15": m15, "H1": h1, "H4": []},
        {"H1": {b["timestamp"]: "matched" for b in h1}, "H4": {}},
        "donchian",
        config,
    )
    assert [x["h1_open"] for x in output[:3]] == [start - timedelta(hours=1)] * 3
    assert output[3]["decision_at"] == start + timedelta(hours=1)
    assert output[3]["h1_open"] == start
    changed = deepcopy(h1)
    changed[1].update(open=200.0, high=201.0, low=199.0, close=200.0)
    altered = generate_decisions(
        {"M15": m15, "H1": changed, "H4": []},
        {"H1": {b["timestamp"]: "matched" for b in h1}, "H4": {}},
        "donchian",
        config,
    )
    assert output[:3] == altered[:3]
    assert output[3]["h1_context"] != altered[3]["h1_context"]


def test_h4_context_is_unavailable_until_its_exact_closure():
    start = datetime(2024, 1, 1)

    def bar(t, price):
        return {
            "timestamp": t,
            "open": price - 0.05,
            "high": price + 0.05,
            "low": price - 0.1,
            "close": price,
        }

    m15 = [bar(start + timedelta(minutes=15 * i), 100 + i * 0.2) for i in range(68)]
    h1 = [bar(start + timedelta(hours=i), 100 + i) for i in range(17)]
    h4 = [bar(start + timedelta(hours=4 * i), 100 + 10 * i) for i in range(4)]
    alignments = {
        "H1": {row["timestamp"]: "matched" for row in h1},
        "H4": {row["timestamp"]: "matched" for row in h4},
    }
    config = IndicatorConfig(
        ema_fast=2,
        ema_slow=3,
        adx_period=2,
        atr_period=1,
        donchian_period=1,
        h4_confirm=True,
    )
    before = generate_decisions(
        {"M15": m15, "H1": h1, "H4": h4}, alignments, "donchian", config
    )
    changed = deepcopy(h4)
    changed[3].update(open=79.95, high=80.05, low=79.9, close=80.0)
    after = generate_decisions(
        {"M15": m15, "H1": h1, "H4": changed}, alignments, "donchian", config
    )
    # The 12:00 H4 candle closes at 16:00; 15:45 M15 is the first eligible origin.
    first = next(
        i
        for i, item in enumerate(before)
        if item["decision_at"] == start + timedelta(hours=16)
    )
    assert before[:first] == after[:first]
    assert before[first]["decision"] == "BUY"
    assert after[first]["decision"] == "WAIT"
