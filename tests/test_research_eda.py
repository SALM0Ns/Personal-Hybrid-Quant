"""Synthetic, offline contracts for gap-aware BTC hourly descriptive research."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

import polars as pl
import pytest

from quant.research.__main__ import run
from quant.research.eda import (
    HOUR,
    Candle,
    add_returns,
    add_rolling_volatility,
    audit_candles,
    autocorrelations,
    build_timeline,
    classify_regimes,
    describe,
    quantile,
    seasonality,
)

START = datetime(2021, 1, 1, tzinfo=UTC)


def candle(hour: int, close: float = 100.0, *, start: datetime = START) -> Candle:
    return Candle(
        timestamp=start + hour * HOUR,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=2.0,
    )


def analyze(candles: list[Candle], **flags) -> list:
    hours = build_timeline(candles, **flags)
    add_returns(hours)
    for window in (24, 168):
        add_rolling_volatility(hours, window)
    return hours


def test_consecutive_hour_returns_and_invalid_first() -> None:
    hours = analyze([candle(0, 100), candle(1, 110), candle(2, 121)])
    assert [hour.return_valid for hour in hours] == [False, True, True]
    assert hours[0].simple_return is None
    assert hours[1].simple_return == pytest.approx(0.1)
    assert hours[1].log_return == pytest.approx(math.log(1.1))
    assert hours[2].log_return == pytest.approx(math.log(1.1))


def test_missing_hour_breaks_returns_without_filling_ohlcv() -> None:
    hours = analyze(
        [candle(0, 100), candle(1, 110), candle(3, 130), candle(4, 143)],
        documented_gaps=frozenset({START + 2 * HOUR}),
    )
    assert len(hours) == 5
    assert hours[2].missing and hours[2].documented_gap
    assert hours[2].close is None and hours[2].log_return is None
    assert hours[3].log_return is None
    assert hours[4].log_return == pytest.approx(math.log(1.1))
    assert hours[1].segment_id != hours[3].segment_id


def test_rolling_windows_require_all_contiguous_returns() -> None:
    candles = [
        candle(hour, 100 + hour + (hour % 3) * 0.1)
        for hour in range(225)
        if hour != 170
    ]
    hours = analyze(candles)
    assert hours[23].rolling_vol_24 is None
    assert hours[24].rolling_vol_24 is not None
    assert hours[167].rolling_vol_168 is None
    assert hours[168].rolling_vol_168 is not None
    assert hours[170].missing
    assert hours[171].rolling_vol_24 is None
    assert hours[194].rolling_vol_24 is None
    assert hours[195].rolling_vol_24 is not None
    assert hours[224].rolling_vol_168 is None


@pytest.mark.parametrize("lag", (1, 2, 6, 12, 24, 48, 168))
def test_lag_pairs_never_span_internal_gaps(lag: int) -> None:
    # Both endpoints can have valid returns while the interval between them
    # contains a missing candle. Each uninterrupted segment contributes only
    # its own valid-return pairs at the requested elapsed-hour lag.
    missing = {190, 360}
    hours = analyze(
        [
            candle(hour, 100 + hour + (hour % 2) * 0.1)
            for hour in range(500)
            if hour not in missing
        ]
    )
    result = autocorrelations(hours, lags=(lag,))[0]
    return_lengths = (189, 168, 138)
    expected = sum(max(length - lag, 0) for length in return_lengths)
    assert result["lag_hours"] == lag
    assert result["pair_count"] == expected
    assert result["clean_endpoint_pair_count"] == expected


def test_documented_anomaly_flags_touch_both_adjacent_returns() -> None:
    start = datetime(2021, 4, 23, tzinfo=UTC)
    hours = analyze([candle(i, 100 + i, start=start) for i in range(4)])
    assert hours[1].archive_discrepancy
    assert hours[1].timestamp == datetime(2021, 4, 23, 1, tzinfo=UTC)
    assert hours[1].return_anomaly_involved
    assert hours[2].return_anomaly_involved
    assert hours[2].timestamp == datetime(2021, 4, 23, 2, tzinfo=UTC)
    assert not hours[3].return_anomaly_involved


@pytest.mark.parametrize(
    "short_open",
    (
        datetime(2021, 2, 11, 3, tzinfo=UTC),
        datetime(2021, 4, 25, 4, tzinfo=UTC),
        datetime(2021, 8, 13, 1, tzinfo=UTC),
        datetime(2023, 3, 24, 12, tzinfo=UTC),
    ),
)
def test_shortened_close_flags_prior_return_then_gap_breaks_next(
    short_open: datetime,
) -> None:
    start = short_open - HOUR
    hours = analyze([candle(hour, 100 + hour, start=start) for hour in (0, 1, 3, 4)])
    assert hours[1].shortened_close
    assert hours[1].return_valid and hours[1].return_anomaly_involved
    assert hours[2].missing and not hours[2].return_valid
    assert not hours[3].return_valid
    assert hours[4].return_valid and not hours[4].return_anomaly_involved


def test_utc_hour_and_weekday_seasonality() -> None:
    sunday = datetime(2021, 1, 3, 23, tzinfo=UTC)
    hours = analyze([candle(0, 100, start=sunday), candle(1, 110, start=sunday)])
    hour_groups = seasonality(hours, by="hour")
    weekday_groups = seasonality(hours, by="weekday")
    assert hour_groups[0]["count"] == 1
    assert hour_groups[23]["count"] == 0
    assert weekday_groups[0]["count"] == 1  # Monday UTC, not Sunday.
    assert weekday_groups[6]["count"] == 0


def test_regime_thresholds_are_retrospective_and_exclude_flagged_windows() -> None:
    candles = [candle(hour, 100 + hour * 0.2 + (hour % 7) * 0.3) for hour in range(220)]
    hours = analyze(candles, shortened_closes=frozenset({START + 200 * HOUR}))
    regimes = classify_regimes(hours)
    assert regimes["thresholds"] is not None
    eligible = [
        hour.rolling_vol_168
        for hour in hours
        if hour.rolling_vol_168 is not None and not hour.rolling_168_anomaly_involved
    ]
    assert regimes["thresholds"]["low_to_medium"] == pytest.approx(
        quantile(eligible, 1 / 3)
    )
    assert regimes["thresholds"]["medium_to_high"] == pytest.approx(
        quantile(eligible, 2 / 3)
    )
    assert "full-sample retrospective" in regimes["method"]
    assert hours[200].rolling_168_anomaly_involved
    assert hours[200].regime is None
    assert sum(regimes["counts"].values()) == sum(
        hour.regime is not None for hour in hours
    )


def test_validation_rejects_duplicate_non_utc_and_bad_ohlc() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        audit_candles([candle(0), candle(0)])
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        audit_candles([candle(0, start=datetime(2021, 1, 1))])
    with pytest.raises(ValueError, match="high is below"):
        audit_candles([Candle(START, 100, 99, 98, 100, 1)])


def test_distribution_uses_documented_sample_std_and_linear_quantiles() -> None:
    stats = describe([1.0, 2.0, 3.0, 4.0])
    assert stats["count"] == 4
    assert stats["mean"] == 2.5
    assert stats["std"] == pytest.approx(math.sqrt(5 / 3))
    assert stats["quantiles"]["q25"] == pytest.approx(1.75)
    assert stats["skewness"] == pytest.approx(0)


def test_reproducible_cli_artifacts_with_synthetic_silver(tmp_path) -> None:
    candles = [candle(hour, 100 + hour * 0.2 + (hour % 7) * 0.3) for hour in range(220)]
    silver = tmp_path / "BTC-USDT.parquet"
    pl.DataFrame(
        {
            "exchange": ["binance"] * len(candles),
            "symbol": ["BTC/USDT"] * len(candles),
            "timeframe": ["1h"] * len(candles),
            "timestamp": [item.timestamp for item in candles],
            "open": [item.open for item in candles],
            "high": [item.high for item in candles],
            "low": [item.low for item in candles],
            "close": [item.close for item in candles],
            "volume": [item.volume for item in candles],
            "ingested_at": [item.timestamp + HOUR for item in candles],
        }
    ).write_parquet(silver)
    output = tmp_path / "gold"
    report = tmp_path / "report.md"
    kwargs = {
        "silver_path": silver,
        "output_dir": output,
        "report_path": report,
        "now": START + 300 * HOUR,
    }
    first = run(**kwargs)
    digest_before = {
        path.relative_to(tmp_path).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in (output / "timeline.parquet", output / "results.json", report)
    }
    second = run(**kwargs)
    digest_after = {
        path.relative_to(tmp_path).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in (output / "timeline.parquet", output / "results.json", report)
    }
    assert first == second
    assert digest_before == digest_after
    assert first["dataset"]["sha256"] == hashlib.sha256(silver.read_bytes()).hexdigest()
    assert json.loads((output / "results.json").read_text()) == first
    assert len(list((output / "charts").glob("*.svg"))) == 9
    for chart in (output / "charts").glob("*.svg"):
        ElementTree.parse(chart)
    assert not list((output / "timeline.parquet").parent.glob("*.zip"))


def test_incomplete_last_candle_is_rejected_before_output(tmp_path) -> None:
    silver = tmp_path / "BTC-USDT.parquet"
    pl.DataFrame(
        {
            "exchange": ["binance"],
            "symbol": ["BTC/USDT"],
            "timeframe": ["1h"],
            "timestamp": [START],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1.0],
            "ingested_at": [START],
        }
    ).write_parquet(silver)
    output = tmp_path / "gold"
    with pytest.raises(ValueError, match="incomplete"):
        run(
            silver_path=silver,
            output_dir=output,
            report_path=tmp_path / "report.md",
            now=START + timedelta(minutes=30),
        )
    assert not output.exists()
