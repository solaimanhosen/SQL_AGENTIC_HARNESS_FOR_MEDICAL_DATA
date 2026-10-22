import dataclasses
from datetime import date

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

import main
import sql_agent.agent as agent_module
from sql_agent.agent import MAX_HISTORY_TURNS, AgentResult, SqlAgent, Turn, _final_text, _token_totals
from sql_agent.config import load_settings
from sql_agent.db import ReadOnlyDatabase
from sql_agent.answer import AnswerIssues, Draft, Finding, StructuredAnswer, TimeWindow, draft_from_partial
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


class _FakeGraph:
    """Stands in for the LangChain agent: records what it was given and answers at once."""

    def __init__(self):
        self.inputs = []

    def stream(self, state, config=None, stream_mode=None):
        self.inputs.append(state)
        assert stream_mode == ["messages", "values"]
        yield "values", {"messages": []}
        for chunk in self.chunks:
            yield "messages", (chunk, {"langgraph_node": "model"})
        yield "values", {
            "messages": [AIMessage("done", usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4})],
            "structured_response": StructuredAnswer(headline="Seventeen patients have heart disease."),
        }

    chunks = ()


@pytest.fixture
def offline_agent(sample_db_path, monkeypatch):
    graph = _FakeGraph()
    created, built = [], []
    monkeypatch.setattr(agent_module, "create_agent", lambda *args, **kwargs: created.append(kwargs) or graph)
    monkeypatch.setattr(agent_module, "build_chat_model", lambda settings, **choice: built.append(choice))
    settings = dataclasses.replace(load_settings({}), db_path=sample_db_path)
    agent = SqlAgent(settings, db=ReadOnlyDatabase(sample_db_path, max_rows=10, timeout_seconds=5))
    agent.graph = graph
    agent.created, agent.built = created, built
    return agent


def test_a_question_runs_on_the_default_model_unless_another_is_chosen(offline_agent):
    result = offline_agent.answer("How many?")
    assert offline_agent.built[-1] == {"model": "claude-opus-5", "effort": "high"}
    assert (result.model, result.effort) == ("claude-opus-5", "high")

    result = offline_agent.answer("How many?", model="claude-haiku-5-5", effort="low")
    assert offline_agent.built[-1] == {"model": "claude-haiku-5-5", "effort": "low"}
    assert (result.model, result.effort) == ("claude-haiku-5-5", "low")


def test_the_answer_always_uses_native_structured_output(offline_agent):
    from langchain.agents.structured_output import ProviderStrategy

    offline_agent.answer("How many?", model="claude-sonnet-5-5")
    strategy = offline_agent.created[-1]["response_format"]
    assert isinstance(strategy, ProviderStrategy) and strategy.schema is StructuredAnswer


def test_a_result_becomes_a_turn_without_its_query_citations():
    result = _result(answer="Eight patients. [query 1]\n\nFindings\n  - Eight. [query 1, 2]\n  - Why. [no query cited]")
    turn = result.as_turn()
    assert turn.question == "How many?"
    assert turn.answer == "Eight patients.\n\nFindings\n  - Eight.\n  - Why."
    assert turn.sql == ("SELECT 1",), "only SQL that succeeded is carried forward"


def test_a_turn_is_replayed_as_a_question_and_an_answer_with_its_sql():
    user, assistant = Turn(question="How many have diabetes?", answer="Eight.", sql=("SELECT 8",)).as_messages()
    assert user == {"role": "user", "content": "How many have diabetes?"}
    assert assistant["role"] == "assistant"
    assert assistant["content"].startswith("Eight.") and "SELECT 8" in assistant["content"]


def test_a_follow_up_is_sent_after_the_earlier_turns(offline_agent):
    history = [Turn(question="How many have diabetes?", answer="Eight.", sql=("SELECT 8",))]
    result = offline_agent.answer("What about heart disease?", history=history)
    messages = offline_agent.graph.inputs[0]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "How many have diabetes?"
    assert messages[-1]["content"] == "What about heart disease?"
    assert result.history == tuple(history)


def test_only_the_most_recent_turns_are_sent(offline_agent):
    history = [Turn(question=f"question {number}", answer="answer") for number in range(MAX_HISTORY_TURNS + 3)]
    result = offline_agent.answer("latest", history=history)
    messages = offline_agent.graph.inputs[0]["messages"]
    assert len(messages) == 2 * MAX_HISTORY_TURNS + 1
    assert messages[0]["content"] == "question 3"
    assert len(result.history) == MAX_HISTORY_TURNS


def test_a_question_with_no_history_is_sent_alone(offline_agent):
    offline_agent.answer("How many?")
    assert offline_agent.graph.inputs[0]["messages"] == [{"role": "user", "content": "How many?"}]


def test_the_prompt_says_earlier_answers_are_context_not_evidence():
    prompt = build_system_prompt(load_semantic_layer(), AS_OF, max_rows=200)
    assert "context, not evidence" in prompt
    assert "cite only the queries you ran for this question" in prompt


def test_a_draft_is_read_from_an_answer_that_has_only_partly_arrived():
    assert draft_from_partial('{"headline":"8 of the 108 pat') == Draft(headline="8 of the 108 pat")
    partial = '{"headline":"Eight.","findings":[{"statement":"8 match.","query_numbers":[1]},{"statement":"A further 34'
    assert draft_from_partial(partial) == Draft(headline="Eight.", findings=("8 match.", "A further 34"))


@pytest.mark.parametrize("text", ["", "{", '{"headline":""', "Let me check the tables first.", "[1, 2]", '{"findings":[{}]}'])
def test_text_that_holds_no_answer_yet_gives_no_draft(text):
    assert draft_from_partial(text) is None


def test_the_answer_is_reported_as_the_model_writes_it(offline_agent):
    offline_agent.graph.chunks = [
        AIMessageChunk("I will count them.", id="m1"),
        AIMessageChunk('{"headline":"Seventeen pat', id="m2"),
        AIMessageChunk("", id="m2"),
        AIMessageChunk('ients have heart disease.","findings":[', id="m2"),
        AIMessageChunk('{"statement":"17 match."}]}', id="m2"),
    ]
    drafts = []
    result = offline_agent.answer("How many?", on_draft=drafts.append)
    assert drafts == [
        Draft(headline="Seventeen pat"),
        Draft(headline="Seventeen patients have heart disease."),
        Draft(headline="Seventeen patients have heart disease.", findings=("17 match.",)),
    ]
    assert result.structured.headline == "Seventeen patients have heart disease."
    assert (result.input_tokens, result.output_tokens) == (3, 1)


def test_a_remark_before_a_tool_call_does_not_leak_into_the_draft(offline_agent):
    offline_agent.graph.chunks = [AIMessageChunk('{"note": "thinking aloud"}', id="m1"), AIMessageChunk('{"headline":"Done."}', id="m2")]
    drafts = []
    offline_agent.answer("How many?", on_draft=drafts.append)
    assert drafts == [Draft(headline="Done.")]


def test_a_run_told_to_stop_ends_at_its_next_step(offline_agent):
    from sql_agent.agent import AgentStopped, describe_failure

    with pytest.raises(AgentStopped) as stopped:
        offline_agent.answer("How many?", should_stop=lambda: True)
    assert describe_failure(stopped.value)[0] == "stopped"
    assert offline_agent.answer("How many?", should_stop=lambda: False).structured is not None
