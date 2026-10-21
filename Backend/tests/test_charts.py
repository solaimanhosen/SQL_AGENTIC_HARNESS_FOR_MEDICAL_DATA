import pytest

from sql_agent.answer import ChartRequest, StructuredAnswer, check_answer, render_answer
from sql_agent.charts import Chart, Series, resolve_chart, resolve_charts
from sql_agent.semantic import load_semantic_layer
from sql_agent.tools import QueryRecord

MONTHS = QueryRecord(
    sql="SELECT ...",
    number=1,
    row_count=3,
    columns=("period", "count", "complete"),
    rows=(("2026-06", 51, "yes"), ("2026-07", 36, "yes"), ("2026-08", 22, "no")),
)
GROUPS = QueryRecord(
    sql="SELECT ...",
    number=2,
    row_count=4,
    columns=("month", "class", "visits"),
    rows=(("2026-06", "emergency", 6), ("2026-06", "inpatient", 2), ("2026-07", "emergency", "5"), ("2026-08", "inpatient", 1)),
)
FAILED = QueryRecord(sql="SELECT nope", error="QueryExecutionError: no such column")


def _request(**fields):
    return ChartRequest(**({"query_number": 1, "kind": "line", "x": "period", "y": ["count"], "title": "Visits"} | fields))


def test_a_chart_reads_its_values_from_the_cited_query():
    chart = resolve_chart(_request(), (FAILED, MONTHS))
    assert chart == Chart(
        kind="line",
        title="Visits",
        query_number=1,
        x_label="period",
        y_label="count",
        x=("2026-06", "2026-07", "2026-08"),
        series=(Series("count", (51, 36, 22)),),
    )


def test_a_series_column_splits_one_value_column_and_leaves_gaps_empty():
    chart = resolve_chart(_request(query_number=2, kind="bar", x="Month", y=["visits"], series="class"), (GROUPS,))
    assert chart.x == ("2026-06", "2026-07", "2026-08")
    assert chart.series == (Series("emergency", (6, 5, None)), Series("inpatient", (2, None, 1)))
    assert chart.y_label == "visits"


def test_several_value_columns_become_several_series():
    record = QueryRecord(sql="s", number=1, columns=("g", "a", "b"), rows=(("x", 1, 2.5), ("y", None, 4)))
    chart = resolve_chart(_request(kind="bar", x="g", y=["a", "b"]), (record,))
    assert chart.series == (Series("a", (1, None)), Series("b", (2.5, 4)))
    assert chart.y_label == ""


@pytest.mark.parametrize(
    ("request_fields", "queries", "problem"),
    [
        ({"query_number": 7}, (MONTHS,), "query 7 did not run"),
        ({"query_number": 1}, (FAILED,), "query 1 did not run"),
        ({"y": ["visits"]}, (MONTHS,), "'visits' is not a column of the query, which returned period, count, complete"),
        ({"y": ["complete"]}, (MONTHS,), "complete holds values that are not numbers, such as 'yes'"),
        ({"y": []}, (MONTHS,), "no column to plot was named"),
        ({"query_number": 2, "x": "month", "y": ["visits"]}, (GROUPS,), "month repeats values, so split them with a series column or aggregate first"),
        ({"query_number": 2, "x": "month", "y": ["visits", "class"], "series": "class"}, (GROUPS,), "split by a series column, or plot several columns, but not both"),
    ],
)
def test_a_chart_that_cannot_be_drawn_from_the_run_is_refused(request_fields, queries, problem):
    charts, problems = resolve_charts([_request(**request_fields)], queries)
    assert charts == ()
    assert problems == (f"chart 'Visits': {problem}",)


def test_a_chart_of_cut_off_rows_is_refused():
    record = QueryRecord(sql="s", number=1, columns=("period", "count"), rows=(("a", 1),), truncated=True)
    _, problems = resolve_charts([_request()], (record,))
    assert "kept only some of its rows" in problems[0]


def test_two_rows_for_the_same_point_are_refused():
    record = QueryRecord(sql="s", number=1, columns=("m", "c", "v"), rows=(("a", "x", 1), ("a", "x", 2)))
    _, problems = resolve_charts([_request(x="m", y=["v"], series="c")], (record,))
    assert problems == ("chart 'Visits': more than one row for a in series x",)


def test_size_limits():
    many = QueryRecord(sql="s", number=1, columns=("k", "v"), rows=tuple((str(i), i) for i in range(61)))
    assert "61 points, more than 60 for a bar chart" in resolve_charts([_request(kind="bar", x="k", y=["v"])], (many,))[1][0]
    assert resolve_charts([_request(kind="line", x="k", y=["v"])], (many,))[1] == ()
    wide = QueryRecord(sql="s", number=1, columns=("k", "s", "v"), rows=tuple(("a", str(i), i) for i in range(9)))
    assert "9 series, more than 8" in resolve_charts([_request(x="k", y=["v"], series="s")], (wide,))[1][0]


def test_only_three_charts_are_drawn():
    charts, problems = resolve_charts([_request(title=f"c{i}") for i in range(4)], (MONTHS,))
    assert len(charts) == 3
    assert problems == ("chart 'c3': only the first 3 charts are drawn",)


def test_an_empty_title_falls_back_to_the_query():
    chart = resolve_chart(_request(title="  "), (MONTHS,))
    assert chart.title == "Query 1"


def test_all_empty_values_are_refused():
    record = QueryRecord(sql="s", number=1, columns=("k", "v"), rows=(("a", None), ("b", "")))
    assert resolve_charts([_request(x="k", y=["v"])], (record,))[1] == ("chart 'Visits': every value to plot is empty",)


def test_a_refused_chart_is_a_traceability_warning_and_a_drawn_one_is_listed():
    layer = load_semantic_layer()
    answer = StructuredAnswer(headline="h", charts=[_request(), _request(query_number=9, title="Ghost")])
    issues = check_answer(answer, (MONTHS,), layer, as_of="2026-08-16")
    assert issues.chart_problems == ("chart 'Ghost': query 9 did not run",)
    assert issues.any
    text = render_answer(answer, (MONTHS,), layer, as_of="2026-08-16")
    assert "Charts\n  - Visits: line chart [query 1]" in text
    assert "Ghost" not in text
