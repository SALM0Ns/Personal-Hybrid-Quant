"""Incremental indicator primitives; callers reset on unverified gaps."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


def _require_finite(value: float) -> float:
    """Reject numeric overflow or nonfinite input rather than emit invalid analytics."""
    if not math.isfinite(value):
        raise ValueError("indicator input or calculation is nonfinite")
    return value


class EMA:
    def __init__(self, period: int):
        if period < 1:
            raise ValueError("EMA period must be positive")
        self.period = period
        self.seed: list[float] = []
        self.value: float | None = None

    def update(self, value: float) -> float | None:
        _require_finite(value)
        if self.value is None:
            self.seed.append(value)
            if len(self.seed) == self.period:
                self.value = sum(self.seed) / self.period
        else:
            self.value += 2.0 / (self.period + 1) * (value - self.value)
        if self.value is not None:
            _require_finite(self.value)
        return self.value


class ATR:
    def __init__(self, period: int):
        if period < 1:
            raise ValueError("ATR period must be positive")
        self.period = period
        self.previous_close: float | None = None
        self.seed: list[float] = []
        self.value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        for value in (high, low, close):
            _require_finite(value)
        tr = (
            high - low
            if self.previous_close is None
            else max(
                high - low,
                abs(high - self.previous_close),
                abs(low - self.previous_close),
            )
        )
        _require_finite(tr)
        self.previous_close = close
        if self.value is None:
            self.seed.append(tr)
            if len(self.seed) == self.period:
                self.value = sum(self.seed) / self.period
        else:
            self.value = (self.value * (self.period - 1) + tr) / self.period
        if self.value is not None:
            _require_finite(self.value)
        return self.value


class ADX:
    """Wilder-smoothed ADX; first bar supplies only previous OHLC."""

    def __init__(self, period: int):
        if period < 2:
            raise ValueError("ADX period must be at least two")
        self.period = period
        self.previous: tuple[float, float, float] | None = None
        self.trs: list[float] = []
        self.plus: list[float] = []
        self.minus: list[float] = []
        self.sums: tuple[float, float, float] | None = None
        self.dx: list[float] = []
        self.value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        for value in (high, low, close):
            _require_finite(value)
        previous = self.previous
        self.previous = (high, low, close)
        if previous is None:
            return None
        up, down = high - previous[0], previous[1] - low
        plus = up if up > down and up > 0 else 0.0
        minus = down if down > up and down > 0 else 0.0
        tr = max(high - low, abs(high - previous[2]), abs(low - previous[2]))
        for value in (plus, minus, tr):
            _require_finite(value)
        if self.sums is None:
            self.trs.append(tr)
            self.plus.append(plus)
            self.minus.append(minus)
            if len(self.trs) < self.period:
                return None
            self.sums = (sum(self.trs), sum(self.plus), sum(self.minus))
        else:
            self.sums = tuple(
                old - old / self.period + new
                for old, new in zip(self.sums, (tr, plus, minus))
            )
        tr_sum, plus_sum, minus_sum = self.sums
        for value in self.sums:
            _require_finite(value)
        positive = 100 * plus_sum / tr_sum if tr_sum else 0.0
        negative = 100 * minus_sum / tr_sum if tr_sum else 0.0
        _require_finite(positive)
        _require_finite(negative)
        total = _require_finite(positive + negative)
        dx = 100 * abs(positive - negative) / total if total else 0.0
        _require_finite(dx)
        if self.value is None:
            self.dx.append(dx)
            if len(self.dx) == self.period:
                self.value = sum(self.dx) / self.period
        else:
            self.value = (self.value * (self.period - 1) + dx) / self.period
        if self.value is not None:
            _require_finite(self.value)
        return self.value


class Donchian:
    """Return channel from prior bars, then add the current bar."""

    def __init__(self, period: int):
        if period < 1:
            raise ValueError("Donchian period must be positive")
        self.bars: deque[tuple[float, float]] = deque(maxlen=period)
        self.period = period

    def update(self, high: float, low: float) -> tuple[float, float] | None:
        channel = None
        if len(self.bars) == self.period:
            channel = (max(x[0] for x in self.bars), min(x[1] for x in self.bars))
        self.bars.append((high, low))
        return channel


@dataclass(frozen=True)
class IndicatorConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    adx_period: int = 14
    atr_period: int = 14
    donchian_period: int = 20
    adx_threshold: float = 20.0
    h4_confirm: bool = False

    def __post_init__(self):
        import math

        if not 1 <= self.ema_fast < self.ema_slow or self.adx_period < 2:
            raise ValueError("invalid EMA or ADX periods")
        if self.atr_period < 1 or self.donchian_period < 1:
            raise ValueError("invalid ATR or Donchian period")
        if not math.isfinite(self.adx_threshold) or not 0 <= self.adx_threshold <= 100:
            raise ValueError("ADX threshold must be between 0 and 100")
