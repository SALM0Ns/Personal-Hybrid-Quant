"""Gap-aware, descriptive BTC/USDT hourly research; never emits signals."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import NormalDist, fmean, median, stdev

import polars as pl

HOUR = timedelta(hours=1)
SILVER_RELATIVE_PATH = Path("data/silver/binance/1h/BTC-USDT.parquet")
ANOMALY_PROVENANCE = "docs/QNT-001B_VERIFICATION_REPORT.md"
DOCUMENTED_GAPS = frozenset(
    datetime.fromisoformat(value).replace(tzinfo=UTC)
    for value in (
        "2021-02-11 04:00",
        "2021-03-06 02:00",
        "2021-04-20 02:00",
        "2021-04-20 03:00",
        "2021-04-25 05:00",
        "2021-04-25 06:00",
        "2021-04-25 07:00",
        "2021-08-13 02:00",
        "2021-08-13 03:00",
        "2021-08-13 04:00",
        "2021-08-13 05:00",
        "2021-09-29 07:00",
        "2021-09-29 08:00",
        "2023-03-24 13:00",
    )
)
ARCHIVE_DISCREPANCIES = frozenset({datetime(2021, 4, 23, 1, tzinfo=UTC)})
SHORTENED_CLOSES = frozenset(
    {
        datetime(2021, 2, 11, 3, tzinfo=UTC),
        datetime(2021, 4, 25, 4, tzinfo=UTC),
        datetime(2021, 8, 13, 1, tzinfo=UTC),
        datetime(2023, 3, 24, 12, tzinfo=UTC),
    }
)
LAGS = (1, 2, 6, 12, 24, 48, 168)
QUANTILES = (0.01, 0.05, 0.25, 0.75, 0.95, 0.99)


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class Hour:
    timestamp: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    missing: bool
    documented_gap: bool
    archive_discrepancy: bool
    shortened_close: bool
    segment_id: int | None = None
    simple_return: float | None = None
    log_return: float | None = None
    return_valid: bool = False
    return_anomaly_involved: bool = False
    rolling_vol_24: float | None = None
    rolling_vol_168: float | None = None
    rolling_24_anomaly_involved: bool = False
    rolling_168_anomaly_involved: bool = False
    regime: str | None = None


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def load_silver(path: Path) -> tuple[list[Candle], dict[str, str], str]:
    """Read only the approved Silver file and validate its source identity."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    frame = pl.read_parquet(path)
    required = {
        "exchange",
        "symbol",
        "timeframe",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ingested_at",
    }
    if not required.issubset(frame.columns):
        raise ValueError(
            f"Silver schema is missing {sorted(required - set(frame.columns))}"
        )
    for column in ("timestamp", "ingested_at"):
        dtype = frame.schema[column]
        if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
            raise ValueError(f"{column} must be a timezone-aware UTC datetime")
    for column in ("open", "high", "low", "close", "volume"):
        if frame.schema[column] != pl.Float64:
            raise ValueError(f"{column} must be Float64")
    if frame.height == 0:
        raise ValueError("Silver file contains no candles")
    identity = frame.select(
        (pl.col("exchange") == "binance").all().alias("exchange"),
        (pl.col("symbol") == "BTC/USDT").all().alias("symbol"),
        (pl.col("timeframe") == "1h").all().alias("timeframe"),
    ).row(0)
    if identity != (True, True, True):
        raise ValueError(
            "Silver file contains an unexpected exchange, symbol, or timeframe"
        )
    if frame.null_count().select(pl.sum_horizontal(pl.all())).item() != 0:
        raise ValueError("Silver file contains null source fields")
    candles = [
        Candle(row[0], *row[1:])
        for row in frame.select(
            "timestamp", "open", "high", "low", "close", "volume"
        ).iter_rows()
    ]
    audit_candles(candles)
    return candles, {key: str(value) for key, value in frame.schema.items()}, digest


def audit_candles(candles: list[Candle]) -> None:
    """Reject ambiguous or invalid canonical observations before analysis."""
    if not candles:
        raise ValueError("at least one candle is required")
    previous: datetime | None = None
    for candle in candles:
        ts = candle.timestamp
        if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
            raise ValueError("all candle timestamps must be timezone-aware UTC")
        if ts.minute or ts.second or ts.microsecond:
            raise ValueError(f"candle is not hour-aligned: {_iso(ts)}")
        if previous is not None and ts <= previous:
            reason = "duplicate" if ts == previous else "out-of-order"
            raise ValueError(f"{reason} candle timestamp: {_iso(ts)}")
        values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"non-finite OHLCV at {_iso(ts)}")
        if min(values[:4]) <= 0 or candle.volume < 0:
            raise ValueError(f"invalid price or volume at {_iso(ts)}")
        if candle.high < max(candle.open, candle.low, candle.close):
            raise ValueError(f"high is below another price at {_iso(ts)}")
        if candle.low > min(candle.open, candle.high, candle.close):
            raise ValueError(f"low is above another price at {_iso(ts)}")
        previous = ts


def build_timeline(
    candles: list[Candle],
    *,
    documented_gaps: frozenset[datetime] = DOCUMENTED_GAPS,
    discrepancies: frozenset[datetime] = ARCHIVE_DISCREPANCIES,
    shortened_closes: frozenset[datetime] = SHORTENED_CLOSES,
) -> list[Hour]:
    """Represent every hour from first through last observed candle explicitly."""
    audit_candles(candles)
    by_timestamp = {candle.timestamp: candle for candle in candles}
    hours = []
    timestamp = candles[0].timestamp
    while timestamp <= candles[-1].timestamp:
        candle = by_timestamp.get(timestamp)
        hours.append(
            Hour(
                timestamp=timestamp,
                open=candle.open if candle else None,
                high=candle.high if candle else None,
                low=candle.low if candle else None,
                close=candle.close if candle else None,
                volume=candle.volume if candle else None,
                missing=candle is None,
                documented_gap=timestamp in documented_gaps,
                archive_discrepancy=timestamp in discrepancies,
                shortened_close=timestamp in shortened_closes,
            )
        )
        timestamp += HOUR
    return hours


def add_returns(hours: list[Hour]) -> None:
    """Compute returns only when both candle opens are one actual hour apart."""
    previous: Hour | None = None
    segment = 0
    for hour in hours:
        if hour.missing:
            previous = None
            continue
        if previous is None:
            segment += 1
        hour.segment_id = segment
        if previous is not None and hour.timestamp - previous.timestamp == HOUR:
            assert hour.close is not None and previous.close is not None
            ratio = hour.close / previous.close
            hour.simple_return = ratio - 1
            hour.log_return = math.log(ratio)
            hour.return_valid = True
            hour.return_anomaly_involved = any(
                (
                    hour.archive_discrepancy,
                    hour.shortened_close,
                    previous.archive_discrepancy,
                    previous.shortened_close,
                )
            )
        previous = hour


def add_rolling_volatility(hours: list[Hour], window: int) -> None:
    """Raw hourly sample std; a gap resets the complete-return window."""
    if window not in (24, 168):
        raise ValueError("supported windows are 24 and 168 hourly returns")
    values: deque[float] = deque()
    anomalies: deque[bool] = deque()
    total = squared = 0.0
    anomaly_count = 0
    for hour in hours:
        if not hour.return_valid:
            values.clear()
            anomalies.clear()
            total = squared = 0.0
            anomaly_count = 0
            continue
        assert hour.log_return is not None
        value = hour.log_return
        values.append(value)
        anomalies.append(hour.return_anomaly_involved)
        total += value
        squared += value * value
        anomaly_count += hour.return_anomaly_involved
        if len(values) > window:
            old = values.popleft()
            total -= old
            squared -= old * old
            anomaly_count -= anomalies.popleft()
        if len(values) == window:
            variance = max(0.0, (squared - total * total / window) / (window - 1))
            setattr(hour, f"rolling_vol_{window}", math.sqrt(variance))
            setattr(hour, f"rolling_{window}_anomaly_involved", anomaly_count > 0)


def quantile(values: list[float], probability: float) -> float:
    """Hyndman-Fan type 7 (linear interpolation), on a nonempty sample."""
    if not values or not 0 <= probability <= 1:
        raise ValueError("quantile requires data and a probability in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def describe(values: list[float]) -> dict:
    """Sample std (n-1); population-standardized skew and excess kurtosis."""
    if not values:
        return {"count": 0}
    count = len(values)
    mean = fmean(values)
    centered = [value - mean for value in values]
    second = math.fsum(value * value for value in centered) / count
    third = math.fsum(value**3 for value in centered) / count
    fourth = math.fsum(value**4 for value in centered) / count
    return {
        "count": count,
        "mean": mean,
        "median": median(values),
        "std": stdev(values) if count > 1 else None,
        "min": min(values),
        "max": max(values),
        "skewness": third / second**1.5 if second > 0 else None,
        "excess_kurtosis": fourth / second**2 - 3 if second > 0 else None,
        "quantiles": {f"q{int(p * 100):02d}": quantile(values, p) for p in QUANTILES},
    }


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    x_mean = fmean(left for left, _ in pairs)
    y_mean = fmean(right for _, right in pairs)
    numerator = math.fsum((x - x_mean) * (y - y_mean) for x, y in pairs)
    x_square = math.fsum((x - x_mean) ** 2 for x, _ in pairs)
    y_square = math.fsum((y - y_mean) ** 2 for _, y in pairs)
    return numerator / math.sqrt(x_square * y_square) if x_square * y_square else None


def autocorrelations(hours: list[Hour], lags: tuple[int, ...] = LAGS) -> list[dict]:
    """Pair elapsed-hour lags only within uninterrupted observed segments."""
    result = []
    for lag in lags:
        pairs = []
        clean_pairs = []
        for index in range(lag, len(hours)):
            current, earlier = hours[index], hours[index - lag]
            if (
                not current.return_valid
                or not earlier.return_valid
                or current.segment_id != earlier.segment_id
                or current.timestamp - earlier.timestamp != lag * HOUR
            ):
                continue
            assert current.log_return is not None and earlier.log_return is not None
            pair = (current.log_return, earlier.log_return)
            pairs.append(pair)
            if (
                not current.return_anomaly_involved
                and not earlier.return_anomaly_involved
            ):
                clean_pairs.append(pair)
        result.append(
            {
                "lag_hours": lag,
                "pair_count": len(pairs),
                "log_return_acf": _pearson(pairs),
                "absolute_log_return_acf": _pearson(
                    [(abs(x), abs(y)) for x, y in pairs]
                ),
                "clean_endpoint_pair_count": len(clean_pairs),
                "clean_log_return_acf": _pearson(clean_pairs),
                "clean_absolute_log_return_acf": _pearson(
                    [(abs(x), abs(y)) for x, y in clean_pairs]
                ),
            }
        )
    return result


def seasonality(hours: list[Hour], *, by: str) -> list[dict]:
    """UTC hour-of-day or Monday=0 day-of-week, using valid log returns."""
    if by not in ("hour", "weekday"):
        raise ValueError("seasonality grouping must be hour or weekday")
    groups: dict[int, list[Hour]] = defaultdict(list)
    for hour in hours:
        if hour.return_valid:
            key = hour.timestamp.hour if by == "hour" else hour.timestamp.weekday()
            groups[key].append(hour)
    result = []
    for key in range(24 if by == "hour" else 7):
        rows = groups[key]
        values = [row.log_return for row in rows if row.log_return is not None]
        result.append(
            {
                by: key,
                "count": len(values),
                "mean_log_return": fmean(values) if values else None,
                "median_log_return": median(values) if values else None,
                "std_log_return": stdev(values) if len(values) > 1 else None,
                "mean_absolute_log_return": fmean(map(abs, values)) if values else None,
                "anomaly_involved_count": sum(
                    row.return_anomaly_involved for row in rows
                ),
            }
        )
    return result


def classify_regimes(hours: list[Hour]) -> dict:
    """Retrospective tertiles of clean 168-return rolling volatility only."""
    clean = [
        hour.rolling_vol_168
        for hour in hours
        if hour.rolling_vol_168 is not None and not hour.rolling_168_anomaly_involved
    ]
    if not clean:
        return {"thresholds": None, "counts": {}, "yearly_counts": []}
    low = quantile(clean, 1 / 3)
    high = quantile(clean, 2 / 3)
    counts = {"low": 0, "medium": 0, "high": 0}
    yearly: dict[int, dict[str, int]] = defaultdict(
        lambda: {"low": 0, "medium": 0, "high": 0}
    )
    for hour in hours:
        value = hour.rolling_vol_168
        if value is None or hour.rolling_168_anomaly_involved:
            continue
        hour.regime = "low" if value <= low else "medium" if value <= high else "high"
        counts[hour.regime] += 1
        yearly[hour.timestamp.year][hour.regime] += 1
    return {
        "thresholds": {"low_to_medium": low, "medium_to_high": high},
        "counts": counts,
        "yearly_counts": [{"year": year, **yearly[year]} for year in sorted(yearly)],
        "unclassified_hour_count": sum(hour.regime is None for hour in hours),
        "method": (
            "full-sample retrospective tertiles of anomaly-free 168-return windows"
        ),
    }


def summarize(hours: list[Hour], *, schema: dict[str, str], sha256: str) -> dict:
    """Build deterministic machine-readable aggregates from the full timeline."""
    missing = [hour for hour in hours if hour.missing]
    valid = [hour for hour in hours if hour.return_valid]
    clean = [hour for hour in valid if not hour.return_anomaly_involved]
    simple = [hour.simple_return for hour in valid if hour.simple_return is not None]
    log = [hour.log_return for hour in valid if hour.log_return is not None]
    clean_log = [hour.log_return for hour in clean if hour.log_return is not None]
    distribution = {
        "simple_return": describe(simple),
        "log_return": describe(log),
        "clean_log_return": describe(clean_log),
    }
    log_stats = distribution["log_return"]
    mean, std = log_stats["mean"], log_stats["std"]
    observed_three_sigma = (
        sum(abs(value - mean) > 3 * std for value in log) / len(log)
        if std is not None
        else None
    )
    volatility = {}
    for window in (24, 168):
        rows = [
            hour for hour in hours if getattr(hour, f"rolling_vol_{window}") is not None
        ]
        clean_rows = [
            hour
            for hour in rows
            if not getattr(hour, f"rolling_{window}_anomaly_involved")
        ]
        volatility[str(window)] = {
            "valid_window_count": len(rows),
            "anomaly_involved_window_count": len(rows) - len(clean_rows),
            "clean_window_count": len(clean_rows),
            "raw_hourly_sample_std": describe(
                [getattr(hour, f"rolling_vol_{window}") for hour in rows]
            ),
        }
    return {
        "dataset": {
            "source": SILVER_RELATIVE_PATH.as_posix(),
            "sha256": sha256,
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "schema": schema,
            "first_observed_utc": _iso(hours[0].timestamp),
            "last_observed_utc": _iso(hours[-1].timestamp),
            "interval_convention": (
                "inclusive candle opens; end-exclusive boundary is last + 1h"
            ),
            "end_exclusive_utc": _iso(hours[-1].timestamp + HOUR),
            "expected_hour_count": len(hours),
            "observed_candle_count": len(hours) - len(missing),
            "missing_hour_count": len(missing),
            "gap_period_count": sum(
                hour.missing and (index == 0 or not hours[index - 1].missing)
                for index, hour in enumerate(hours)
            ),
            "missing_timestamps_utc": [_iso(hour.timestamp) for hour in missing],
            "documented_missing_count": sum(hour.documented_gap for hour in missing),
            "unexpected_missing_count": sum(
                not hour.documented_gap for hour in missing
            ),
            "documented_gap_now_observed_count": sum(
                hour.documented_gap and not hour.missing for hour in hours
            ),
            "duplicate_count": 0,
            "out_of_order_count": 0,
            "hour_misalignment_count": 0,
            "ohlc_invalid_count": 0,
            "nonpositive_price_count": 0,
            "negative_volume_count": 0,
            "archive_discrepancy_observation_count": sum(
                hour.archive_discrepancy and not hour.missing for hour in hours
            ),
            "shortened_close_observation_count": sum(
                hour.shortened_close and not hour.missing for hour in hours
            ),
            "anomaly_provenance": ANOMALY_PROVENANCE,
        },
        "returns": {
            "valid_count": len(valid),
            "invalid_observed_count": sum(
                not hour.missing and not hour.return_valid for hour in hours
            ),
            "invalid_timeline_hour_count": len(hours) - len(valid),
            "anomaly_involved_count": len(valid) - len(clean),
            "clean_count": len(clean),
        },
        "distribution": distribution,
        "heavy_tail_comparison": {
            "observed_beyond_three_sample_std_fraction": observed_three_sigma,
            "normal_beyond_three_std_fraction": 2 * (1 - NormalDist().cdf(3)),
            "benchmark": "matched-normal three-sigma exceedance; descriptive only",
        },
        "volatility": volatility,
        "autocorrelation": autocorrelations(hours),
        "seasonality": {
            "utc_hour": seasonality(hours, by="hour"),
            "utc_weekday_monday_zero": seasonality(hours, by="weekday"),
        },
        "regimes": classify_regimes(hours),
        "conventions": {
            "std": "sample standard deviation, n-1 denominator",
            "skewness": (
                "third central moment / second central moment^(3/2), n denominator"
            ),
            "excess_kurtosis": (
                "fourth central moment / second central moment^2 - 3, n denominator"
            ),
            "quantiles": "Hyndman-Fan type 7 linear interpolation",
            "autocorrelation": (
                "pairwise Pearson correlation, centered within each eligible "
                "lag-pair sample"
            ),
            "rolling_volatility": (
                "raw hourly sample std of 24 or 168 consecutive one-hour "
                "log returns; not annualized"
            ),
            "regimes": "retrospective full-sample tertiles; not point-in-time signals",
        },
    }


def timeline_frame(hours: list[Hour]) -> pl.DataFrame:
    """Materialize analysis-only Gold rows; missing OHLCV remain null."""
    return pl.DataFrame([asdict(hour) for hour in hours], infer_schema_length=None)
