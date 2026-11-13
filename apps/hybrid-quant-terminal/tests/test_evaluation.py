from copy import deepcopy
from datetime import datetime, time, timedelta

import pytest

from mt5_market_data.backtest import Assumptions, simulate, size_lots
from mt5_market_data.indicators import ADX, ATR, EMA, Donchian, IndicatorConfig
from mt5_market_data.market import check_alignment
from mt5_market_data.strategies import generate_decisions

T = datetime(2024, 1, 2, 8)


def bar(t, *, opening=100.0, high=101.0, low=99.0, close=100.0):
    return {"timestamp": t, "open": opening, "high": high, "low": low, "close": close}


def signal(b, decision="WAIT", atr=2.0):
    return {
        "bar_open": b["timestamp"],
        "decision_at": b["timestamp"] + timedelta(minutes=15),
        "decision": decision,
        "reason": "synthetic",
        "atr": atr,
    }


def assumptions(**changes):
    args = {
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
        "session_end": time(9),
        "spec_policy": "illustrative",  # Pure historical fill fixtures, not broker approval.
    }
    args.update(changes)
    return Assumptions(**args)


def test_ema_sma_seed_and_recursive_update():
    ema = EMA(3)
    assert [ema.update(x) for x in (1, 2, 3, 4)] == [None, None, 2, 3]


def test_atr_wilder_seed_and_recursion():
    atr = ATR(3)
    assert atr.update(11, 9, 10) is None
    assert atr.update(12, 9, 11) is None
    assert atr.update(13, 10, 12) == pytest.approx(8 / 3)
    assert atr.update(15, 11, 14) == pytest.approx((2 * (8 / 3) + 4) / 3)


def test_adx_increasing_trend_and_warmup():
    adx = ADX(3)
    values = [adx.update(11 + i, 9 + i, 10 + i) for i in range(7)]
    assert values[:5] == [None] * 5
    assert values[5:] == [100, 100]


def test_donchian_uses_only_previous_bars():
    channel = Donchian(2)
    assert channel.update(10, 5) is None
    assert channel.update(12, 6) is None
    assert channel.update(100, 1) == (12, 5)
    assert channel.update(15, 7) == (100, 1)


def test_higher_candle_requires_all_m15_and_matching_values():
    parts = [bar(T + timedelta(minutes=15 * i)) for i in range(4)]
    higher = [bar(T)]
    checks, summary = check_alignment(parts, higher, "H1")
    assert checks[T] == "matched" and summary["matched"] == 1
    assert check_alignment(parts[:-1], higher, "H1")[0][T] == "missing_m15"
    higher[0]["high"] = 102
    assert check_alignment(parts, higher, "H1")[0][T] == "ohlc_mismatch"


def test_exact_next_bar_execution_and_costs():
    bars = [bar(T + timedelta(minutes=15 * i)) for i in range(4)]
    decisions = [signal(x, "BUY" if i == 0 else "WAIT") for i, x in enumerate(bars)]
    result = simulate(
        bars, decisions, assumptions(), start=T, end=T + timedelta(hours=1)
    )
    trade = result["trades"][0]
    assert trade["entry_at"] == T + timedelta(minutes=15)
    assert trade["entry"] == pytest.approx(100.03)
    assert trade["exit"] == pytest.approx(99.99)
    assert trade["reason"] == "period_end"
    assert trade["nominal_stop_risk_usd"] <= trade["risk_budget_usd"]
    assert trade["risk_budget_usd"] == pytest.approx(100)
    assert trade["net_pnl_usd"] == pytest.approx(-((0.04 * 100) + 2) * trade["lots"])
    assert trade["estimated_cost_usd"] == pytest.approx(
        ((0.02 + 0.02) * 100 + 2) * trade["lots"]
    )


def test_sell_spread_and_slippage_costs():
    bars = [bar(T + timedelta(minutes=15 * i)) for i in range(4)]
    decisions = [signal(x, "SELL" if i == 0 else "WAIT") for i, x in enumerate(bars)]
    trade = simulate(
        bars, decisions, assumptions(), start=T, end=T + timedelta(hours=1)
    )["trades"][0]
    assert trade["entry"] == pytest.approx(99.99)
    assert trade["exit"] == pytest.approx(100.03)
    assert trade["net_pnl_usd"] < 0


def test_lot_rounding_and_risk_limits():
    a = assumptions()
    lots, reason = size_lots(10000, 100, 3, a)
    assert reason == "accepted" and lots == 0.33
    assert lots * ((3 + a.slip) * 100 + a.commission_usd_per_lot_roundtrip) <= 100
    assert size_lots(1, 100, 100, a)[1] == "below_minimum_lot"
    assert size_lots(10000, 100, 3, assumptions(max_lot=0.1))[1] == "above_maximum_lot"
    assert (
        size_lots(10000, 100, 3, assumptions(max_notional_usd=1))[1]
        == "above_maximum_notional"
    )


def test_stop_trigger_and_gap_open_slippage():
    bars = [bar(T), bar(T + timedelta(minutes=15), low=95)]
    decisions = [signal(bars[0], "BUY"), signal(bars[1])]
    result = simulate(
        bars, decisions, assumptions(), start=T, end=T + timedelta(minutes=30)
    )
    trade = result["trades"][0]
    assert trade["reason"] == "stop"
    assert trade["stop"] == pytest.approx(97.03)
    assert trade["exit"] == pytest.approx(97.02)
    bars = [
        bar(T),
        bar(T + timedelta(minutes=15)),
        bar(T + timedelta(minutes=30), opening=96, low=95),
    ]
    trade = simulate(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])],
        assumptions(),
        start=T,
        end=T + timedelta(minutes=45),
    )["trades"][0]
    assert trade["exit"] == pytest.approx(95.99)


def test_missing_next_bar_cancels_entry():
    bars = [bar(T), bar(T + timedelta(minutes=30))]
    result = simulate(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1])],
        assumptions(),
        start=T,
        end=T + timedelta(hours=1),
    )
    assert result["closed_trade_count"] == 0
    assert result["rejections"]["next_bar_missing"] == 1


def test_holding_gap_marks_unresolved_and_hides_total_metrics():
    bars = [bar(T), bar(T + timedelta(minutes=15)), bar(T + timedelta(minutes=45))]
    result = simulate(
        bars,
        [signal(bars[0], "BUY"), signal(bars[1]), signal(bars[2])],
        assumptions(),
        start=T,
        end=T + timedelta(hours=1),
    )
    assert result["status"] == "unresolved"
    assert result["net_pnl_usd"] is None and result["max_drawdown_fraction"] is None
    assert result["unresolved"]["reason"] == "missing_holding_bar"


def test_daily_close_and_no_session_entry():
    bars = [bar(T + timedelta(minutes=15 * i)) for i in range(6)]
    result = simulate(
        bars,
        [signal(b, "BUY" if i in (0, 4) else "WAIT") for i, b in enumerate(bars)],
        assumptions(),
        start=T,
        end=T + timedelta(hours=2),
    )
    assert result["trades"][0]["reason"] == "configured_close"
    assert result["trades"][0]["exit_at"] == T + timedelta(hours=1)
    assert result["rejections"]["signal_outside_configured_session"] >= 1


def test_empty_period_and_bad_signal_fail_closed():
    result = simulate([], [], assumptions(), start=T, end=T + timedelta(hours=1))
    assert result["status"] == "no_data" and result["net_pnl_usd"] is None
    with pytest.raises(ValueError, match="positive ATR"):
        simulate(
            [bar(T)],
            [signal(bar(T), "BUY", float("nan"))],
            assumptions(),
            start=T,
            end=T + timedelta(hours=1),
        )


def test_missing_higher_context_waits_and_future_append_is_invariant():
    bars = [bar(T + timedelta(minutes=15 * i)) for i in range(12)]
    datasets = {"M15": bars, "H1": [], "H4": []}
    alignment = {"H1": {}, "H4": {}}
    config = IndicatorConfig(
        ema_fast=2, ema_slow=3, adx_period=2, atr_period=2, donchian_period=2
    )
    full = generate_decisions(datasets, alignment, "donchian", config)
    prefix = generate_decisions(
        {**datasets, "M15": bars[:8]}, alignment, "donchian", config
    )
    assert full[:8] == prefix
    assert all(x["decision"] == "WAIT" for x in full)
    assert "H1 missing" in full[-1]["reason"]
    changed = deepcopy(bars)
    changed[-1]["high"] = 1000
    assert (
        generate_decisions({**datasets, "M15": changed}, alignment, "donchian", config)[
            :-1
        ]
        == full[:-1]
    )


def test_repeated_simulation_is_deterministic():
    bars = [bar(T + timedelta(minutes=15 * i)) for i in range(4)]
    dec = [signal(b, "BUY" if i == 0 else "WAIT") for i, b in enumerate(bars)]
    a = simulate(bars, dec, assumptions(), start=T, end=T + timedelta(hours=1))
    b = simulate(bars, dec, assumptions(), start=T, end=T + timedelta(hours=1))
    assert a == b


def test_short_stop_uses_ask_high_and_adverse_slippage():
    bars = [bar(T), bar(T + timedelta(minutes=15), high=104)]
    result = simulate(
        bars,
        [signal(bars[0], "SELL"), signal(bars[1])],
        assumptions(),
        start=T,
        end=T + timedelta(minutes=30),
    )
    trade = result["trades"][0]
    assert trade["entry"] == pytest.approx(99.99)
    assert trade["stop"] == pytest.approx(102.99)
    assert trade["exit"] == pytest.approx(103.00)
    assert trade["reason"] == "stop"


def _trending_market(sign):
    start = datetime(2024, 1, 1)
    m15 = []
    for i in range(48):
        opening = 100 + sign * i * 0.1
        close = opening + sign * 0.08
        m15.append(
            bar(
                start + timedelta(minutes=15 * i),
                opening=opening,
                high=max(opening, close) + 0.01,
                low=min(opening, close) - 0.01,
                close=close,
            )
        )
    h1 = []
    for i in range(0, len(m15), 4):
        group = m15[i : i + 4]
        h1.append(
            bar(
                group[0]["timestamp"],
                opening=group[0]["open"],
                high=max(x["high"] for x in group),
                low=min(x["low"] for x in group),
                close=group[-1]["close"],
            )
        )
    alignment, _ = check_alignment(m15, h1, "H1")
    return {"M15": m15, "H1": h1, "H4": []}, {"H1": alignment, "H4": {}}


@pytest.mark.parametrize("sign,expected", [(1, "BUY"), (-1, "SELL")])
@pytest.mark.parametrize("strategy", ["ema", "donchian"])
def test_both_strategies_produce_directional_decisions_on_synthetic_trends(
    sign, expected, strategy
):
    datasets, alignments = _trending_market(sign)
    config = IndicatorConfig(
        ema_fast=2, ema_slow=3, adx_period=2, atr_period=2, donchian_period=2
    )
    decisions = generate_decisions(datasets, alignments, strategy, config)
    assert any(row["decision"] == expected for row in decisions)
    assert all(
        row["decision_at"] == row["bar_open"] + timedelta(minutes=15)
        for row in decisions
    )


def test_future_higher_timeframe_candles_cannot_change_past_decisions():
    datasets, alignments = _trending_market(1)
    config = IndicatorConfig(
        ema_fast=2, ema_slow=3, adx_period=2, atr_period=2, donchian_period=2
    )
    full = generate_decisions(datasets, alignments, "ema", config)
    prefix = {"M15": datasets["M15"][:32], "H1": datasets["H1"][:8], "H4": []}
    prior = generate_decisions(prefix, alignments, "ema", config)
    assert full[:32] == prior


def test_overnight_must_be_opted_into_and_cost_is_applied():
    start = datetime(2024, 1, 2, 23, 30)
    bars = [bar(start + timedelta(minutes=15 * i)) for i in range(4)]
    dec = [signal(b, "BUY" if i == 0 else "WAIT") for i, b in enumerate(bars)]
    cfg = assumptions(
        session_start=time(0),
        session_end=time(23, 45),
        allow_overnight=True,
        overnight_cost_usd_per_lot=3,
    )
    # The signal closes exactly at the session boundary and cannot create a new entry.
    assert (
        simulate(bars, dec, cfg, start=start, end=start + timedelta(hours=1))[
            "closed_trade_count"
        ]
        == 0
    )
    start = datetime(2024, 1, 2, 23, 15)
    bars = [bar(start + timedelta(minutes=15 * i)) for i in range(5)]
    dec = [signal(b, "BUY" if i == 0 else "WAIT") for i, b in enumerate(bars)]
    result = simulate(
        bars, dec, cfg, start=start, end=start + timedelta(hours=1, minutes=15)
    )
    assert result["trades"][0]["estimated_cost_usd"] > 0
    assert (
        result["trades"][0]["exit_at"].date() > result["trades"][0]["entry_at"].date()
    )


def test_m15_gap_restarts_atr_warmup():
    datasets, alignments = _trending_market(1)
    datasets["M15"].pop(20)
    config = IndicatorConfig(
        ema_fast=2, ema_slow=3, adx_period=2, atr_period=2, donchian_period=2
    )
    decisions = generate_decisions(datasets, alignments, "ema", config)
    after = decisions[20]
    assert after["atr"] is None
    assert after["decision"] == "WAIT"
    assert "ATR warming up" in after["reason"]


def test_training_and_evaluation_cash_are_independent():
    bars = [bar(T + timedelta(minutes=15 * i)) for i in range(8)]
    decisions = [
        signal(b, "BUY" if i in (0, 4) else "WAIT") for i, b in enumerate(bars)
    ]
    cfg = assumptions(session_end=time(12))
    training = simulate(bars, decisions, cfg, start=T, end=T + timedelta(hours=1))
    evaluation = simulate(
        bars, decisions, cfg, start=T + timedelta(hours=1), end=T + timedelta(hours=2)
    )
    assert training["closed_trade_count"] == evaluation["closed_trade_count"] == 1
    assert training["trades"][0]["lots"] == evaluation["trades"][0]["lots"]
    assert training["trades"][0]["exit_at"] <= evaluation["trades"][0]["decision_at"]


def test_backtest_requires_explicit_financial_assumptions():
    from mt5_market_data.evaluation import main

    with pytest.raises(SystemExit) as error:
        main(["backtest", "--symbol", "EURUSDm", "--strategy", "ema"])
    assert error.value.code == 2


def test_close_marked_drawdown_includes_estimated_exit_costs():
    bars = [bar(T + timedelta(minutes=15 * i)) for i in range(4)]
    decisions = [signal(b, "BUY" if i == 0 else "WAIT") for i, b in enumerate(bars)]
    result = simulate(
        bars, decisions, assumptions(), start=T, end=T + timedelta(hours=1)
    )
    loss = (0.04 * 100 + 2) * result["trades"][0]["lots"]
    assert result["net_pnl_usd"] == pytest.approx(-loss)
    assert result["max_drawdown_fraction"] == pytest.approx(loss / 10000)
