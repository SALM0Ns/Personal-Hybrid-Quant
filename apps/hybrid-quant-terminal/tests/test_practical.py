from datetime import datetime, time, timedelta

import pytest

from mt5_market_data.backtest import Assumptions, simulate

T = datetime(2024, 1, 2, 8)


def bar(i, opening=100.0, high=101.0, low=99.0, close=100.0):
    return {
        "timestamp": T + timedelta(minutes=15 * i),
        "open": opening,
        "high": high,
        "low": low,
        "close": close,
    }


def signal(b, decision="WAIT", atr=2.0):
    return {
        "bar_open": b["timestamp"],
        "decision_at": b["timestamp"] + timedelta(minutes=15),
        "decision": decision,
        "atr": atr,
    }


def config(**changes):
    values = {
        "symbol": "XAUUSDm",
        "initial_equity_usd": 10000,
        "risk_fraction": 0.01,
        "max_risk_fraction": 0.02,
        "max_lot": 10,
        "max_notional_usd": 1000000,
        "point_size": 0.01,
        "spread_points": 2,
        "slippage_points": 1,
        "commission_usd_per_lot_roundtrip": 2,
        "stop_atr": 1.5,
        "session_start": time(8),
        "session_end": time(10),
        "spec_policy": "illustrative",  # Fixtures intentionally omit broker evidence.
    }
    values.update(changes)
    return Assumptions(**values)


def run(bars, decisions, **changes):
    return simulate(
        bars, decisions, config(**changes), start=T, end=T + timedelta(hours=2)
    )


def test_both_intrabar_barriers_choose_stop_conservatively():
    bars = [bar(0), bar(1, high=110, low=90)]
    r = run(bars, [signal(bars[0], "BUY"), signal(bars[1])], exit_mode="take_profit")
    assert r["trades"][0]["reason"] == "stop"
    assert r["trades"][0]["exit"] == pytest.approx(97.02)


def test_gap_open_through_take_profit_takes_known_open_before_intrabar_stop():
    bars = [bar(0), bar(1), bar(2, opening=107, high=108, low=95, close=100)]
    r = run(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])],
        exit_mode="take_profit",
    )
    trade = r["trades"][0]
    assert trade["reason"] == "take_profit"
    assert trade["exit_at"] == bars[2]["timestamp"]
    assert trade["exit"] == pytest.approx(trade["take_profit"] - 0.01)


def test_short_intrabar_both_barriers_choose_stop():
    bars = [bar(0), bar(1, high=110, low=90)]
    r = run(bars, [signal(bars[0], "SELL"), signal(bars[1])], exit_mode="take_profit")
    assert r["trades"][0]["reason"] == "stop"
    assert r["trades"][0]["exit"] == pytest.approx(103.0)


def test_trailing_update_only_applies_on_following_bar():
    bars = [
        bar(0),
        bar(1, high=105, low=99, close=104),
        bar(2, opening=100, high=101, low=99, close=100),
    ]
    r = run(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])],
        exit_mode="trailing",
    )
    trade = r["trades"][0]
    assert trade["initial_stop"] == pytest.approx(97.03)
    assert trade["stop"] == pytest.approx(101)
    assert trade["exit_at"] == bars[2]["timestamp"]
    assert trade["exit"] == pytest.approx(99.99)


def test_reversal_decision_exits_next_open_not_current_bar():
    bars = [bar(0), bar(1), bar(2, opening=100.5)]
    r = run(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1], "SELL"), signal(bars[2])],
        exit_mode="reversal",
    )
    assert r["trades"][0]["reason"] == "reversal"
    assert r["trades"][0]["exit_at"] == bars[2]["timestamp"]
    assert r["trades"][0]["exit"] == pytest.approx(100.49)


def test_open_stop_precedes_pending_reversal():
    bars = [bar(0), bar(1), bar(2, opening=96, high=101, low=95)]
    r = run(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1], "SELL"), signal(bars[2])],
        exit_mode="reversal",
    )
    assert r["trades"][0]["reason"] == "stop"
    assert r["trades"][0]["exit_at"] == bars[2]["timestamp"]
    assert r["trades"][0]["exit"] == pytest.approx(95.99)


def test_missing_specs_strict_rejects_and_illustrative_stays_unverified():
    bars = [bar(0), bar(1), bar(2)]
    decisions = [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])]
    strict = run(bars, decisions, spec_policy="strict")
    assert strict["closed_trade_count"] == 0
    assert strict["rejections"]["missing_broker_specifications"] == 1
    assert strict["unverified_spec_candidates"] == 1
    hypothetical = simulate(
        bars,
        decisions,
        config(spec_policy="illustrative"),
        start=T,
        end=T + timedelta(minutes=45),
    )
    assert hypothetical["unverified_spec_candidates"] == 1
    assert hypothetical["broker_feasibility"] == "unverified"
    assert hypothetical["trades"][0]["broker_feasibility"] == "unverified"


def test_known_insufficient_margin_and_stop_distance_are_rejected():
    bars = [bar(0), bar(1)]
    decisions = [signal(bars[0], "BUY"), signal(bars[1])]
    r = run(
        bars,
        decisions,
        margin_per_lot_usd=1000,
        available_margin_usd=1,
        min_stop_distance_points=0,
    )
    assert r["rejections"]["insufficient_available_margin"] == 1
    r = run(
        bars,
        decisions,
        margin_per_lot_usd=1,
        available_margin_usd=100,
        min_stop_distance_points=500,
    )
    assert r["rejections"]["below_minimum_stop_distance"] == 1


def test_cost_attribution_reconciles_gross_to_net_without_double_counting():
    bars = [bar(0), bar(1), bar(2), bar(3)]
    r = simulate(
        bars,
        [signal(bars[0], "BUY"), *[signal(x) for x in bars[1:]]],
        config(),
        start=T,
        end=T + timedelta(hours=1),
    )
    t = r["trades"][0]
    total = sum(
        t[k]
        for k in (
            "spread_cost_usd",
            "slippage_cost_usd",
            "commission_usd",
            "financing_usd",
        )
    )
    assert t["gross_pnl_usd"] - total == pytest.approx(t["net_pnl_usd"])
    assert t["gross_pnl_usd"] == pytest.approx(0, abs=1e-9)
    assert r["gross_pnl_usd"] - r["spread_cost_usd"] - r["slippage_cost_usd"] - r[
        "commission_usd"
    ] - r["financing_usd"] == pytest.approx(r["net_pnl_usd"])


def test_unknown_gap_is_not_invented_as_scheduled_or_unexpected():
    bars = [bar(0), bar(2)]
    r = run(bars, [signal(bars[0]), signal(bars[1])])
    assert r["gap_classification"] == {
        "verified_scheduled": 0,
        "verified_unexpected": 0,
        "unknown": 1,
        "verified_calendar_available": False,
    }


def test_default_api_policy_rejects_missing_broker_specs():
    from dataclasses import replace

    cfg = replace(config(), spec_policy="strict")
    bars = [bar(0), bar(1), bar(2)]
    r = simulate(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])],
        cfg,
        start=T,
        end=T + timedelta(minutes=45),
    )
    assert r["closed_trade_count"] == 0
    assert r["rejections"]["missing_broker_specifications"] == 1


def test_small_account_never_raises_risk_to_force_minimum_lot():
    bars = [bar(0), bar(1), bar(2)]
    decisions = [signal(bars[0], "BUY", atr=1.0), signal(bars[1]), signal(bars[2])]
    result = simulate(
        bars,
        decisions,
        config(initial_equity_usd=105.57),
        start=T,
        end=T + timedelta(minutes=45),
    )
    assert result["rejections"]["below_minimum_lot"] == 1
    assert result["closed_trade_count"] == 0
    assert result["status"] == "no_trades"
    assert result["net_pnl_usd"] is None


def test_blocked_specs_do_not_report_false_zero_performance():
    bars = [bar(0), bar(1), bar(2)]
    r = simulate(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])],
        config(spec_policy="strict"),
        start=T,
        end=T + timedelta(minutes=45),
    )
    assert r["status"] == "blocked_missing_broker_specifications"
    assert r["net_pnl_usd"] is None and r["gross_pnl_usd"] is None
    assert r["max_drawdown_fraction"] is None


def test_supplied_margin_assumptions_never_claim_broker_verification():
    bars = [bar(0), bar(1), bar(2)]
    r = simulate(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])],
        config(
            spec_policy="strict",
            margin_per_lot_usd=1,
            available_margin_usd=100,
            min_stop_distance_points=0,
        ),
        start=T,
        end=T + timedelta(minutes=45),
    )
    assert r["closed_trade_count"] == 1
    assert r["trades"][0]["broker_feasibility"] == "unverified"


def test_unresolved_position_does_not_claim_total_costs():
    bars = [bar(0), bar(1), bar(3)]
    r = run(bars, [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])])
    assert r["status"] == "unresolved"
    assert r["spread_cost_usd"] is None and r["commission_usd"] is None
    assert r["closed_spread_cost_usd"] == 0
    assert r["unresolved"]["lots"] > 0
