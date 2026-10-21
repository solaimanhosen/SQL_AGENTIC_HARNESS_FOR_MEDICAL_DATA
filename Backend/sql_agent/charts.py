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
