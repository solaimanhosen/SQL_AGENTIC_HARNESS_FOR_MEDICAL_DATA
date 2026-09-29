import dataclasses
import json
from datetime import date

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from sql_agent.agent import AgentError, AgentResult
from sql_agent.answer import AnswerIssues, Finding, StructuredAnswer, TimeWindow
from sql_agent.config import load_settings
from sql_agent.conversations import ConversationStore
from sql_agent.db import ReadOnlyDatabase
from sql_agent.semantic import load_semantic_layer
from sql_agent.service import MAX_QUESTION_CHARS, create_app
from sql_agent.tools import QueryRecord

AS_OF = date(2026, 8, 16)


def _result(question: str, history=()) -> AgentResult:
    return AgentResult(
        question=question,
        answer="Eight patients have diabetes. [query 1]",
        structured=StructuredAnswer(
            headline="Eight patients have diabetes.",
            findings=[Finding(statement="8 patients match the diabetes codes.", query_numbers=[1])],
            definitions_used=["diabetes", "made_up"],
            time_window=TimeWindow(months=12),
            caveats=["Small cohort."],
        ),
        issues=AnswerIssues(unknown_definitions=("made_up",)),
        queries=(
            QueryRecord(
                sql="SELECT COUNT(*) AS n FROM conditions",
                number=1,
                row_count=1,
                elapsed_ms=3.0,
                columns=("n",),
                rows=((8,),),
            ),
            QueryRecord(sql="DROP TABLE conditions", error="UnsafeQueryError: only SELECT"),
        ),
        as_of=AS_OF,
        model="claude-opus-5",
        elapsed_s=4.321,
        input_tokens=1200,
        output_tokens=150,
        history=tuple(history),
    )


class StubAgent:
    """Stands in for SqlAgent: real settings, database and layer, but no model calls."""

    def __init__(self, settings, db, *, fail_with: Exception | None = None):
        self.settings = settings
        self.db = db
        self.layer = load_semantic_layer()
        self.as_of = AS_OF
        self.fail_with = fail_with
        self.questions = []
        self.histories = []

    def answer(self, question, *, history=(), on_event=None):
        self.questions.append(question)
        self.histories.append(tuple(history))
        if on_event is not None:
            on_event("sql", "SELECT COUNT(*) AS n FROM conditions")
            on_event("sql_result", "1 rows in 3 ms")
        if self.fail_with is not None:
            raise self.fail_with
        return _result(question, history)


@pytest.fixture
def settings(sample_db_path, tmp_path):
    return dataclasses.replace(load_settings({}), db_path=sample_db_path, log_path=tmp_path / "runs.jsonl")


@pytest.fixture
def db(sample_db_path):
    return ReadOnlyDatabase(sample_db_path, max_rows=10, timeout_seconds=5)


def _client(settings, db, *, conversations=None, **kwargs):
    agent = StubAgent(settings, db, **kwargs)
    return TestClient(create_app(agent, conversations)), agent


def _events(response):
    """Parse a server-sent event stream into (event, data) pairs."""
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_health_reports_the_database_without_calling_the_model(settings, db):
    client, agent = _client(settings, db)
    body = client.get("/api/health").json()
    assert body == {"status": "ok", "database": True, "tables": 2, "model": settings.model, "as_of": "2026-08-16"}
    assert agent.questions == []


def test_schema_lists_documented_tables_and_never_an_identity_column(settings, db):
    client, _ = _client(settings, db)
    tables = {table["name"]: table for table in client.get("/api/schema").json()}
    assert {"patients", "encounters", "conditions"} <= set(tables)
    for name, table in tables.items():
        blocked = db.blocked_columns_for(name)
        assert not {column["name"].lower() for column in table["columns"]} & blocked
    assert "ssn" in db.blocked_columns_for("patients"), "the check above must have something to find"


def test_definitions_carry_their_status_from_the_semantic_layer(settings, db):
    client, _ = _client(settings, db)
    definitions = {item["name"]: item for item in client.get("/api/definitions").json()}
    layer = load_semantic_layer()
    assert set(definitions) == set(layer.definitions)
    assert definitions["diabetes"]["label"] == layer.definitions["diabetes"].label
    assert {item["status"] for item in definitions.values()} <= {"confirmed", "assumed"}


def test_ask_returns_the_answer_with_its_sql_rows_and_warnings(settings, db):
    client, agent = _client(settings, db)
    response = client.post("/api/ask", json={"question": "How many patients have diabetes?"})
    assert response.status_code == 200
    body = response.json()

    assert agent.questions == ["How many patients have diabetes?"]
    assert body["headline"] == "Eight patients have diabetes."
    assert body["findings"] == [{"statement": "8 patients match the diabetes codes.", "query_numbers": [1]}]
    assert body["queries"][0]["sql"] == "SELECT COUNT(*) AS n FROM conditions"
    assert body["queries"][0]["columns"] == ["n"] and body["queries"][0]["rows"] == [[8]]
    assert body["queries"][1]["ok"] is False and body["queries"][1]["error"].startswith("UnsafeQueryError")
    assert body["issues"]["any"] is True and body["issues"]["unknown_definitions"] == ["made_up"]
    assert body["elapsed_s"] == 4.32 and body["input_tokens"] == 1200


def test_ask_fills_in_definition_status_and_window_dates_from_our_records(settings, db):
    client, _ = _client(settings, db)
    body = client.post("/api/ask", json={"question": "q"}).json()
    diabetes, made_up = body["definitions_used"]
    layer = load_semantic_layer()
    expected = "confirmed" if layer.definitions["diabetes"].status == "confirmed" else "assumed"
    assert diabetes["status"] == expected and diabetes["summary"] == layer.definitions["diabetes"].summary
    assert made_up == {"name": "made_up", "label": "made_up", "status": "unknown", "summary": ""}
    assert body["time_window"] == {
        "months": 12,
        "start": "2025-08-17",
        "end": "2026-08-16",
        "description": "last 12 months (2025-08-17 to 2026-08-16)",
    }


def test_each_run_is_logged_without_its_rows(settings, db):
    client, _ = _client(settings, db)
    client.post("/api/ask", json={"question": "q"})
    record = json.loads(settings.log_path.read_text().strip())
    assert record["question"] == "q"
    assert all("rows" not in query for query in record["queries"])


@pytest.mark.parametrize("payload", [{"question": ""}, {"question": "x" * (MAX_QUESTION_CHARS + 1)}, {}])
def test_bad_questions_are_refused_before_reaching_the_agent(settings, db, payload):
    client, agent = _client(settings, db)
    response = client.post("/api/ask", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert agent.questions == []


def _api_error(kind):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    if kind == "connection":
        return anthropic.APIConnectionError(request=request)
    status = 401 if kind == "auth" else 529
    response = httpx.Response(status, request=request, json={"error": {"message": "overloaded"}})
    error_class = anthropic.AuthenticationError if kind == "auth" else anthropic.APIStatusError
    return error_class("overloaded", response=response, body=None)


@pytest.mark.parametrize(
    "error,status,kind",
    [
        (AgentError("The agent was still working after 30 steps and was stopped."), 422, "agent"),
        ("auth", 502, "auth"),
        ("api", 502, "api"),
        ("connection", 503, "connection"),
    ],
)
def test_failures_map_to_a_status_and_a_readable_message(settings, db, error, status, kind):
    exc = error if isinstance(error, Exception) else _api_error(error)
    client, _ = _client(settings, db, fail_with=exc)
    response = client.post("/api/ask", json={"question": "q"})
    assert response.status_code == status
    body = response.json()
    assert body["error"] == kind and body["message"]
    assert "Traceback" not in body["message"]
    assert not settings.log_path.exists(), "a failed run has nothing to log"


def test_cross_origin_access_is_limited_to_the_configured_origins(settings, db):
    client, _ = _client(settings, db)
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:4200"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:4200"
    other = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_a_question_starts_a_conversation(settings, db):
    client, _ = _client(settings, db)
    body = client.post("/api/ask", json={"question": "How many have diabetes?"}).json()
    assert len(body["conversation_id"]) == 32 and body["turn"] == 1


def test_a_follow_up_sees_the_earlier_turn_without_its_citations(settings, db):
    client, agent = _client(settings, db)
    first = client.post("/api/ask", json={"question": "How many have diabetes?"}).json()
    second = client.post(
        "/api/ask", json={"question": "What about heart disease?", "conversation_id": first["conversation_id"]}
    ).json()
    assert second["conversation_id"] == first["conversation_id"] and second["turn"] == 2
    assert agent.histories[0] == ()
    (earlier,) = agent.histories[1]
    assert earlier.question == "How many have diabetes?"
    assert earlier.answer == "Eight patients have diabetes."
    assert earlier.sql == ("SELECT COUNT(*) AS n FROM conditions",)


def test_separate_conversations_do_not_share_history(settings, db):
    client, agent = _client(settings, db)
    client.post("/api/ask", json={"question": "first"})
    client.post("/api/ask", json={"question": "second"})
    assert agent.histories == [(), ()]


def test_an_unknown_conversation_is_refused(settings, db):
    client, agent = _client(settings, db)
    response = client.post("/api/ask", json={"question": "q", "conversation_id": "0" * 32})
    assert response.status_code == 404 and response.json()["error"] == "unknown_conversation"
    assert agent.questions == []


def test_a_malformed_conversation_id_is_refused(settings, db):
    client, _ = _client(settings, db)
    response = client.post("/api/ask", json={"question": "q", "conversation_id": "../etc"})
    assert response.status_code == 422


def test_a_conversation_answers_one_question_at_a_time(settings, db):
    store = ConversationStore()
    client, agent = _client(settings, db, conversations=store)
    conversation_id, _, _ = store.begin(None)
    response = client.post("/api/ask", json={"question": "q", "conversation_id": conversation_id})
    assert response.status_code == 409 and response.json()["error"] == "busy"
    assert agent.questions == []


def test_a_failed_question_frees_the_conversation_and_adds_no_turn(settings, db):
    store = ConversationStore()
    client, agent = _client(settings, db, conversations=store, fail_with=AgentError("stopped"))
    conversation_id, _, _ = store.begin(None)
    store.finish(conversation_id, None)
    assert client.post("/api/ask", json={"question": "q", "conversation_id": conversation_id}).status_code == 422
    _, history, turn = store.begin(conversation_id)
    assert history == () and turn == 1


def test_the_log_records_the_conversation_and_the_earlier_questions(settings, db):
    client, _ = _client(settings, db)
    first = client.post("/api/ask", json={"question": "How many have diabetes?"}).json()
    client.post("/api/ask", json={"question": "And heart disease?", "conversation_id": first["conversation_id"]})
    records = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    assert [record["conversation_id"] for record in records] == [first["conversation_id"]] * 2
    assert records[1]["previous_questions"] == ["How many have diabetes?"]


def test_the_stream_sends_the_conversation_then_each_step_then_the_answer(settings, db):
    client, _ = _client(settings, db)
    response = client.post("/api/ask/stream", json={"question": "How many have diabetes?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    assert [event for event, _ in events] == ["conversation", "step", "step", "answer"]
    conversation, answer = events[0][1], events[-1][1]
    assert conversation["turn"] == 1
    assert events[1][1] == {"kind": "sql", "detail": "SELECT COUNT(*) AS n FROM conditions"}
    assert answer["conversation_id"] == conversation["conversation_id"]
    assert answer["headline"] == "Eight patients have diabetes." and answer["queries"][0]["rows"] == [[8]]


def test_a_streamed_answer_becomes_part_of_the_conversation(settings, db):
    client, agent = _client(settings, db)
    first = _events(client.post("/api/ask/stream", json={"question": "How many have diabetes?"}))
    conversation_id = first[0][1]["conversation_id"]
    second = _events(client.post("/api/ask/stream", json={"question": "And heart disease?", "conversation_id": conversation_id}))
    assert second[0][1] == {"conversation_id": conversation_id, "turn": 2}
    assert agent.histories[1][0].question == "How many have diabetes?"


def test_a_failure_during_the_stream_is_sent_as_an_error_event(settings, db):
    client, _ = _client(settings, db, fail_with=_api_error("connection"))
    events = _events(client.post("/api/ask/stream", json={"question": "q"}))
    event, data = events[-1]
    assert event == "error" and data["error"] == "connection" and data["status"] == 503
    assert "answer" not in [name for name, _ in events]


def test_the_stream_refuses_an_unknown_conversation_before_it_starts(settings, db):
    client, _ = _client(settings, db)
    response = client.post("/api/ask/stream", json={"question": "q", "conversation_id": "f" * 32})
    assert response.status_code == 404 and response.json()["error"] == "unknown_conversation"


def test_a_run_whose_reader_never_arrives_still_finishes_and_frees_the_conversation(settings, db):
    import asyncio

    from sql_agent.service import _start

    store = ConversationStore()
    agent = StubAgent(settings, db)

    async def ask_and_walk_away():
        background = set()
        conversation_id, history, turn = store.begin(None)
        _start(agent, store, conversation_id, history, turn, "How many have diabetes?", background)
        await asyncio.gather(*background)
        return conversation_id

    conversation_id = asyncio.run(ask_and_walk_away())
    _, history, turn = store.begin(conversation_id)
    assert turn == 2 and history[0].question == "How many have diabetes?"
    assert json.loads(settings.log_path.read_text())["conversation_id"] == conversation_id
