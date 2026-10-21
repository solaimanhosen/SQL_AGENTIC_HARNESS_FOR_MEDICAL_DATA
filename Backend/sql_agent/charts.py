"""Charts, resolved from the run rather than written by the model.

The model asks for a chart by naming a query and its columns. The values plotted are read
here from that query's recorded rows, so a chart can only ever show numbers that came out
of SQL that ran for this question. A request that cannot be resolved is refused with a
reason, which becomes a traceability warning, and nothing is drawn for it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .answer import ChartRequest
    from .tools import QueryRecord

MAX_CHARTS = 3
MAX_BARS = 60
MAX_LINE_POINTS = 400
MAX_SERIES = 8
EMPTY_LABEL = "(empty)"


class ChartProblem(ValueError):
    """The chart asked for cannot be drawn from the run, and why."""


@dataclass(frozen=True)
class Series:
    name: str
    values: tuple[float | None, ...]
    """One value per category, in the order of `Chart.x`. None is a gap."""


@dataclass(frozen=True)
class Chart:
    kind: str
    """bar or line."""
    title: str
    query_number: int
    x_label: str
    y_label: str
    x: tuple[str, ...]
    series: tuple[Series, ...]


def resolve_charts(
    requests: Sequence["ChartRequest"], queries: Sequence["QueryRecord"]
) -> tuple[tuple[Chart, ...], tuple[str, ...]]:
    """The charts that can be drawn, and a reason for each one that cannot."""
    charts, problems = [], []
    for index, request in enumerate(requests):
        if index >= MAX_CHARTS:
            problems.append(f"{_name(request)}: only the first {MAX_CHARTS} charts are drawn")
            continue
        try:
            charts.append(resolve_chart(request, queries))
        except ChartProblem as exc:
            problems.append(f"{_name(request)}: {exc}")
    return tuple(charts), tuple(problems)


def resolve_chart(request: "ChartRequest", queries: Sequence["QueryRecord"]) -> Chart:
    record = next((query for query in queries if query.ok and query.number == request.query_number), None)
    if record is None:
        raise ChartProblem(f"query {request.query_number} did not run")
    if record.truncated:
        raise ChartProblem(f"query {request.query_number} kept only some of its rows, so a chart would mislead")
    if not record.rows:
        raise ChartProblem(f"query {request.query_number} returned no rows")
    if not request.y:
        raise ChartProblem("no column to plot was named")
    if request.series and len(request.y) > 1:
        raise ChartProblem("split by a series column, or plot several columns, but not both")

    x_index = _column(record.columns, request.x)
    y_indexes = [_column(record.columns, name) for name in request.y]
    if request.series:
        series_index = _column(record.columns, request.series)
        categories, series = _long(record.rows, x_index, y_indexes[0], series_index)
    else:
        categories = [_label(row[x_index]) for row in record.rows]
        if len(set(categories)) < len(categories):
            raise ChartProblem(f"{request.x} repeats values, so split them with a series column or aggregate first")
        series = [
            Series(record.columns[index], tuple(_number(row[index], record.columns[index]) for row in record.rows))
            for index in y_indexes
        ]

    if len(series) > MAX_SERIES:
        raise ChartProblem(f"{len(series)} series, more than {MAX_SERIES}")
    limit = MAX_BARS if request.kind == "bar" else MAX_LINE_POINTS
    if len(categories) > limit:
        raise ChartProblem(f"{len(categories)} points, more than {limit} for a {request.kind} chart")
    if all(value is None for each in series for value in each.values):
        raise ChartProblem("every value to plot is empty")

    return Chart(
        kind=request.kind,
        title=request.title.strip() or f"Query {request.query_number}",
        query_number=request.query_number,
        x_label=record.columns[x_index],
        y_label=record.columns[y_indexes[0]] if len(y_indexes) == 1 else "",
        x=tuple(categories),
        series=tuple(series),
    )


def _long(rows: Sequence[Sequence], x_index: int, y_index: int, series_index: int) -> tuple[list[str], list[Series]]:
    """Rows of (category, series, value) laid out as one series per series value."""
    categories: list[str] = []
    names: list[str] = []
    cells: dict[tuple[str, str], float | None] = {}
    for row in rows:
        category, name = _label(row[x_index]), _label(row[series_index])
        if (category, name) in cells:
            raise ChartProblem(f"more than one row for {category} in series {name}")
        if category not in categories:
            categories.append(category)
        if name not in names:
            names.append(name)
        cells[(category, name)] = _number(row[y_index], "the value column")
    return categories, [Series(name, tuple(cells.get((category, name)) for category in categories)) for name in names]


def _column(columns: Sequence[str], name: str) -> int:
    wanted = (name or "").strip().lower()
    matches = [index for index, column in enumerate(columns) if column.lower() == wanted]
    if len(matches) != 1:
        found = "is not a column" if not matches else "names more than one column"
        raise ChartProblem(f"{name!r} {found} of the query, which returned {', '.join(columns)}")
    return matches[0]


def _number(value: object, column: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ChartProblem(f"{column} holds values that are not numbers")
    try:
        number = float(value)
    except ValueError:
        raise ChartProblem(f"{column} holds values that are not numbers, such as {str(value)[:30]!r}") from None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _label(value: object) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return EMPTY_LABEL
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _name(request: "ChartRequest") -> str:
    return f"chart {request.title.strip()!r}" if request.title.strip() else f"chart of query {request.query_number}"


# Drawing, for the HTML report. The interface draws the same charts in
# Frontend/src/app/chat/chart-scale.ts and chart-view.html; the geometry and the tick rule
# here follow that file so a chart reads the same in both places. There is no script in a
# report, so each mark carries a <title> the browser shows on hover.

PLOT_HEIGHT = 220
TOP = 18
AXIS_BAND = 34
MAX_BAR = 24
BAR_GAP = 2
CHAR_WIDTH = 6.6
MAX_LABEL_CHARS = 12
REPORT_WIDTH = 720


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """Round tick values covering lo to hi, about `target` of them, stepped by 1, 2 or 5."""
    if lo == hi:
        if lo == 0:
            hi = 1
        elif lo > 0:
            lo = 0
        else:
            hi = 0
    step = _nice_step((hi - lo) / target)
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step
    decimals = max(0, -math.floor(math.log10(step)))
    ticks = []
    value = start
    while value <= end + step / 2:
        rounded = round(value, decimals)
        ticks.append(int(rounded) if decimals == 0 else rounded)
        value += step
    return ticks


def _nice_step(raw: float) -> float:
    power = 10 ** math.floor(math.log10(raw))
    fraction = raw / power
    nice = 1 if fraction <= 1 else 2 if fraction <= 2 else 5 if fraction <= 5 else 10
    return nice * power


def value_domain(kind: str, series: Sequence) -> tuple[float, float]:
    """Bars start at zero; a line does too unless its values sit far above it."""
    values = [value for each in series for value in each.values if value is not None]
    lo, hi = min(values), max(values)
    if kind == "bar" or (lo >= 0 and lo <= hi / 2):
        lo, hi = min(lo, 0), max(hi, 0)
    return lo, hi


def format_value(value: float) -> str:
    size = abs(value)
    if size >= 1_000_000:
        return _trim(f"{value / 1_000_000:,.1f}") + "M"
    return _trim(f"{value:,.{4 if size < 1 else 2}f}")


def _trim(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


def short_label(label: str) -> str:
    return label if len(label) <= MAX_LABEL_CHARS else label[: MAX_LABEL_CHARS - 1] + "…"


def bar_path(x: float, width: float, base: float, end: float) -> str:
    """A bar with a 4px rounded end at its value and a square end on the baseline."""
    height = abs(base - end)
    r = min(4, width / 2, height)
    x0, x1 = _r(x), _r(x + width)
    if height == 0:
        return f"M{x0},{_r(base)}H{x1}"
    sign = 1 if end < base else -1
    return (
        f"M{x0},{_r(base)}V{_r(end + sign * r)}Q{x0},{_r(end)} {_r(x + r)},{_r(end)}"
        f"H{_r(x + width - r)}Q{x1},{_r(end)} {x1},{_r(end + sign * r)}V{_r(base)}Z"
    )


def _r(value: float) -> int | float:
    rounded = round(value, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def chart_svg(chart, width: int = REPORT_WIDTH) -> str:
    """The chart as inline SVG. Every piece of text is escaped: titles and labels are data."""
    kind, x_values, series = chart.kind, list(chart.x), list(chart.series)
    lo, hi = value_domain(kind, series)
    ticks = nice_ticks(lo, hi)
    low, high = ticks[0], ticks[-1]
    tick_labels = [format_value(tick) for tick in ticks]
    longest = min(max(len(label) for label in x_values), MAX_LABEL_CHARS)
    edge = round(longest * CHAR_WIDTH / 2 + 4) if kind == "line" else 0
    left = max(round(max(len(label) for label in tick_labels) * CHAR_WIDTH + 14), edge)
    last_values = [
        format_value(values[-1])
        for values in ([value for value in each.values if value is not None] for each in series)
        if values
    ]
    right = round(max([16, edge, *(len(text) * CHAR_WIDTH + 12 for text in last_values)])) if kind == "line" else 8
    bottom = TOP + PLOT_HEIGHT
    plot_width = max(width - left - right, 40)
    count = len(x_values)
    banded = kind == "bar" or count < 2
    slot = plot_width / count if banded else plot_width / (count - 1)

    def y(value: float) -> float:
        return bottom - (value - low) / ((high - low) or 1) * PLOT_HEIGHT

    def centre(index: int) -> float:
        return left + slot * (index + 0.5) if banded else left + slot * index

    zero = y(min(max(0, low), high))
    stride = max(1, math.ceil((longest * CHAR_WIDTH + 10) / (plot_width / count)))
    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {bottom + AXIS_BAND}" width="{width}" '
        f'height="{bottom + AXIS_BAND}" role="img" aria-label="{escape(_description(chart))}">'
    ]
    for tick, label in zip(ticks, tick_labels):
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{_r(y(tick))}" y2="{_r(y(tick))}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{_r(y(tick) + 4)}" text-anchor="end">{escape(label)}</text>')
    parts.append(f'<line class="baseline" x1="{left}" x2="{width - right}" y1="{_r(zero)}" y2="{_r(zero)}"/>')

    if kind == "bar":
        bars = sum(1 for each in series for value in each.values if value is not None)
        bar_width = max(2, min(MAX_BAR, (slot * 0.75 - BAR_GAP * (len(series) - 1)) / len(series)))
        group = bar_width * len(series) + BAR_GAP * (len(series) - 1)
        label_bars = bars <= 12 and bar_width >= 14
        for s, each in enumerate(series):
            for index, value in enumerate(each.values):
                if value is None:
                    continue
                x = centre(index) - group / 2 + s * (bar_width + BAR_GAP)
                end = y(value)
                tip = f"{x_values[index]} · {each.name}: {format_value(value)}"
                parts.append(
                    f'<path class="bar s{s % 8 + 1}" d="{bar_path(x, bar_width, zero, end)}">'
                    f"<title>{escape(tip)}</title></path>"
                )
                if label_bars:
                    label_y = end - 5 if value >= 0 else end + 13
                    parts.append(
                        f'<text class="value" x="{_r(x + bar_width / 2)}" y="{_r(label_y)}" '
                        f'text-anchor="middle">{escape(format_value(value))}</text>'
                    )
    else:
        ends = []
        for s, each in enumerate(series):
            points = [(index, centre(index), y(value)) for index, value in enumerate(each.values) if value is not None]
            path, previous = "", -2
            for index, px, py in points:
                path += f"{'L' if index == previous + 1 else 'M'}{_r(px)},{_r(py)}"
                previous = index
            parts.append(f'<path class="line s{s % 8 + 1}" d="{path}"/>')
            if len(points) == 1:
                parts.append(f'<circle class="dot s{s % 8 + 1}" cx="{_r(points[0][1])}" cy="{_r(points[0][2])}" r="4"/>')
            for index, px, py in points:
                tip = f"{x_values[index]} · {each.name}: {format_value(each.values[index])}"
                parts.append(f'<circle class="hit" cx="{_r(px)}" cy="{_r(py)}" r="9"><title>{escape(tip)}</title></circle>')
            if points:
                index, px, py = points[-1]
                ends.append((py, px, format_value(each.values[index])))
        positions = sorted(end[0] for end in ends)
        if len(ends) <= 4 and all(b - a >= 14 for a, b in zip(positions, positions[1:])):
            for py, px, text in ends:
                parts.append(f'<text class="value" x="{_r(px + 7)}" y="{_r(py + 4)}">{escape(text)}</text>')

    for index, label in enumerate(x_values):
        if index % stride == 0:
            parts.append(
                f'<text class="tick" x="{_r(centre(index))}" y="{bottom + 18}" text-anchor="middle">'
                f"<title>{escape(label)}</title>{escape(short_label(label))}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _description(chart) -> str:
    kind = "Bar" if chart.kind == "bar" else "Line"
    names = ", ".join(each.name for each in chart.series)
    many = len(chart.series) > 1
    return (
        f"{kind} chart: {chart.title}. {len(chart.x)} {chart.x_label} values"
        + (f", series {names}." if many else ".")
        + f" The values are in the table of query {chart.query_number}."
    )
