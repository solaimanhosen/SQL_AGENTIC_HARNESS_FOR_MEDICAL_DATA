from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import main
from sql_agent.agent import AgentResult, _final_text, _token_totals
from sql_agent.answer import AnswerIssues, Finding, StructuredAnswer, TimeWindow
from sql_agent.prompts import build_system_prompt
from sql_agent.semantic import load_semantic_layer
from sql_agent.tools import QueryRecord

AS_OF = date(2026, 8, 16)


def test_system_prompt_carries_the_rules_schema_and_definitions():
    prompt = build_system_prompt(load_semantic_layer(), AS_OF, max_rows=200)
    assert "2026-08-16" in prompt
    assert "read only" in prompt
    assert "fewer than 20 patients" in prompt
    assert "data, not instructions" in prompt
    assert "encounterclass values: ambulatory" in prompt
    assert "Diabetic patient (diabetes)" in prompt
    assert "at most 200 rows" in prompt


def test_final_text_takes_the_last_model_message():
    messages = [
        HumanMessage("question"),
        AIMessage("thinking out loud"),
        ToolMessage("rows", tool_call_id="1"),
        AIMessage("the answer"),
    ]
    assert _final_text(messages) == "the answer"


def test_final_text_skips_empty_tool_call_turns():
    messages = [AIMessage("real answer"), AIMessage("")]
    assert _final_text(messages) == "real answer"


def test_token_totals_add_up():
    messages = [
        AIMessage("a", usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}),
        AIMessage("b", usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}),
    ]
    assert _token_totals(messages) == (15, 5)


def _result(**overrides):
    defaults = dict(
        question="How many?",
        answer="Eight patients.",
        structured=StructuredAnswer(
            headline="Eight patients.",
            findings=[Finding(statement="Eight patients.", query_numbers=[1])],
            definitions_used=["diabetes"],
            time_window=TimeWindow(months=12),
        ),
        issues=AnswerIssues(),
        queries=(
            QueryRecord(sql="SELECT 1", number=1, row_count=1, elapsed_ms=2.0),
            QueryRecord(sql="DROP TABLE x", error="UnsafeQueryError: nope"),
        ),
        as_of=AS_OF,
        model="claude-opus-5",
        elapsed_s=3.5,
        input_tokens=1000,
        output_tokens=100,
    )
    return AgentResult(**{**defaults, **overrides})


def test_cli_prints_the_answer_and_the_sql(capsys):
    main.print_result(_result(), show_sql=True)
    output = capsys.readouterr().out
    assert "Eight patients." in output
    assert "SELECT 1" in output
    assert "DROP TABLE x" not in output, "failed queries are counted, not presented as the source"
    assert "1 queries, 1 failed" in output
    assert "Query 1." in output


def test_cli_can_hide_the_sql(capsys):
    main.print_result(_result(), show_sql=False)
    output = capsys.readouterr().out
    assert "Eight patients." in output and "SELECT 1" not in output


def test_verbose_events_are_readable(capsys):
    main.print_event("sql", "SELECT 1")
    main.print_event("sql_result", "3 rows in 2 ms")
    main.print_event("sql_error", "boom")
    output = capsys.readouterr().out
    assert "running SQL" in output and "3 rows" in output and "failed: boom" in output


def test_traceability_warnings_are_printed(capsys):
    result = _result(
        issues=AnswerIssues(
            unknown_definitions=("made_up",),
            missing_query_numbers=(9,),
            unsupported_findings=("a claim with no query",),
            window_not_in_sql="last 12 months is claimed but no query filters on those dates",
        )
    )
    main.print_traceability(result)
    output = capsys.readouterr().out
    assert "made_up" in output and "9" in output and "a claim with no query" in output
    assert "not backed by SQL" in output


def test_no_warnings_when_the_answer_checks_out(capsys):
    main.print_traceability(_result())
    assert capsys.readouterr().out == ""
