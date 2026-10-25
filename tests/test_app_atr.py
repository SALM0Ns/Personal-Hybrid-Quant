"""Synthetic Wilder ATR and reference-level checks, without broker execution."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import timedelta

import pytest
from test_app_analysis import HOUR, NOW, _window

from quant.app import analysis
from quant.features.engine import FEATURES


def _atr_window(count=15, *, changes=None):
    boundary = NOW.replace(minute=0, second=0, microsecond=0)
    rows = [
        {
            "timestamp": boundary - (count - index) * HOUR,
            "ingested_at": NOW,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 10.0,
        }
        for index in range(count)
    ]
    for index, values in (changes or {}).items():
        rows[index].update(values)
    return analysis.MarketWindow(tuple(rows), NOW)


def test_exact_first_wilder_seed_requires_fourteen_previous_close_true_ranges():
    window = _atr_window()
    assert analysis.calculate_atr(window) == 2.0
    assert analysis.calculate_atr(window) == analysis.calculate_atr(window)


@pytest.mark.parametrize("jump,high,low", [(111.0, 112.0, 110.0), (89.0, 90.0, 88.0)])
def test_true_range_includes_price_jumps_between_consecutive_hours(jump, high, low):
    changes = {
        index: {"open": jump, "high": high, "low": low, "close": jump}
        for index in range(1, 15)
    }
    # The first jump spans 12 price units; later true ranges are 2.
    expected = math.fsum([12.0, *([2.0] * 13)]) / 14
    assert analysis.calculate_atr(_atr_window(changes=changes)) == pytest.approx(
        expected, rel=1e-14
    )


def test_wilder_recurrence_after_seed_differs_from_simple_rolling_average():
    window = _atr_window(17, changes={15: {"high": 109.0, "low": 91.0}})
    first = (2.0 * 13 + 18.0) / 14
    expected = (first * 13 + 2.0) / 14
    assert analysis.calculate_atr(window) == pytest.approx(expected, rel=1e-14)
    assert expected != math.fsum([18.0, *([2.0] * 13)]) / 14


@pytest.mark.parametrize("count", [0, 1, 14])
def test_insufficient_atr_history_is_rejected(count):
    with pytest.raises(analysis.MarketDataError):
        analysis.calculate_atr(_atr_window(count))


@pytest.mark.parametrize(
    "defect", ["gap", "duplicate", "out_of_order", "stale", "incomplete", "future"]
)
def test_atr_requires_exact_consecutive_completed_latest_hours(defect):
    window = _atr_window(17)
    rows = [dict(row) for row in window.observations]
    if defect == "gap":
        del rows[5]
    elif defect == "duplicate":
        rows[5] = dict(rows[4])
    elif defect == "out_of_order":
        rows[4], rows[5] = rows[5], rows[4]
    elif defect == "stale":
        for row in rows:
            row["timestamp"] -= HOUR
    elif defect == "incomplete":
        rows[-1]["timestamp"] += HOUR
    else:
        rows.append({**rows[-1], "timestamp": rows[-1]["timestamp"] + HOUR})
    with pytest.raises(analysis.MarketDataError):
        analysis.calculate_atr(replace(window, observations=tuple(rows)))


@pytest.mark.parametrize(
    "changes",
    [
        {"high": None},
        {"close": math.nan},
        {"high": math.inf},
        {"volume": -1.0},
        {"open": True},
        {"low": 102.0},
        {"close": 0.0},
        {"timestamp": NOW.replace(tzinfo=None)},
        {"timestamp": NOW.replace(hour=9, minute=0, second=1)},
        {"ingested_at": NOW + timedelta(microseconds=1)},
        {"ingested_at": NOW.replace(hour=9, minute=59, second=59)},
    ],
)
def test_invalid_ohlcv_or_observation_metadata_cannot_produce_atr(changes):
    with pytest.raises(analysis.MarketDataError):
        analysis.calculate_atr(_atr_window(changes={14: changes}))


def test_missing_required_ohlcv_field_is_rejected():
    window = _atr_window()
    rows = [dict(row) for row in window.observations]
    del rows[-1]["high"]
    with pytest.raises(analysis.MarketDataError):
        analysis.calculate_atr(replace(window, observations=tuple(rows)))


def test_zero_atr_is_not_used_for_zero_distance_levels():
    changes = {index: {"high": 100.0, "low": 100.0} for index in range(15)}
    with pytest.raises(analysis.MarketDataError):
        analysis.calculate_atr(_atr_window(changes=changes))


def test_future_candle_prices_are_not_read_before_closure_rejection():
    window = _atr_window()

    class FutureCandle(dict):
        def __getitem__(self, name):
            if name in {"open", "high", "low", "close", "volume"}:
                raise AssertionError("Incomplete candle values entered ATR")
            return super().__getitem__(name)

    future = FutureCandle(window.observations[-1])
    future["timestamp"] += HOUR
    with pytest.raises(analysis.MarketDataError):
        analysis.calculate_atr(
            replace(window, observations=(*window.observations, future))
        )


def test_representable_seed_mean_does_not_overflow_from_intermediate_sum():
    changes = {
        index: {"open": 5e307, "high": 1e308, "low": 1.0, "close": 5e307}
        for index in range(15)
    }
    assert analysis.calculate_atr(_atr_window(changes=changes)) == pytest.approx(
        1e308, rel=1e-14
    )


@pytest.mark.parametrize(
    "decision,stop_loss,take_profit", [("BUY", 97.0, 106.0), ("SELL", 103.0, 94.0)]
)
def test_reference_levels_have_exact_one_to_two_risk_reward(
    decision, stop_loss, take_profit
):
    levels = analysis.reference_levels(decision, entry=100.0, atr=2.0)
    assert levels["entry"] == 100.0
    assert levels["stop_loss"] == stop_loss
    assert levels["take_profit"] == take_profit
    assert abs(levels["take_profit"] - levels["entry"]) == 2 * abs(
        levels["entry"] - levels["stop_loss"]
    )
    assert levels["risk_reward"] == "1:2"
    assert levels["currency"] == "USDT"
    assert levels["atr_period"] == 14
    assert levels["atr_method"] == "Wilder RMA"
    assert "Binance" in str(levels)
    assert "Exness" in str(levels)
    assert "position_size" not in levels


def test_hold_has_no_entry_stop_or_target_levels():
    assert analysis.reference_levels("HOLD", entry=100.0, atr=2.0) is None


@pytest.mark.parametrize(
    "entry,atr",
    [
        (0.0, 2.0),
        (-1.0, 2.0),
        (100.0, 0.0),
        (100.0, -1.0),
        (math.nan, 2.0),
        (100.0, math.inf),
        (True, 2.0),
        (100.0, None),
        (1.0, 1.0),
        (1e308, 1e308),
        (1e16, 2.0),  # Distinct float prices would give risk 4 and reward 6.
    ],
)
@pytest.mark.parametrize("decision", ["BUY", "SELL"])
def test_invalid_or_nonpositive_reference_levels_fail_closed(decision, entry, atr):
    with pytest.raises(analysis.MarketDataError):
        analysis.reference_levels(decision, entry=entry, atr=atr)


def test_unknown_direction_cannot_produce_reference_levels():
    with pytest.raises(analysis.MarketDataError):
        analysis.reference_levels("MAYBE", entry=100.0, atr=2.0)


@pytest.mark.parametrize(
    "growth,expected", [(1.001, "BUY"), (0.999, "SELL"), (1.0, "HOLD")]
)
def test_atr_reference_levels_do_not_change_existing_directional_strategy(
    growth, expected
):
    payload = analysis.build_analysis(_window(growth=growth))
    assert payload["decision"] == expected
    assert payload["actionable"] is False
    assert tuple(payload["indicators"]) == tuple(FEATURES)
    assert payload["atr_14"] > 0
    assert payload["atr_method"] == "Wilder RMA (14)"
    if expected == "HOLD":
        assert payload["reference_levels"] is None
        assert payload.get("entry_reference") is None
    else:
        assert payload["reference_levels"]["entry"] > 0
    assert "position_size" not in payload


def test_failure_response_cannot_retain_prior_reference_levels():
    payload = analysis.failure_payload("Synthetic invalid candle")
    assert payload["decision"] == "HOLD"
    assert payload["actionable"] is False
    assert payload.get("reference_levels") is None
    assert payload.get("entry_reference") is None


def test_atr_is_in_memory_and_independent_of_feature_engine_or_market_calls(
    monkeypatch,
):
    from pathlib import Path

    import polars as pl

    def forbidden(*args, **kwargs):
        pytest.fail("ATR attempted external data access or changed feature computation")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(pl, "read_parquet", forbidden)
    monkeypatch.setattr(analysis, "fetch_recent_market", forbidden)
    monkeypatch.setattr(analysis, "prepare_shared_features", forbidden)
    assert analysis.calculate_atr(_atr_window()) == 2.0
