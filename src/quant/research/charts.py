"""Dependency-free, deterministic SVG charts for local descriptive EDA."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path
from statistics import NormalDist, median

from quant.research.eda import Hour, quantile

WIDTH = 960
HEIGHT = 480
LEFT = 84
RIGHT = 26
TOP = 64
BOTTOM = 104
COLORS = ("#3178c6", "#d97706", "#16a085", "#c2416c")


def _document(title: str, body: str, *, x_label: str, y_label: str) -> str:
    title = escape(title)
    x_label = escape(x_label)
    y_label = escape(y_label)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="{title}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        f'<text x="{LEFT}" y="32" font-family="sans-serif" font-size="20" '
        f'fill="#172b4d">{title}</text>\n'
        f'<text x="{WIDTH / 2}" y="{HEIGHT - 18}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="13">{x_label}</text>\n'
        f'<text x="18" y="{HEIGHT / 2}" text-anchor="middle" '
        f'transform="rotate(-90 18 {HEIGHT / 2})" font-family="sans-serif" '
        f'font-size="13">{y_label}</text>\n'
        f"{body}\n</svg>\n"
    )


def _axes(y_min: float, y_max: float, *, left_label: str, right_label: str) -> str:
    plot_height = HEIGHT - TOP - BOTTOM
    parts = [
        f'<path d="M {LEFT} {TOP} V {HEIGHT - BOTTOM} H {WIDTH - RIGHT}" '
        'fill="none" stroke="#64748b" stroke-width="1"/>'
    ]
    for tick in range(5):
        y = TOP + plot_height * tick / 4
        value = y_max - (y_max - y_min) * tick / 4
        parts.append(
            f'<path d="M {LEFT} {y:.2f} H {WIDTH - RIGHT}" stroke="#e2e8f0"/>'
            f'<text x="{LEFT - 9}" y="{y + 4:.2f}" text-anchor="end" '
            f'font-family="monospace" font-size="11">{value:.4g}</text>'
        )
    for x, label, anchor in (
        (LEFT, left_label, "start"),
        (WIDTH - RIGHT, right_label, "end"),
    ):
        parts.append(
            f'<text x="{x}" y="{HEIGHT - BOTTOM + 20}" text-anchor="{anchor}" '
            f'font-family="sans-serif" font-size="11">{escape(label)}</text>'
        )
    return "\n".join(parts)


def line_chart(
    title: str,
    series: list[tuple[str, list[tuple[float, float]]]],
    *,
    x_label: str,
    y_label: str,
    left_label: str,
    right_label: str,
) -> str:
    all_points = [point for _, points in series for point in points]
    if not all_points:
        raise ValueError("line chart requires points")
    x_min = min(x for x, _ in all_points)
    x_max = max(x for x, _ in all_points)
    y_min = min(y for _, y in all_points)
    y_max = max(y for _, y in all_points)
    if x_max == x_min:
        x_max += 1
    if y_max == y_min:
        y_min -= 1
        y_max += 1
    padding = (y_max - y_min) * 0.06
    y_min -= padding
    y_max += padding
    plot_width = WIDTH - LEFT - RIGHT
    plot_height = HEIGHT - TOP - BOTTOM
    parts = [_axes(y_min, y_max, left_label=left_label, right_label=right_label)]
    for index, (name, points) in enumerate(series):
        color = COLORS[index % len(COLORS)]
        coords = " ".join(
            f"{LEFT + (x - x_min) / (x_max - x_min) * plot_width:.2f},"
            f"{TOP + (y_max - y) / (y_max - y_min) * plot_height:.2f}"
            for x, y in points
        )
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{color}" '
            'stroke-width="1.7" stroke-linejoin="round"/>'
        )
        parts.append(
            f'<rect x="{LEFT + 170 * index}" y="{HEIGHT - 51}" width="13" '
            f'height="4" fill="{color}"/>'
            f'<text x="{LEFT + 170 * index + 19}" y="{HEIGHT - 46}" '
            f'font-family="sans-serif" font-size="11">{escape(name)}</text>'
        )
    return _document(title, "\n".join(parts), x_label=x_label, y_label=y_label)


def bar_chart(
    title: str,
    categories: list[str],
    series: list[tuple[str, list[float]]],
    *,
    x_label: str,
    y_label: str,
) -> str:
    if not categories or any(len(values) != len(categories) for _, values in series):
        raise ValueError("bar chart requires aligned categories and values")
    all_values = [value for _, values in series for value in values]
    y_min = min(0.0, *all_values)
    y_max = max(0.0, *all_values)
    if y_max == y_min:
        y_max += 1
    plot_width = WIDTH - LEFT - RIGHT
    plot_height = HEIGHT - TOP - BOTTOM

    def to_y(value: float) -> float:
        return TOP + (y_max - value) / (y_max - y_min) * plot_height

    parts = [
        _axes(
            y_min,
            y_max,
            left_label=categories[0] if len(categories) > 24 else "",
            right_label=categories[-1] if len(categories) > 24 else "",
        )
    ]
    zero = to_y(0)
    parts.append(f'<path d="M {LEFT} {zero:.2f} H {WIDTH - RIGHT}" stroke="#475569"/>')
    group_width = plot_width / len(categories)
    bar_width = max(1.0, group_width * 0.72 / len(series))
    for index, (name, values) in enumerate(series):
        color = COLORS[index % len(COLORS)]
        for category, value in enumerate(values):
            x = LEFT + category * group_width + group_width * 0.14 + index * bar_width
            y = min(zero, to_y(value))
            height = max(0.8, abs(to_y(value) - zero))
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
                f'height="{height:.2f}" fill="{color}"/>'
            )
        parts.append(
            f'<rect x="{LEFT + 170 * index}" y="{HEIGHT - 51}" width="13" '
            f'height="8" fill="{color}"/>'
            f'<text x="{LEFT + 170 * index + 19}" y="{HEIGHT - 44}" '
            f'font-family="sans-serif" font-size="11">{escape(name)}</text>'
        )
    if len(categories) <= 24:
        for index, label in enumerate(categories):
            x = LEFT + (index + 0.5) * group_width
            parts.append(
                f'<text x="{x:.2f}" y="{HEIGHT - BOTTOM + 20}" '
                'text-anchor="middle" font-family="sans-serif" font-size="10">'
                f"{escape(label)}</text>"
            )
    return _document(title, "\n".join(parts), x_label=x_label, y_label=y_label)


def histogram(values: list[float], *, title: str, x_label: str) -> str:
    """Display the central 99.8%; full-sample statistics remain in tables."""
    if not values:
        raise ValueError("histogram requires values")
    lower = quantile(values, 0.001)
    upper = quantile(values, 0.999)
    if lower == upper:
        upper = lower + 1
    bins = 60
    counts = [0] * bins
    clipped = 0
    for value in values:
        if value < lower or value > upper:
            clipped += 1
            continue
        index = min(bins - 1, int((value - lower) / (upper - lower) * bins))
        counts[index] += 1
    chart = bar_chart(
        title,
        [f"{lower:.3g}", *[""] * (bins - 2), f"{upper:.3g}"],
        [("count", [float(value) for value in counts])],
        x_label=f"{x_label}; 0.1–99.9% display range ({clipped} outside)",
        y_label="count",
    )
    return chart


def stacked_regimes(yearly: list[dict]) -> str:
    if not yearly:
        raise ValueError("regime chart requires classified windows")
    colors = {"low": "#16a085", "medium": "#d97706", "high": "#c2416c"}
    count = len(yearly)
    group_width = (WIDTH - LEFT - RIGHT) / count
    parts = [
        _axes(
            0,
            100,
            left_label=str(yearly[0]["year"]),
            right_label=str(yearly[-1]["year"]),
        )
    ]
    for index, item in enumerate(yearly):
        total = sum(item[label] for label in colors)
        bottom = HEIGHT - BOTTOM
        for label, color in colors.items():
            height = (HEIGHT - TOP - BOTTOM) * item[label] / total
            bottom -= height
            parts.append(
                f'<rect x="{LEFT + index * group_width + 8:.2f}" '
                f'y="{bottom:.2f}" width="{group_width - 16:.2f}" '
                f'height="{height:.2f}" fill="{color}"/>'
            )
    for index, (label, color) in enumerate(colors.items()):
        parts.append(
            f'<rect x="{LEFT + 170 * index}" y="{HEIGHT - 51}" '
            f'width="13" height="8" fill="{color}"/>'
            f'<text x="{LEFT + 170 * index + 19}" y="{HEIGHT - 44}" '
            f'font-family="sans-serif" font-size="11">{label}</text>'
        )
    return _document(
        "Retrospective volatility-regime distribution by year",
        "\n".join(parts),
        x_label="UTC year",
        y_label="classified windows (%)",
    )


def render_charts(hours: list[Hour], summary: dict, directory: Path) -> list[str]:
    """Write local-only SVGs; chart inputs are descriptive, never signals."""
    directory.mkdir(parents=True, exist_ok=True)
    log = [hour.log_return for hour in hours if hour.return_valid]
    log = [value for value in log if value is not None]
    mean = summary["distribution"]["log_return"]["mean"]
    std = summary["distribution"]["log_return"]["std"]
    normal = NormalDist(mean, std)
    probabilities = [(index + 0.5) / 100 for index in range(100)]
    monthly: dict[str, list[float]] = defaultdict(list)
    daily_vol: dict[date, dict[int, list[float]]] = defaultdict(
        lambda: {24: [], 168: []}
    )
    for hour in hours:
        if hour.log_return is not None:
            monthly[hour.timestamp.strftime("%Y-%m")].append(hour.log_return)
        for window in (24, 168):
            value = getattr(hour, f"rolling_vol_{window}")
            if value is not None:
                daily_vol[hour.timestamp.date()][window].append(value)
    months = sorted(monthly)
    days = sorted(daily_vol)
    charts = {
        "return_histogram.svg": histogram(
            log, title="Hourly BTC/USDT log-return histogram", x_label="log return"
        ),
        "return_quantiles.svg": line_chart(
            "Empirical versus matched-normal log-return quantiles",
            [
                ("empirical", [(p, quantile(log, p)) for p in probabilities]),
                ("normal", [(p, normal.inv_cdf(p)) for p in probabilities]),
            ],
            x_label="cumulative probability",
            y_label="log return",
            left_label="0.005",
            right_label="0.995",
        ),
        "return_distribution_over_time.svg": line_chart(
            "Monthly hourly log-return quantiles",
            [
                (
                    label,
                    [
                        (index, quantile(monthly[month], p))
                        for index, month in enumerate(months)
                    ],
                )
                for label, p in (("5%", 0.05), ("median", 0.5), ("95%", 0.95))
            ],
            x_label="UTC month",
            y_label="hourly log return",
            left_label=months[0],
            right_label=months[-1],
        ),
        "rolling_volatility.svg": line_chart(
            "Daily medians of raw hourly rolling volatility",
            [
                (
                    f"{window} returns",
                    [
                        (index, median(daily_vol[day][window]))
                        for index, day in enumerate(days)
                        if daily_vol[day][window]
                    ],
                )
                for window in (24, 168)
            ],
            x_label="UTC day",
            y_label="raw hourly log-return std",
            left_label=days[0].isoformat(),
            right_label=days[-1].isoformat(),
        ),
        "volatility_distribution.svg": histogram(
            [
                hour.rolling_vol_168
                for hour in hours
                if hour.rolling_vol_168 is not None
            ],
            title="168-return rolling volatility distribution",
            x_label="raw hourly log-return std",
        ),
        "autocorrelation.svg": bar_chart(
            "Gap-aware autocorrelation by elapsed-hour lag",
            [str(item["lag_hours"]) for item in summary["autocorrelation"]],
            [
                (
                    "log return",
                    [
                        item["log_return_acf"] or 0
                        for item in summary["autocorrelation"]
                    ],
                ),
                (
                    "absolute log return",
                    [
                        item["absolute_log_return_acf"] or 0
                        for item in summary["autocorrelation"]
                    ],
                ),
            ],
            x_label="elapsed hours",
            y_label="pairwise Pearson correlation",
        ),
        "utc_hour_seasonality.svg": bar_chart(
            "UTC hour-of-day mean absolute log return",
            [f"{item['hour']:02d}" for item in summary["seasonality"]["utc_hour"]],
            [
                (
                    "mean absolute log return",
                    [
                        item["mean_absolute_log_return"] or 0
                        for item in summary["seasonality"]["utc_hour"]
                    ],
                )
            ],
            x_label="UTC hour",
            y_label="mean absolute log return",
        ),
        "utc_weekday_seasonality.svg": bar_chart(
            "UTC weekday mean absolute log return",
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            [
                (
                    "mean absolute log return",
                    [
                        item["mean_absolute_log_return"] or 0
                        for item in summary["seasonality"]["utc_weekday_monday_zero"]
                    ],
                )
            ],
            x_label="UTC weekday",
            y_label="mean absolute log return",
        ),
    }
    if summary["regimes"]["yearly_counts"]:
        charts["regime_yearly_distribution.svg"] = stacked_regimes(
            summary["regimes"]["yearly_counts"]
        )
    for filename, content in sorted(charts.items()):
        if not content.startswith("<svg"):
            raise ValueError(f"invalid chart output: {filename}")
        (directory / filename).write_text(content, encoding="utf-8")
    return sorted(charts)
