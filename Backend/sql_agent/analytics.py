"""Statistics the agent can ask for, computed here rather than by the model.

The model chooses an analysis and writes the SQL behind it. These functions do the
arithmetic and the tests, so a median, the direction of a trend or a p-value is never the
model's own figure. Each takes the columns and rows a query returned and gives back a small
table, which becomes the evidence a finding cites, and a few sentences saying what it shows.

Nothing here touches the database or the model, so every function is tested on fixed data.
The tests come from SciPy and suit small cohorts: Fisher's exact test for two rates, a
permutation test for two means, and the Mann-Kendall test for the direction of a trend.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

# A group with fewer values than this is flagged, as the agent's instructions do for cohorts.
SMALL_GROUP = 20
MAX_GROUPS = 50
MAX_PERIODS = 400
# The fewest complete periods a direction is judged on.
MIN_TREND_PERIODS = 4
SIGNIFICANCE = 0.05
PERMUTATIONS = 9_999
# A fixed seed, so the same rows always give the same p-value.
SEED = 2026

PERIODS = {"month": "M", "quarter": "Q", "year": "Y"}
TREND_MEASURES = ("count", "sum", "mean")
COMPARE_MEASURES = ("rate", "mean")
EMPTY_LABEL = "(empty)"


class AnalysisError(ValueError):
    """The rows or the arguments do not suit the analysis. The message says what to change."""


@dataclass(frozen=True)
class AnalysisResult:
    columns: tuple[str, ...]
    rows: tuple[tuple, ...]
    """The computed table, which is what a finding citing this analysis points at."""
    summary: tuple[str, ...]
    """Sentences stating what the table shows, with every figure computed here."""


def summarize(
    columns: Sequence[str], rows: Sequence[Sequence], *, value_column: str, group_column: str | None = None
) -> AnalysisResult:
    """Summary statistics of one numeric column, overall or for each group."""
    values = _numbers(_values(columns, rows, value_column, "values"))
    labels = _group_labels(columns, rows, group_column) if group_column else ["all rows"] * len(values)
    if not np.isfinite(values).any():
        raise AnalysisError(f"No value in {value_column!r} is a number, so there is nothing to summarise.")

    table = []
    for label, group in _groups(labels, values):
        numeric = group[np.isfinite(group)]
        n = len(numeric)
        quartiles = np.percentile(numeric, [25, 50, 75]) if n else [None] * 3
        table.append(
            (
                label,
                n,
                len(group) - n,
                _round(numeric.mean()) if n else None,
                _round(numeric.std(ddof=1)) if n > 1 else None,
                _round(numeric.min()) if n else None,
                *(_round(value) for value in quartiles),
                _round(numeric.max()) if n else None,
            )
        )

    header = ("n", "excluded", "mean", "sd", "min", "p25", "median", "p75", "max")
    summary = [f"Summarised {value_column} from {_count(len(values))} rows."]
    excluded = sum(row[2] for row in table)
    if excluded:
        summary.append(f"{_count(excluded)} values were empty or not numbers and were left out.")
    if group_column is None:
        _, _, _, mean, _, low, p25, median, p75, high = table[0]
        summary.append(
            f"Median {_fmt(median)}, middle half {_fmt(p25)} to {_fmt(p75)}, mean {_fmt(mean)}, "
            f"range {_fmt(low)} to {_fmt(high)}."
        )
        return AnalysisResult(header, tuple(row[1:] for row in table), tuple(summary))

    if len(table) <= 10:
        summary.append(
            f"Median by {group_column}: " + "; ".join(f"{row[0]} {_fmt(row[7])}" for row in table) + "."
        )
    summary += _small_groups([(row[0], row[1]) for row in table])
    return AnalysisResult((group_column, *header), tuple(table), tuple(summary))


def trend(
    columns: Sequence[str],
    rows: Sequence[Sequence],
    *,
    date_column: str,
    as_of: date,
    value_column: str | None = None,
    period: str = "month",
    measure: str = "count",
    start: date | str | None = None,
) -> AnalysisResult:
    """A value per period, and whether it is rising or falling over the complete periods.

    `count` counts rows, so the SQL should return one row per thing being counted. A period
    is complete when it lies wholly within the data: the one holding the as-of date usually
    does not, and nor does the first when the SQL starts partway through it, which `start`
    says. Incomplete periods are shown but not used for the direction.
    """
    if period not in PERIODS:
        raise AnalysisError(f"period must be one of {', '.join(PERIODS)}, not {period!r}.")
    if measure not in TREND_MEASURES:
        raise AnalysisError(f"measure must be one of {', '.join(TREND_MEASURES)}, not {measure!r}.")
    if measure == "count" and value_column:
        raise AnalysisError("count counts rows. Leave value_column out, or use sum or mean of it.")
    if measure != "count" and not value_column:
        raise AnalysisError(f"{measure} needs value_column, the column to {measure}.")
    first_day = _parse_start(start)

    when = _dates(_values(columns, rows, date_column, "dates"))
    values = (
        np.ones(len(when)) if measure == "count" else _numbers(_values(columns, rows, value_column, "values"))
    )
    readable = when.notna().to_numpy()
    if not readable.any():
        raise AnalysisError(f"No value in {date_column!r} is a date this tool can read, such as 2026-08-16.")
    periods = when[readable].dt.to_period(PERIODS[period]).reset_index(drop=True)
    span = pd.period_range(periods.min(), periods.max(), freq=PERIODS[period])
    if len(span) > MAX_PERIODS:
        raise AnalysisError(
            f"The rows span {len(span)} {period}s, more than {MAX_PERIODS}. "
            "Filter by date in SQL, or use a longer period."
        )

    by_period = {key: group.to_numpy() for key, group in pd.Series(values[readable]).groupby(periods)}
    table = []
    for each in span:
        group = by_period.get(each, np.array([]))
        numeric = group[np.isfinite(group)]
        complete = each.end_time.date() <= as_of and (first_day is None or each.start_time.date() >= first_day)
        if measure == "count":
            table.append((_period_label(each), len(group), "yes" if complete else "no"))
        else:
            value = numeric.sum() if measure == "sum" else (numeric.mean() if len(numeric) else None)
            table.append((_period_label(each), _round(value), len(numeric), "yes" if complete else "no"))

    of = "rows" if measure == "count" else f"{measure} of {value_column}"
    summary = [f"{of.capitalize()} by {period}, {table[0][0]} to {table[-1][0]}, from {_count(len(values))} rows."]
    unread = int((~readable).sum())
    if unread:
        summary.append(f"{_count(unread)} rows had no readable date in {date_column} and were left out.")
    if measure != "count":
        excluded = int((~np.isfinite(values[readable])).sum())
        if excluded:
            summary.append(f"{_count(excluded)} values were empty or not numbers and were left out.")
    incomplete = [row[0] for row in table if row[-1] == "no"]
    if incomplete:
        reasons = [f"the data ends on {as_of.isoformat()}"]
        if first_day is not None:
            reasons.insert(0, f"the rows start on {first_day.isoformat()}")
        summary.append(
            f"Incomplete, so shown but not used for the direction: {', '.join(incomplete)} "
            f"({' and '.join(reasons)})."
        )
    summary += _direction([row for row in table if row[-1] == "yes" and row[1] is not None], period)

    header = ("period", measure, "complete") if measure == "count" else ("period", measure, "n", "complete")
    return AnalysisResult(header, tuple(table), tuple(summary))


def compare_groups(
    columns: Sequence[str], rows: Sequence[Sequence], *, group_column: str, value_column: str, measure: str = "rate"
) -> AnalysisResult:
    """Compare groups by the share of rows with an event, or by the mean of a value.

    For `rate`, every row holds 1 when the event happened and 0 when it did not, so the SQL
    should return one row per member of each group. Two groups are tested against each
    other; with more, only the figures for each group are given.
    """
    if measure not in COMPARE_MEASURES:
        raise AnalysisError(f"measure must be one of {', '.join(COMPARE_MEASURES)}, not {measure!r}.")
    values = _numbers(_values(columns, rows, value_column, "values"))
    labels = _group_labels(columns, rows, group_column)
    groups = _groups(labels, values)
    if len(groups) < 2:
        raise AnalysisError(f"{group_column!r} holds only one group, and comparing needs at least two.")
    if measure == "rate":
        return _compare_rates(groups, group_column, value_column, len(values))
    return _compare_means(groups, group_column, value_column, len(values))


def _compare_rates(groups: list, group_column: str, value_column: str, total: int) -> AnalysisResult:
    for label, group in groups:
        if not np.isin(group, (0.0, 1.0)).all():
            raise AnalysisError(
                f"rate needs 0 or 1 in every row of {value_column!r}, and group {label} holds other values "
                "or empty ones. Use CASE WHEN ... THEN 1 ELSE 0 END, or COALESCE(..., 0)."
            )
    table = []
    for label, group in groups:
        n, events = len(group), int(group.sum())
        interval = stats.binomtest(events, n).proportion_ci(confidence_level=0.95, method="wilson")
        table.append((label, n, events, _round(100 * events / n), _round(100 * interval.low), _round(100 * interval.high)))

    summary = [
        f"Share of rows with {value_column} = 1 in each {group_column} group, from {_count(total)} rows, "
        "with 95% Wilson intervals."
    ]
    summary += [
        f"{label}: {_count(events)} of {_count(n)}, {_fmt(rate)}% ({_fmt(low)}% to {_fmt(high)}%)."
        for label, n, events, rate, low, high in table
    ]
    if len(table) == 2:
        (first, n1, e1, r1, _, _), (second, n2, e2, r2, _, _) = table
        p = stats.fisher_exact([[e1, n1 - e1], [e2, n2 - e2]]).pvalue
        line = f"{first} minus {second}: {_fmt(_round(r1 - r2))} percentage points"
        if e2:
            line += f", {_fmt(_round((e1 / n1) / (e2 / n2)))} times the rate"
        summary.append(line + ".")
        summary.append(f"Fisher's exact test: {_p_text(p)}, so {_verdict(p)}.")
    else:
        summary.append(_TWO_GROUPS_ONLY)
    summary += _small_groups([(row[0], row[1]) for row in table])
    return AnalysisResult(
        (group_column, "n", "events", "rate_pct", "ci_low_pct", "ci_high_pct"), tuple(table), tuple(summary)
    )


def _compare_means(groups: list, group_column: str, value_column: str, total: int) -> AnalysisResult:
    numeric = [(label, group[np.isfinite(group)], len(group)) for label, group in groups]
    table = [
        (
            label,
            len(values),
            size - len(values),
            _round(values.mean()) if len(values) else None,
            _round(values.std(ddof=1)) if len(values) > 1 else None,
            _round(np.median(values)) if len(values) else None,
        )
        for label, values, size in numeric
    ]
    summary = [f"Mean of {value_column} in each {group_column} group, from {_count(total)} rows."]
    excluded = sum(row[2] for row in table)
    if excluded:
        summary.append(f"{_count(excluded)} values were empty or not numbers and were left out.")
    summary += [f"{row[0]}: mean {_fmt(row[3])} over {_count(row[1])} values." for row in table if row[1]]
    if len(table) == 2:
        (first, a, _), (second, b, _) = numeric
        if len(a) < 2 or len(b) < 2:
            summary.append("A group has fewer than two values, so the difference is not tested.")
        else:
            result = stats.permutation_test(
                (a, b),
                _mean_difference,
                permutation_type="independent",
                vectorized=True,
                n_resamples=PERMUTATIONS,
                batch=500,
                alternative="two-sided",
                rng=np.random.default_rng(SEED),
            )
            summary.append(f"{first} minus {second}: {_fmt(_round(a.mean() - b.mean()))}.")
            summary.append(f"Permutation test of the difference in means: {_p_text(result.pvalue)}, so {_verdict(result.pvalue)}.")
    else:
        summary.append(_TWO_GROUPS_ONLY)
    summary += _small_groups([(row[0], row[1]) for row in table])
    return AnalysisResult((group_column, "n", "excluded", "mean", "sd", "median"), tuple(table), tuple(summary))


_TWO_GROUPS_ONLY = "Tests are run only between exactly two groups. Combine groups in SQL to test two of them."


def _mean_difference(x: np.ndarray, y: np.ndarray, axis: int) -> np.ndarray:
    return np.mean(x, axis=axis) - np.mean(y, axis=axis)


def _direction(complete: list[tuple], period: str) -> list[str]:
    """The Mann-Kendall verdict on the complete periods, with Sen's slope for its size."""
    if len(complete) < MIN_TREND_PERIODS:
        return [
            f"Only {len(complete)} complete {period}s, fewer than {MIN_TREND_PERIODS}, "
            "so no direction is judged."
        ]
    y = np.array([float(row[1]) for row in complete])
    x = np.arange(len(y), dtype=float)
    lines = [f"From {_fmt(complete[0][1])} in {complete[0][0]} to {_fmt(complete[-1][1])} in {complete[-1][0]}."]
    if np.all(y == y[0]):
        return lines + [f"Direction over the {len(y)} complete {period}s: no change, every value is the same."]
    result = stats.kendalltau(x, y)
    tau, p = float(result.statistic), float(result.pvalue)
    if p < SIGNIFICANCE:
        direction = "increasing" if tau > 0 else "decreasing"
        verdict = f"{direction}, and unlikely to be chance alone"
    else:
        verdict = "no clear trend, the changes could be chance"
    slope = stats.theilslopes(y, x).slope
    return lines + [
        f"Direction over the {len(y)} complete {period}s: {verdict} "
        f"(Mann-Kendall test, Kendall's tau {tau:.2f}, {_p_text(p)}).",
        f"Typical change {_fmt(_round(slope))} per {period} (Sen's slope).",
    ]


def _values(columns: Sequence[str], rows: Sequence[Sequence], name: str | None, role: str) -> list:
    wanted = (name or "").strip().lower()
    matches = [index for index, column in enumerate(columns) if column.lower() == wanted]
    if not matches:
        raise AnalysisError(
            f"There is no column {name!r} to use as the {role}. The query returned: {', '.join(columns) or 'no columns'}."
        )
    if len(matches) > 1:
        raise AnalysisError(f"More than one column is named {name!r}. Give each column its own alias.")
    if not rows:
        raise AnalysisError("The query returned no rows, so there is nothing to analyse.")
    return [row[matches[0]] for row in rows]


def _numbers(values: list) -> np.ndarray:
    """Values as floats, with empty and non-numeric values as NaN. Stored numbers are often text."""
    out = np.full(len(values), np.nan)
    for index, value in enumerate(values):
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                continue
        else:
            continue
        if math.isfinite(number):
            out[index] = number
    return out


def _dates(values: list) -> pd.Series:
    """Dates in any of the stored formats, read as SQLite's date() reads them, in UTC."""
    text = pd.Series([value if isinstance(value, str) else None for value in values], dtype=object)
    parsed = pd.to_datetime(text, errors="coerce", format="mixed", utc=True)
    return parsed.dt.tz_convert(None)


def _parse_start(start: date | str | None) -> date | None:
    if start is None or isinstance(start, date):
        return start
    text = str(start).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise AnalysisError(f"start must be a date such as 2025-08-17, not {start!r}.") from None


def _group_labels(columns: Sequence[str], rows: Sequence[Sequence], group_column: str) -> list[str]:
    labels = [_label(value) for value in _values(columns, rows, group_column, "groups")]
    distinct = len(set(labels))
    if distinct > MAX_GROUPS:
        raise AnalysisError(
            f"{group_column!r} holds {distinct} groups, more than {MAX_GROUPS}. Group more coarsely in SQL."
        )
    return labels


def _label(value: object) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return EMPTY_LABEL
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _groups(labels: list[str], values: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Each group's values, in order of the group's label."""
    by_label: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        by_label.setdefault(label, []).append(index)
    return [(label, values[by_label[label]]) for label in sorted(by_label)]


def _small_groups(sizes: list[tuple[str, int]]) -> list[str]:
    small = [f"{label} ({_count(n)})" for label, n in sizes if n < SMALL_GROUP]
    if not small:
        return []
    return [f"Fewer than {SMALL_GROUP} values in: {', '.join(small)}, so read those figures as small numbers."]


def _period_label(period: pd.Period) -> str:
    if period.freqstr.startswith("Q"):
        return f"{period.year}-Q{period.quarter}"
    return str(period)


def _round(value: object) -> float | int | None:
    """A figure as it is reported: two decimals, or four significant figures below 1."""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if number.is_integer():
        return int(number)
    digits = 2 if abs(number) >= 1 else 3 - math.floor(math.log10(abs(number)))
    rounded = round(number, digits)
    return int(rounded) if rounded.is_integer() else rounded


def _fmt(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def _count(value: int) -> str:
    return f"{value:,}"


def _p_text(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def _verdict(p: float) -> str:
    if p < SIGNIFICANCE:
        return "a difference this large is unlikely to be chance alone"
    return "the difference could be chance"
