"""Deterministic Markdown and CSV summaries of descriptive EDA results."""

# ruff: noqa: E501
# Long lines inside the Markdown template preserve readable generated prose.

from __future__ import annotations

import csv
from pathlib import Path


def _number(value: float | int | None, precision: int = 6) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.{precision}g}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def _csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_tables(summary: dict, directory: Path) -> list[str]:
    """Local aggregate tables, never raw market observations."""
    directory.mkdir(parents=True, exist_ok=True)
    distribution = []
    for name, stats in summary["distribution"].items():
        distribution.append(
            {
                "series": name,
                **{key: value for key, value in stats.items() if key != "quantiles"},
                **stats["quantiles"],
            }
        )
    tables = {
        "return_distribution.csv": distribution,
        "autocorrelation.csv": summary["autocorrelation"],
        "utc_hour_seasonality.csv": summary["seasonality"]["utc_hour"],
        "utc_weekday_seasonality.csv": summary["seasonality"][
            "utc_weekday_monday_zero"
        ],
        "regime_yearly_counts.csv": summary["regimes"]["yearly_counts"],
        "volatility.csv": [
            {
                "window_returns": int(window),
                "valid_window_count": details["valid_window_count"],
                "anomaly_involved_window_count": details[
                    "anomaly_involved_window_count"
                ],
                "clean_window_count": details["clean_window_count"],
                "median_raw_hourly_std": details["raw_hourly_sample_std"].get("median"),
                "max_raw_hourly_std": details["raw_hourly_sample_std"].get("max"),
            }
            for window, details in summary["volatility"].items()
        ],
        "missing_hours.csv": [
            {"timestamp_utc": timestamp}
            for timestamp in summary["dataset"]["missing_timestamps_utc"]
        ],
    }
    for filename, rows in sorted(tables.items()):
        _csv(directory / filename, rows)
    return sorted(tables)


def render_report(summary: dict, chart_files: list[str], table_files: list[str]) -> str:
    """Generate a reviewable report with no row-level market data or private paths."""
    dataset = summary["dataset"]
    returns = summary["returns"]
    distributions = summary["distribution"]
    volatility = summary["volatility"]
    acf = summary["autocorrelation"]
    regimes = summary["regimes"]
    data_dir = "data/gold/qnt-002a/btc_usdt_1h"
    distribution_rows = [
        [
            label,
            _number(stats["count"]),
            _number(stats["mean"]),
            _number(stats["median"]),
            _number(stats["std"]),
            _number(stats["min"]),
            _number(stats["max"]),
            _number(stats["skewness"]),
            _number(stats["excess_kurtosis"]),
        ]
        for label, stats in distributions.items()
    ]
    quantile_rows = [
        [
            label,
            *(_number(stats["quantiles"][f"q{p:02d}"]) for p in (1, 5, 25, 75, 95, 99)),
        ]
        for label, stats in distributions.items()
    ]
    volatility_rows = [
        [
            window,
            _number(details["valid_window_count"]),
            _number(details["anomaly_involved_window_count"]),
            _number(details["clean_window_count"]),
            _number(details["raw_hourly_sample_std"].get("median")),
            _number(details["raw_hourly_sample_std"].get("max")),
        ]
        for window, details in volatility.items()
    ]
    acf_rows = [
        [
            str(item["lag_hours"]),
            _number(item["pair_count"]),
            _number(item["log_return_acf"]),
            _number(item["absolute_log_return_acf"]),
            _number(item["clean_endpoint_pair_count"]),
        ]
        for item in acf
    ]
    seasonality_tables = []
    for name, key in (
        ("UTC hour of day", "utc_hour"),
        ("UTC weekday (Monday=0)", "utc_weekday_monday_zero"),
    ):
        group_key = "hour" if key == "utc_hour" else "weekday"
        rows = [
            [
                str(item[group_key]),
                _number(item["count"]),
                _number(item["mean_log_return"]),
                _number(item["median_log_return"]),
                _number(item["std_log_return"]),
                _number(item["mean_absolute_log_return"]),
                _number(item["anomaly_involved_count"]),
            ]
            for item in summary["seasonality"][key]
        ]
        seasonality_tables.append(
            f"### {name}\n\n"
            + _table(
                [
                    "Group",
                    "Count",
                    "Mean log r",
                    "Median log r",
                    "Std log r",
                    "Mean abs(log r)",
                    "Flagged",
                ],
                rows,
            )
        )
    regime_rows = [
        [
            str(item["year"]),
            *(_number(item[label]) for label in ("low", "medium", "high")),
        ]
        for item in regimes["yearly_counts"]
    ]
    thresholds = regimes["thresholds"] or {}
    tail = summary["heavy_tail_comparison"]
    schema_table = _table(
        ["Field", "Silver type"],
        [[field, dtype] for field, dtype in dataset["schema"].items()],
    )
    chart_list = "\n".join(f"- `{data_dir}/charts/{name}`" for name in chart_files)
    table_list = "\n".join(f"- `{data_dir}/tables/{name}`" for name in table_files)
    gaps = "\n".join(
        f"- `{timestamp}`" for timestamp in dataset["missing_timestamps_utc"]
    )
    return f"""# QNT-002A — Gap-Aware BTC/USDT Exploratory Data Analysis

This is read-only, descriptive research on the existing Binance Spot BTC/USDT
Silver 1-hour dataset. It does not create trading signals, train a model, or
change Bronze/Silver. All derived rows and charts are local-only.

## Dataset identity and coverage

- Source: `{dataset["source"]}`.
- Input SHA-256: `{dataset["sha256"]}`.
- Identity: `{dataset["exchange"]}` Spot, `{dataset["symbol"]}`, `{dataset["timeframe"]}`.
- First and last observed candle opens (UTC): `{dataset["first_observed_utc"]}` to `{dataset["last_observed_utc"]}`.
- End-exclusive boundary: `{dataset["end_exclusive_utc"]}`.
- Expected hourly opens: {_number(dataset["expected_hour_count"])}; observed: {_number(dataset["observed_candle_count"])}; missing: {_number(dataset["missing_hour_count"])}.
- Dataset audit: {_number(dataset["duplicate_count"])} duplicates, {_number(dataset["out_of_order_count"])} out of order, {_number(dataset["hour_misalignment_count"])} misaligned, {_number(dataset["ohlc_invalid_count"])} OHLC invalid, {_number(dataset["nonpositive_price_count"])} nonpositive prices, {_number(dataset["negative_volume_count"])} negative volumes. All source timestamps are timezone-aware UTC.

Silver schema:

{schema_table}

The local `{data_dir}/timeline.parquet` contains every expected hour in this
observed interval. Missing hours have null OHLCV; none is forward-filled or
interpolated. No first-observed candle is treated as proof of listing date.

## Data quality findings

Documented absent hours still missing: {_number(dataset["documented_missing_count"])};
unexpected missing hours: {_number(dataset["unexpected_missing_count"])};
documented gaps now observed: {_number(dataset["documented_gap_now_observed_count"])}.
The missing hours form {_number(dataset["gap_period_count"])} gap periods.
Exact missing opens (UTC):

{gaps}

The documented BTC archive/REST discrepancy at 2021-04-23 01:00 UTC is flagged
on {_number(dataset["archive_discrepancy_observation_count"])} observed candle.
The four BTC shortened-close candles are flagged on
{_number(dataset["shortened_close_observation_count"])} observations. These
flags come from `{dataset["anomaly_provenance"]}`, not from a close-time field in
Silver. Their causes remain unknown. Returns touching flagged candles and
rolling windows containing those returns retain explicit anomaly indicators.
Because the disputed 01:00 candle's **close** enters two adjacent ratios, the
valid returns ending at 2021-04-23 01:00 and 02:00 UTC are both flagged. Each
shortened-close candle immediately precedes a documented gap: its ending
return is flagged, the next hour has no return, and the first observed candle
after the gap has an invalid return. No historical value is replaced.

## Gap-aware returns and distribution

A return is valid only when both observed candle opens are exactly one hour
apart. Valid returns: {_number(returns["valid_count"])}; invalid among observed
candles: {_number(returns["invalid_observed_count"])}; invalid across all
timeline hours: {_number(returns["invalid_timeline_hour_count"])}. Of valid
returns, {_number(returns["anomaly_involved_count"])} touch a flagged candle
and {_number(returns["clean_count"])} do not. The primary descriptive tables
include all continuity-valid returns and report the clean subset separately.

{_table(["Series", "Count", "Mean", "Median", "Std", "Min", "Max", "Skew", "Excess kurtosis"], distribution_rows)}

Quantiles use linear interpolation (Hyndman–Fan type 7):

{_table(["Series", "1%", "5%", "25%", "75%", "95%", "99%"], quantile_rows)}

Standard deviation uses the sample `n-1` denominator. Skewness is the third
central moment divided by the second central moment to the 3/2 power;
excess kurtosis is the fourth divided by the squared second minus 3, with
`n` denominators for moments. For log returns, the fraction beyond three
sample standard deviations from the mean is
{_number(tail["observed_beyond_three_sample_std_fraction"])}, versus
{_number(tail["normal_beyond_three_std_fraction"])} for a matched normal
benchmark. This and excess kurtosis are descriptive heavy-tail comparisons,
not tests of significance or distributional proof.

## Volatility analysis

Rolling values are **raw hourly** sample standard deviations of 24 or 168
consecutive valid one-hour log returns (requiring 25 or 169 consecutive
observed candle opens). They are not annualized. Gaps reset each window;
no window crosses an absent hour.

{_table(["Returns/window", "Valid windows", "Flagged windows", "Clean windows", "Median std", "Maximum std"], volatility_rows)}

The 168-hour volatility distribution and its time variation describe episodes
of higher and lower variability. Positive absolute-return autocorrelation in
the table below is consistent with volatility clustering descriptively, but
does not establish predictability or a causal mechanism.

## Autocorrelation

Pairs are separated by the stated number of actual elapsed UTC hours, have
valid returns at both endpoints, and stay in the same uninterrupted segment;
thus no missing observation lies between paired returns. Correlations are
pairwise Pearson coefficients: each endpoint series is centered on its own
mean over that lag's eligible pairs, then the cross-product sum is divided by
the geometric mean of the two centered square sums. This is not a fixed-mean
full-series ACF estimator. Clean-endpoint pair counts exclude flagged
endpoint returns; they do not replace the primary counts.

{_table(["Lag (h)", "Valid pairs", "Log-return ACF", "Abs log-return ACF", "Clean-endpoint pairs"], acf_rows)}

These are descriptive associations, not evidence of tradable predictability.

## UTC seasonality

Only valid one-hour log returns enter each group. `Flagged` counts returns
touching documented anomalous candles; Monday is weekday 0.

{"\n\n".join(seasonality_tables)}

Group differences are exploratory. No trading rule was optimized or evaluated.

## Descriptive market regimes

Low/medium/high labels are assigned only to **anomaly-free** 168-return
windows. Thresholds are the empirical 1/3 and 2/3 quantiles of all eligible
windows in this **full analysis sample**: {_number(thresholds.get("low_to_medium"))}
and {_number(thresholds.get("medium_to_high"))} raw hourly standard deviation.
This is retrospective classification using future sample information; labels
are **not point-in-time trading signals** and must not be used for training
or backtesting.

- Low: {_number(regimes["counts"].get("low", 0))}; medium: {_number(regimes["counts"].get("medium", 0))}; high: {_number(regimes["counts"].get("high", 0))}.
- Unclassified timeline hours (warm-up, gaps, or flagged windows): {_number(regimes.get("unclassified_hour_count"))}.

{_table(["UTC year", "Low", "Medium", "High"], regime_rows)}

## Local artifacts and reproducibility

Run `PYTHONPATH=src .venv/bin/python -m quant.research` from the repository
root. It reads only the approved BTC Silver file and regenerates the local
`{data_dir}/results.json`, `timeline.parquet`, CSV tables, SVG charts, and
this report. Outputs omit
run timestamps and machine-specific paths. The local artifacts are ignored by
Git; this report contains aggregates, not the market dataset.

Tables:

{table_list}

Charts:

{chart_list}

The return histogram and volatility histogram display only the central
0.1–99.9% range for legibility, with omitted tail counts in their axis labels;
all statistical calculations use the full eligible samples. Monthly return
quantiles and daily median rolling volatilities are display aggregations,
not replacements for the hourly timeline.

## Methodological limitations and future questions

- Four shortened-close observations may not represent complete uninterrupted
  hours; Silver lacks source close-time metadata. The 999 ms case may reflect
  precision rather than materially shortened trading. No cause is inferred.
- The April 2021 REST/archive discrepancy is unresolved. Both source values
  remain in provenance artifacts; Silver is unchanged. Descriptive statistics
  include continuity-valid flagged returns, with a clean-return sensitivity
  summary, rather than silently correcting or discarding them.
- The 14 missing hours are absent from both checked Binance sources, but no
  exchange-outage or listing-date claim follows. Other months and providers
  were not independently reconciled here.
- The sample ends at the last locally observed complete candle, not a claimed
  all-history endpoint. Group differences and heavy-tail comparisons are
  descriptive; no significance tests, causal claims, strategy optimization,
  model training, or backtesting were performed.
- Future research can ask whether tail and volatility descriptions are stable
  across years and anomaly-exclusion choices, whether UTC seasonal patterns
  survive uncertainty-aware testing, and whether archive revisions change
  results. Such work needs separate approval and point-in-time safeguards.
"""
