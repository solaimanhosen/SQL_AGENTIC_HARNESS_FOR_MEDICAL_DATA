import json
from datetime import date

from sql_agent.agent import AgentResult
from sql_agent.answer import AnswerIssues, Finding, StructuredAnswer, TimeWindow
from sql_agent.runlog import build_record, log_run
from sql_agent.tools import QueryRecord


def _result() -> AgentResult:
    return AgentResult(
        question="How many?",
        answer="rendered text",
        structured=StructuredAnswer(
            headline="Eight.",
            findings=[Finding(statement="Eight patients.", query_numbers=[1])],
            definitions_used=["diabetes"],
            time_window=TimeWindow(months=12),
            caveats=["Small cohort."],
        ),
        issues=AnswerIssues(unknown_definitions=("made_up",)),
        queries=(
            QueryRecord(sql="SELECT 1", number=1, row_count=1, elapsed_ms=2.0),
            QueryRecord(sql="DROP TABLE x", error="UnsafeQueryError: nope"),
        ),
        as_of=date(2026, 8, 16),
        model="claude-opus-5",
        elapsed_s=3.456,
        input_tokens=1000,
        output_tokens=100,
    )


def test_record_holds_everything_needed_to_review_a_run():
    record = build_record(_result())
    assert record["question"] == "How many?"
    assert record["headline"] == "Eight."
    assert record["findings"] == [{"statement": "Eight patients.", "query_numbers": [1]}]
    assert record["time_window"] == {"months": 12, "description": ""}
    assert record["definitions_used"] == ["diabetes"]
    assert [query["sql"] for query in record["queries"]] == ["SELECT 1", "DROP TABLE x"]
    assert record["queries"][1]["error"].startswith("UnsafeQueryError")
    assert record["issues"]["unknown_definitions"] == ("made_up",)
    assert record["elapsed_s"] == 3.46
    assert record["timestamp"].endswith("+00:00")


def test_log_appends_one_json_line_per_run(tmp_path):
    path = tmp_path / "nested" / "runs.jsonl"
    log_run(_result(), path)
    log_run(_result(), path)
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["question"] == "How many?"


def test_record_survives_an_answer_that_was_not_structured():
    result = AgentResult(
        question="q", answer="prose", structured=None, issues=AnswerIssues(), queries=(),
        as_of=date(2026, 8, 16), model="m", elapsed_s=1.0, input_tokens=1, output_tokens=1,
    )
    record = build_record(result)
    assert record["headline"] is None and record["findings"] == [] and record["answer"] == "prose"
