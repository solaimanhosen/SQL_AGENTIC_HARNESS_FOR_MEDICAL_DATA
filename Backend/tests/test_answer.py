from datetime import date

from sql_agent.answer import (
    AnswerIssues,
    Finding,
    StructuredAnswer,
    TimeWindow,
    check_answer,
    describe_window,
    render_answer,
)
from sql_agent.semantic import load_semantic_layer
from sql_agent.tools import QueryRecord

AS_OF = date(2026, 8, 16)
LAYER = load_semantic_layer()

QUERIES = (
    QueryRecord(sql="SELECT COUNT(*) FROM conditions WHERE code IN (44054006)", number=1, row_count=1, elapsed_ms=2.0),
    QueryRecord(sql="DROP TABLE patients", error="UnsafeQueryError: nope"),
    QueryRecord(
        sql="SELECT COUNT(*) FROM encounters WHERE date(start) > date('2026-08-16','-12 months')",
        number=2,
        row_count=1,
        elapsed_ms=3.0,
    ),
)


def _answer(**overrides) -> StructuredAnswer:
    defaults = dict(
        headline="Eight patients have diabetes.",
        findings=[Finding(statement="Eight patients have diabetes.", query_numbers=[1])],
        definitions_used=["diabetes"],
        time_window=TimeWindow(months=12),
        assumptions=["Counted patients, not visits."],
        caveats=["The cohort is small."],
    )
    return StructuredAnswer(**{**defaults, **overrides})


def test_window_dates_are_computed_not_quoted():
    assert describe_window(TimeWindow(months=12), AS_OF) == "last 12 months (2025-08-17 to 2026-08-16)"
    assert describe_window(TimeWindow(description="all dates in the data"), AS_OF) == "all dates in the data"
    assert describe_window(TimeWindow(), AS_OF) == "not stated"


def test_render_shows_findings_definitions_and_status():
    text = render_answer(_answer(), QUERIES, LAYER, as_of=AS_OF)
    assert "Eight patients have diabetes." in text
    assert "[query 1]" in text
    assert "Diabetic patient (diabetes, assumed, not yet confirmed)" in text
    assert "last 12 months (2025-08-17 to 2026-08-16)" in text
    assert "The cohort is small." in text


def test_render_marks_a_definition_the_agent_invented():
    text = render_answer(_answer(definitions_used=["made_up"]), QUERIES, LAYER, as_of=AS_OF)
    assert "not a shared definition" in text


def test_render_marks_a_finding_with_no_query():
    answer = _answer(findings=[Finding(statement="Something", query_numbers=[])])
    assert "[no query cited]" in render_answer(answer, QUERIES, LAYER, as_of=AS_OF)


def test_clean_answer_has_no_issues():
    assert not check_answer(_answer(), QUERIES, LAYER, as_of=AS_OF).any


def test_check_catches_invented_definitions_and_missing_queries():
    answer = _answer(
        definitions_used=["diabetes", "made_up"],
        findings=[Finding(statement="x", query_numbers=[1, 9]), Finding(statement="y", query_numbers=[])],
    )
    issues = check_answer(answer, QUERIES, LAYER, as_of=AS_OF)
    assert issues.unknown_definitions == ("made_up",)
    assert issues.missing_query_numbers == (9,)
    assert issues.unsupported_findings == ("y",)
    assert issues.any


def test_check_catches_a_failed_query_being_cited():
    """Query 2 is the second successful query, so the failed DROP cannot be cited at all."""
    answer = _answer(findings=[Finding(statement="x", query_numbers=[3])])
    assert check_answer(answer, QUERIES, LAYER, as_of=AS_OF).missing_query_numbers == (3,)


def test_check_catches_a_window_that_no_query_applied():
    only_undated = (QUERIES[0],)
    issues = check_answer(_answer(), only_undated, LAYER, as_of=AS_OF)
    assert issues.window_not_in_sql and "12 months" in issues.window_not_in_sql


def test_window_claim_is_accepted_when_a_query_filters_on_it():
    assert check_answer(_answer(), QUERIES, LAYER, as_of=AS_OF).window_not_in_sql is None


def test_issues_default_to_clean():
    assert not AnswerIssues().any
