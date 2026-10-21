import dataclasses
from datetime import date, datetime, timezone
from html.parser import HTMLParser

import pytest

from sql_agent.agent import AgentResult
from sql_agent.answer import AnswerIssues, ChartRequest, Finding, StructuredAnswer, TimeWindow
from sql_agent.charts import Chart, Series, chart_svg, nice_ticks, resolve_charts
from sql_agent.payload import AnswerOut, answer_payload
from sql_agent.report import CONTENT_SECURITY_POLICY, render_report, report_filename
from sql_agent.semantic import load_semantic_layer
from sql_agent.tools import AnalysisInfo, QueryRecord

GENERATED = datetime(2026, 10, 20, 15, 30, tzinfo=timezone.utc)
HOSTILE = '<script>alert(1)</script></style><svg onload="alert(2)">'

TREND = QueryRecord(
    sql="SELECT start FROM encounters WHERE encounterclass = 'emergency'",
    number=1,
    row_count=3,
    elapsed_ms=8.0,
    columns=("period", "count", "complete"),
    rows=(("2026-06", 8, "yes"), ("2026-07", 6, "yes"), ("2026-08", 3, "no")),
    analysis=AnalysisInfo(
        tool="trend",
        parameters={"period": "month", "measure": "count"},
        source_rows=17,
        summary=("Incomplete, so shown but not used for the direction: 2026-08.",),
    ),
)
ROWS = QueryRecord(
    sql="SELECT description, COUNT(*) AS n FROM encounters GROUP BY 1",
    number=2,
    row_count=2,
    elapsed_ms=4.0,
    columns=("description", "n"),
    rows=((HOSTILE, 12345), (None, 2.5)),
)
FAILED = QueryRecord(sql="SELECT ssn FROM patients", error="BlockedColumnError: patients.ssn is prohibited")


def _answer(**overrides) -> AnswerOut:
    structured = StructuredAnswer(
        headline="Emergency visits rose over the year.",
        findings=[
            Finding(statement="6 visits in July 2026.", query_numbers=[1]),
            Finding(statement="One description is odd.", query_numbers=[2, 9]),
        ],
        definitions_used=["emergency_visit", "made_up"],
        time_window=TimeWindow(months=12),
        assumptions=["Visits are dated by their start."],
        caveats=["Small counts."],
        charts=[ChartRequest(query_number=1, kind="line", x="period", y=["count"], title="ED visits by month")],
    )
    queries = (TREND, ROWS, FAILED)
    charts, problems = resolve_charts(structured.charts, queries)
    result = AgentResult(
        question="Are ED visits rising?",
        answer="rendered",
        structured=structured,
        issues=AnswerIssues(missing_query_numbers=(9,), chart_problems=("chart 'x': query 7 did not run",)),
        queries=queries,
        as_of=date(2026, 8, 16),
        model="claude-opus-5",
        elapsed_s=21.4,
        input_tokens=25_220,
        output_tokens=1_308,
        charts=charts,
    )
    for key, value in overrides.items():
        result = dataclasses.replace(result, **{key: value})
    return answer_payload(result, load_semantic_layer(), conversation_id="ab" * 16, turn=2)


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attributes = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes += attrs


def _parse(html):
    parser = Tags()
    parser.feed(html)
    return parser


def test_a_report_holds_the_answer_its_chart_and_the_evidence():
    html = render_report(_answer(), generated_at=GENERATED, earlier_questions=["How many ED visits?"])
    assert "<h1>Are ED visits rising?</h1>" in html
    assert "Emergency visits rose over the year." in html
    assert 'href="#q1">Query 1</a>' in html and 'id="q1"' in html
    assert "Query 9 did not run" in html
    assert "last 12 months (2025-08-17 to 2026-08-16)" in html
    assert "Assumed, not yet confirmed" in html and "Not a shared definition" in html
    assert "<figcaption><span class=\"title\">ED visits by month</span>" in html
    assert "<svg class=\"chart-svg\"" in html
    assert "computed a trend by month over 17 rows in 8 ms" in html
    assert "Incomplete, so shown but not used for the direction: 2026-08." in html
    assert "1 failed attempt" in html and "BlockedColumnError" in html
    assert "Chart not drawn, chart &#x27;x&#x27;: query 7 did not run" in html
    assert "A follow-up." in html and "<li>How many ED visits?</li>" in html
    assert "conversation abababab, question 2" in html
    assert "Report generated 2026-10-20 15:30 UTC." in html
    assert "<td class=\"num\">12,345</td>" in html and "<td class=\"null\">null</td>" in html


def test_a_report_needs_nothing_from_the_network():
    html = render_report(_answer(), generated_at=GENERATED)
    parsed = _parse(html)
    assert "script" not in parsed.tags
    assert not {"img", "link", "iframe", "object", "embed", "form", "base"} & set(parsed.tags)
    assert "http://" not in html and "https://" not in html
    sources = [value for name, value in parsed.attributes if name in ("src", "href", "action", "srcset")]
    assert all(value.startswith("#") for value in sources), sources
    assert f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">' in html
    assert CONTENT_SECURITY_POLICY == "default-src 'none'; style-src 'unsafe-inline'"


def test_text_from_the_data_and_the_model_is_escaped_everywhere():
    hostile_answer = _answer(question=HOSTILE)
    html = render_report(hostile_answer, generated_at=GENERATED, earlier_questions=[HOSTILE])
    assert HOSTILE not in html
    assert "<script" not in html and "onload=" not in html.replace("onload=&quot;", "")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;&lt;/style&gt;" in html
    assert html.count("</style>") == 1, "a stored row must not close the stylesheet"
    assert "script" not in _parse(html).tags


def test_hostile_chart_labels_are_escaped_in_the_svg():
    chart = Chart(
        kind="bar",
        title=HOSTILE,
        query_number=1,
        x_label="g",
        y_label="n",
        x=(HOSTILE, "b"),
        series=(Series(HOSTILE, (1, 2)),),
    )
    svg = chart_svg(chart)
    assert "<script" not in svg and HOSTILE not in svg
    assert set(_parse(svg).tags) <= {"svg", "line", "text", "path", "title"}


def test_rows_left_out_of_a_stored_answer_are_noted_not_shown_empty():
    answer = _answer()
    stored = answer.model_copy(
        update={"queries": [query.model_copy(update={"rows": []}) for query in answer.queries]}
    )
    html = render_report(stored, generated_at=GENERATED)
    assert html.count("The rows were not kept with this conversation") == 2


def test_an_answer_in_plain_text_says_its_figures_are_not_linked():
    answer = _answer(structured=None, answer="Eight <b>patients</b>.", charts=())
    html = render_report(answer, generated_at=GENERATED)
    assert '<pre class="prose">Eight &lt;b&gt;patients&lt;/b&gt;.</pre>' in html
    assert "not linked to queries" in html


def test_a_report_made_on_the_command_line_names_no_conversation():
    answer = _answer().model_copy(update={"conversation_id": ""})
    assert "conversation" not in render_report(answer, generated_at=GENERATED).split("</header>")[0]


def test_an_answer_stored_before_reports_existed_still_renders():
    old = _answer().model_dump(mode="json")
    del old["charts"], old["issues"]["chart_problems"]
    for query in old["queries"]:
        del query["analysis"]
    html = render_report(AnswerOut.model_validate(old), generated_at=GENERATED)
    assert "Emergency visits rose over the year." in html and "<svg" not in html


def test_the_file_name_matches_the_other_downloads():
    assert report_filename(_answer()) == "abababab-turn2-report.html"


@pytest.mark.parametrize(
    ("lo", "hi", "expected"),
    [
        # The same cases as Frontend/src/app/chat/chart-scale.spec.ts, so both draw alike.
        (0, 63, [0, 20, 40, 60, 80]),
        (0, 8, [0, 2, 4, 6, 8]),
        (23.5, 31, [22, 24, 26, 28, 30, 32]),
        (0, 0, [0, 0.2, 0.4, 0.6, 0.8, 1]),
        (0, 0.37, [0, 0.1, 0.2, 0.3, 0.4]),
        (-5, 12, [-5, 0, 5, 10, 15]),
        (5, 5, [0, 1, 2, 3, 4, 5]),
    ],
)
def test_ticks_match_the_interface(lo, hi, expected):
    assert nice_ticks(lo, hi) == expected


def test_a_line_breaks_at_a_missing_value_and_marks_carry_tooltips():
    chart = Chart(
        kind="line",
        title="t",
        query_number=1,
        x_label="m",
        y_label="v",
        x=("a", "b", "c", "d"),
        series=(Series("v", (1, 2, None, 4)),),
    )
    svg = chart_svg(chart)
    path = svg.split('class="line s1" d="')[1].split('"')[0]
    assert path.count("M") == 2
    assert svg.count('<circle class="hit"') == 3
    assert "<title>b · v: 2</title>" in svg
