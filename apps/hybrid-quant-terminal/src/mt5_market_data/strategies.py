"""Deterministic historical bar-close decisions; no execution or network APIs."""

from __future__ import annotations

from bisect import bisect_right
from datetime import timedelta

from .indicators import ADX, ATR, EMA, Donchian, IndicatorConfig

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H4 = timedelta(hours=4)


def _higher_indicators(bars, alignment, step, config):
    fast, slow, adx = EMA(config.ema_fast), EMA(config.ema_slow), ADX(config.adx_period)
    result = {}
    previous = None
    for bar in bars:
        t = bar["timestamp"]
        valid = alignment.get(t) == "matched"
        if not valid or (previous is not None and t - previous != step):
            fast, slow, adx = (
                EMA(config.ema_fast),
                EMA(config.ema_slow),
                ADX(config.adx_period),
            )
        if not valid:
            result[t] = None
        else:
            result[t] = {
                "ema_fast": fast.update(bar["close"]),
                "ema_slow": slow.update(bar["close"]),
                "adx": adx.update(bar["high"], bar["low"], bar["close"]),
                "close": bar["close"],
            }
        previous = t if valid else None
    return result


def generate_decisions(datasets, alignments, strategy: str, config: IndicatorConfig):
    if strategy not in {"ema", "donchian"}:
        raise ValueError("strategy must be ema or donchian")
    h1 = _higher_indicators(datasets["H1"], alignments["H1"], H1, config)
    h4 = (
        _higher_indicators(datasets["H4"], alignments["H4"], H4, config)
        if config.h4_confirm
        else {}
    )
    h4_times = sorted(h4)
    fast, atr, channel = (
        EMA(config.ema_fast),
        ATR(config.atr_period),
        Donchian(config.donchian_period),
    )
    previous = None
    result = []
    for bar in datasets["M15"]:
        t, at = bar["timestamp"], bar["timestamp"] + M15
        if previous is not None and t - previous != M15:
            fast, atr, channel = (
                EMA(config.ema_fast),
                ATR(config.atr_period),
                Donchian(config.donchian_period),
            )
        m15_ema = fast.update(bar["close"])
        atr_value = atr.update(bar["high"], bar["low"], bar["close"])
        bounds = channel.update(bar["high"], bar["low"])
        h1_open = at.replace(minute=0, second=0, microsecond=0) - H1
        context = h1.get(h1_open)
        reason, direction = "", "WAIT"
        if atr_value is None or atr_value <= 0:
            reason = "M15 ATR warming up or zero"
        elif context is None:
            reason = "H1 missing, incomplete, misaligned or unverified"
        elif context["ema_fast"] is None:
            reason = "H1 EMA warming up after gap"
        elif strategy == "ema" and (
            context["ema_slow"] is None or context["adx"] is None or m15_ema is None
        ):
            reason = "EMA/ADX warming up after gap"
        elif strategy == "donchian" and bounds is None:
            reason = "Donchian channel warming up after gap"
        else:
            if strategy == "ema":
                bull = (
                    context["ema_fast"] > context["ema_slow"]
                    and context["adx"] >= config.adx_threshold
                    and bar["close"] > m15_ema
                    and bar["close"] > bar["open"]
                )
                bear = (
                    context["ema_fast"] < context["ema_slow"]
                    and context["adx"] >= config.adx_threshold
                    and bar["close"] < m15_ema
                    and bar["close"] < bar["open"]
                )
            else:
                bull = (
                    bar["close"] > bounds[0] and context["close"] > context["ema_fast"]
                )
                bear = (
                    bar["close"] < bounds[1] and context["close"] < context["ema_fast"]
                )
            if config.h4_confirm and (bull or bear):
                index = bisect_right(h4_times, at - H4) - 1
                h4_t = h4_times[index] if index >= 0 else None
                broad = (
                    h4.get(h4_t) if h4_t is not None and at - (h4_t + H4) < H4 else None
                )
                if not broad or broad["ema_fast"] is None or broad["ema_slow"] is None:
                    bull = bear = False
                    reason = "H4 context unavailable or warming up"
                else:
                    bull = bull and broad["ema_fast"] > broad["ema_slow"]
                    bear = bear and broad["ema_fast"] < broad["ema_slow"]
            if bull or bear:
                direction = "BUY" if bull else "SELL"
                if strategy == "ema":
                    reason = (
                        "H1 EMA trend and ADX threshold align; M15 close is "
                        + ("above" if bull else "below")
                        + " its EMA and open"
                    )
                else:
                    reason = (
                        "M15 close breaks the previous Donchian "
                        + ("high" if bull else "low")
                        + "; H1 close agrees with its EMA direction"
                    )
                if config.h4_confirm:
                    reason += "; H4 EMA trend agrees"
            elif not reason:
                reason = (
                    "No entry: H1 trend/ADX and M15 confirmation do not align"
                    if strategy == "ema"
                    else "No entry: prior-channel breakout and H1 trend do not align"
                )
        result.append(
            {
                "bar_open": t,
                "decision_at": at,
                "decision": direction,
                "reason": reason,
                "atr": atr_value,
                "h1_open": h1_open,
                "h1_context": context,
                "donchian_prior": bounds,
                "m15_ema": m15_ema,
                "m15_open": bar["open"],
                "m15_close": bar["close"],
            }
        )
        previous = t
    return result
