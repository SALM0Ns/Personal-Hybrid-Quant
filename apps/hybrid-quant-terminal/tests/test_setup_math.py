"""Independent synthetic checks for non-executable setup reference mathematics."""

import math
from decimal import Decimal

import pytest

from mt5_market_data.terminal_analysis import AnalysisConfig, _risk_setup


@pytest.mark.parametrize(
    "kind,entry,anchor1,anchor2,atr,close,expected_stop,expected_target,digits",
    [
        (
            "DOUBLE_BOTTOM",
            "1.08565",
            "1.08400",
            "1.08420",
            "0.00100",
            "1.08570",
            "1.08390",
            "1.08915",
            5,
        ),
        (
            "DOUBLE_TOP",
            "2350.125",
            "2352.345",
            "2352.120",
            "2.5",
            "2349",
            "2352.595",
            "2345.185",
            3,
        ),
    ],
)
def test_setup_matches_independent_decimal_geometry(
    kind, entry, anchor1, anchor2, atr, close, expected_stop, expected_target, digits
):
    # These Decimal calculations deliberately do not use the implementation's math.
    e, a1, a2, a = map(Decimal, (entry, anchor1, anchor2, atr))
    bottom = kind == "DOUBLE_BOTTOM"
    stop = (
        min(a1, a2) - Decimal("0.1") * a if bottom else max(a1, a2) + Decimal("0.1") * a
    )
    target = e + Decimal(2) * abs(e - stop) * (1 if bottom else -1)
    assert stop == Decimal(expected_stop)
    assert target == Decimal(expected_target)
    pattern = {
        "type": kind,
        "neckline": float(e),
        "anchor_1_price": float(a1),
        "anchor_2_price": float(a2),
    }
    actual = _risk_setup(pattern, float(a), True, float(close), AnalysisConfig())
    assert actual["direction"] == ("BUY" if bottom else "SELL")
    for key, expected in (("entry", e), ("stop_loss", stop), ("take_profit", target)):
        assert math.isfinite(actual[key])
        assert actual[key] == pytest.approx(float(expected), rel=0, abs=1e-12)
        assert f"{actual[key]:.{digits}f}" == f"{expected:.{digits}f}"
    assert (
        (actual["stop_loss"] < actual["entry"] < actual["take_profit"])
        if bottom
        else (actual["take_profit"] < actual["entry"] < actual["stop_loss"])
    )
    assert abs(actual["take_profit"] - actual["entry"]) / abs(
        actual["entry"] - actual["stop_loss"]
    ) == pytest.approx(2.0)
    assert actual["overall_action"] == "WAIT"
    assert actual["execution_eligibility"] == "BLOCKED_UNVERIFIED"


@pytest.mark.parametrize("kind", ["DOUBLE_BOTTOM", "DOUBLE_TOP"])
def test_reward_so_small_that_target_rounds_to_entry_is_rejected(kind):
    bottom = kind == "DOUBLE_BOTTOM"
    pattern = {
        "type": kind,
        "neckline": 1.09,
        "anchor_1_price": 1.08 if bottom else 1.10,
        "anchor_2_price": 1.08 if bottom else 1.10,
    }
    result = _risk_setup(pattern, 0.01, True, 1.09, AnalysisConfig(risk_reward=1e-30))
    assert result["direction"] == "WAIT"
    assert result["entry"] is result["stop_loss"] is result["take_profit"] is None
    assert result["risk_reward"] is None
    assert "Proposed target is invalid." in result["blocking_reasons"]


@pytest.mark.parametrize(
    "entry,anchor,atr,digits,display",
    [
        (1.000001, 0.9999995, 0.000001, 5, "1.00000"),
        (2000.0001, 1999.99995, 0.0001, 3, "2000.000"),
    ],
)
def test_raw_valid_prices_can_collapse_at_display_precision(
    entry, anchor, atr, digits, display
):
    pattern = {
        "type": "DOUBLE_BOTTOM",
        "neckline": entry,
        "anchor_1_price": anchor,
        "anchor_2_price": anchor,
    }
    result = _risk_setup(pattern, atr, True, entry, AnalysisConfig())
    assert result["stop_loss"] < result["entry"] < result["take_profit"]
    assert {
        f"{result[k]:.{digits}f}" for k in ("entry", "stop_loss", "take_profit")
    } == {display}


def test_unavailable_indicators_or_invalid_stop_never_create_levels():
    pattern = {
        "type": "DOUBLE_BOTTOM",
        "neckline": 1.0,
        "anchor_1_price": 1.1,
        "anchor_2_price": 1.1,
    }
    for atr, ready in ((1.0, False), (0.0, True), (0.1, True)):
        result = _risk_setup(pattern, atr, ready, 1.0, AnalysisConfig())
        assert result["direction"] == "WAIT"
        assert result["entry"] is result["stop_loss"] is result["take_profit"] is None


def test_sell_target_below_zero_is_rejected():
    pattern = {
        "type": "DOUBLE_TOP",
        "neckline": 1.0,
        "anchor_1_price": 4.0,
        "anchor_2_price": 4.0,
    }
    result = _risk_setup(pattern, 1.0, True, 1.0, AnalysisConfig())
    assert result["direction"] == "WAIT"
    assert result["entry"] is result["stop_loss"] is result["take_profit"] is None


@pytest.mark.parametrize("ratio", [0, -1, float("nan"), float("inf")])
def test_invalid_reward_ratio_is_rejected(ratio):
    with pytest.raises(ValueError):
        AnalysisConfig(risk_reward=ratio)
