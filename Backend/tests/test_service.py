import dataclasses
import json
from datetime import date

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from sql_agent.agent import AgentError, AgentResult
from sql_agent.answer import AnswerIssues, ChartRequest, Draft, Finding, StructuredAnswer, TimeWindow
from sql_agent.charts import resolve_charts
from sql_agent.config import load_settings
from sql_agent.conversations import ConversationStore
from sql_agent.limits import SpendingLimits
from sql_agent.db import ReadOnlyDatabase
from sql_agent.semantic import load_semantic_layer
from sql_agent.payload import answer_payload
from sql_agent.service import MAX_QUESTION_CHARS, create_app
from sql_agent.tools import AnalysisInfo, QueryRecord

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

    def answer(self, question, *, history=(), on_event=None, on_draft=None):
        self.questions.append(question)
        self.histories.append(tuple(history))
        if on_event is not None:
            on_event("sql", "SELECT COUNT(*) AS n FROM conditions")
            on_event("sql_result", "1 rows in 3 ms")
        if on_draft is not None:
            on_draft(Draft(headline="Eight patients"))
            on_draft(Draft(headline="Eight patients have diabetes.", findings=("8 patients match",)))
        if self.fail_with is not None:
            raise self.fail_with
        return _result(question, history)


@pytest.fixture
def settings(sample_db_path, tmp_path):
    return dataclasses.replace(
        load_settings({}),
        db_path=sample_db_path,
        log_path=tmp_path / "runs.jsonl",
        request_log_path=tmp_path / "requests.jsonl",
        conversations_path=None,
    )


@pytest.fixture
def db(sample_db_path):
    return ReadOnlyDatabase(sample_db_path, max_rows=10, timeout_seconds=5)


def _client(settings, db, *, conversations=None, limits=None, api_token=None, **kwargs):
    agent = StubAgent(settings, db, **kwargs)
    return TestClient(create_app(agent, conversations, limits=limits, api_token=api_token)), agent


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


def test_the_stream_sends_the_conversation_then_each_step_then_the_draft_then_the_answer(settings, db):
    client, _ = _client(settings, db)
    response = client.post("/api/ask/stream", json={"question": "How many have diabetes?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    assert [event for event, _ in events] == ["conversation", "step", "step", "answer_delta", "answer_delta", "answer"]
    conversation, answer = events[0][1], events[-1][1]
    assert events[3][1] == {"headline": "Eight patients", "findings": []}
    assert events[4][1] == {"headline": "Eight patients have diabetes.", "findings": ["8 patients match"]}
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

    from sql_agent.service import _claim, _start

    store = ConversationStore()
    limits = SpendingLimits.from_settings(settings)
    agent = StubAgent(settings, db)

    async def ask_and_walk_away():
        background = set()
        claim = _claim(store, limits, None)
        _start(agent, store, limits, claim, "How many have diabetes?", background)
        await asyncio.gather(*background)
        return claim.conversation_id

    conversation_id = asyncio.run(ask_and_walk_away())
    _, history, turn = store.begin(conversation_id)
    assert turn == 2 and history[0].question == "How many have diabetes?"
    assert json.loads(settings.log_path.read_text())["conversation_id"] == conversation_id
    assert limits.usage()["running"] == 0 and limits.usage()["spent_today"] == 1350


TOKEN = "a-shared-token-that-is-long-enough-to-pass"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/schema"),
        ("get", "/api/definitions"),
        ("get", "/api/usage"),
        ("get", "/api/conversations"),
        ("post", "/api/ask"),
        ("post", "/api/ask/stream"),
    ],
)
def test_with_a_token_configured_every_endpoint_but_health_requires_it(settings, db, method, path):
    client, agent = _client(settings, db, api_token=TOKEN)
    kwargs = {"json": {"question": "q"}} if method == "post" else {}
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
        response = getattr(client, method)(path, headers=headers, **kwargs)
        assert response.status_code == 401, headers
        assert response.json()["error"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    assert agent.questions == []
    assert getattr(client, method)(path, headers=AUTH, **kwargs).status_code == 200


def test_health_stays_open_so_a_monitor_needs_no_secret(settings, db):
    client, _ = _client(settings, db, api_token=TOKEN)
    assert client.get("/api/health").status_code == 200


def test_without_a_token_configured_the_service_is_open_for_local_development(settings, db):
    client, _ = _client(settings, db)
    assert client.post("/api/ask", json={"question": "q"}).status_code == 200


def test_the_browser_preflight_needs_no_token(settings, db):
    client, _ = _client(settings, db, api_token=TOKEN)
    response = client.options(
        "/api/ask",
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_an_oversized_body_is_refused_before_it_is_parsed(settings, db):
    client, agent = _client(settings, db)
    response = client.post("/api/ask", content=json.dumps({"question": "x" * 20_000}), headers={"Content-Type": "application/json"})
    assert response.status_code == 413 and response.json()["error"] == "too_large"
    assert agent.questions == []


def test_too_many_questions_at_once_are_refused_with_a_retry_hint(settings, db):
    limits = SpendingLimits(max_concurrent_runs=1, daily_token_budget=10**6, conversation_token_budget=10**6)
    limits.reserve("someone-else")
    client, agent = _client(settings, db, limits=limits)
    for path in ("/api/ask", "/api/ask/stream"):
        response = client.post(path, json={"question": "q"})
        assert response.status_code == 429 and response.json()["error"] == "too_many_runs"
        assert response.headers["retry-after"] == "10"
    assert agent.questions == []


def test_a_spent_daily_budget_refuses_questions_before_the_model_is_called(settings, db):
    limits = SpendingLimits(max_concurrent_runs=4, daily_token_budget=100_000, conversation_token_budget=10**6, reserve_tokens=60_000)
    client, agent = _client(settings, db, limits=limits)
    assert client.post("/api/ask", json={"question": "first"}).status_code == 200
    limits.settle(limits.reserve("elsewhere"), 50_000)
    response = client.post("/api/ask", json={"question": "second"})
    assert response.status_code == 429 and response.json()["error"] == "daily_budget"
    assert agent.questions == ["first"]


def test_a_refused_follow_up_leaves_the_conversation_free(settings, db):
    store = ConversationStore()
    limits = SpendingLimits(max_concurrent_runs=4, daily_token_budget=10**6, conversation_token_budget=61_000, reserve_tokens=60_000)
    client, _ = _client(settings, db, conversations=store, limits=limits)
    first = client.post("/api/ask", json={"question": "first"}).json()
    conversation_id = first["conversation_id"]
    response = client.post("/api/ask", json={"question": "second", "conversation_id": conversation_id})
    assert response.status_code == 429 and response.json()["error"] == "conversation_budget"
    _, history, turn = store.begin(conversation_id)
    assert turn == 2 and len(history) == 1
    assert client.post("/api/ask", json={"question": "a new conversation"}).status_code == 200


def test_usage_reports_what_answered_questions_spent(settings, db):
    client, _ = _client(settings, db)
    client.post("/api/ask", json={"question": "q"})
    usage = client.get("/api/usage").json()
    assert usage["spent_today"] == 1350 and usage["running"] == 0 and usage["reserved_today"] == 0


def test_every_request_is_logged_including_refusals_and_never_the_token(settings, db):
    client, _ = _client(settings, db, api_token=TOKEN)
    client.get("/api/health")
    client.post("/api/ask", json={"question": "q"})
    client.post("/api/ask", json={"question": "q"}, headers=AUTH)
    text = settings.request_log_path.read_text()
    assert TOKEN not in text
    health, refused, answered = [json.loads(line) for line in text.splitlines()]
    assert (health["path"], health["status"], health["authenticated"]) == ("/api/health", 200, False)
    assert (refused["status"], refused["refused"], refused["authenticated"]) == (401, "unauthorized", False)
    assert (answered["path"], answered["status"], answered["authenticated"], answered["refused"]) == ("/api/ask", 200, True, None)
    assert answered["elapsed_ms"] >= 0 and answered["method"] == "POST"


def test_a_body_that_hides_its_length_is_still_cut_off(settings, db):
    client, agent = _client(settings, db)

    def chunks():
        yield b'{"question": "'
        for _ in range(40):
            yield b"x" * 1_000
        yield b'"}'

    response = client.post("/api/ask", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413 and response.json()["error"] == "too_large"
    assert agent.questions == []


def test_an_answered_question_is_stored_with_its_rows_and_steps(settings, db):
    store = ConversationStore()
    client, _ = _client(settings, db, conversations=store)
    body = client.post("/api/ask", json={"question": "How many have diabetes?"}).json()
    (turn,) = store.get(body["conversation_id"]).turns
    assert turn.answer == body
    assert turn.answer["queries"][0]["rows"] == [[8]]
    assert turn.steps == [
        {"kind": "sql", "detail": "SELECT COUNT(*) AS n FROM conditions"},
        {"kind": "sql_result", "detail": "1 rows in 3 ms"},
    ]
    assert store.tokens_spent(body["conversation_id"]) == 1350


def test_result_rows_can_be_left_out_of_what_is_stored(settings, db):
    store = ConversationStore()
    client, _ = _client(dataclasses.replace(settings, store_result_rows=False), db, conversations=store)
    body = client.post("/api/ask", json={"question": "How many have diabetes?"}).json()
    assert body["queries"][0]["rows"] == [[8]], "the asker still gets the rows"
    stored = store.get(body["conversation_id"]).turns[0].answer["queries"][0]
    assert stored["rows"] == [] and stored["row_count"] == 1 and stored["sql"]


def test_a_conversation_is_continued_after_the_service_restarts(settings, db, tmp_path):
    settings = dataclasses.replace(settings, conversations_path=tmp_path / "conversations.db")
    client, _ = _client(settings, db)
    conversation_id = client.post("/api/ask", json={"question": "How many have diabetes?"}).json()["conversation_id"]

    restarted, agent = _client(settings, db)
    body = restarted.post("/api/ask", json={"question": "And heart disease?", "conversation_id": conversation_id}).json()
    assert body["turn"] == 2
    assert agent.histories[0][0].question == "How many have diabetes?"


def test_a_conversation_budget_is_not_reset_by_a_restart(settings, db, tmp_path):
    settings = dataclasses.replace(settings, conversations_path=tmp_path / "conversations.db", conversation_token_budget=100_000)
    client, _ = _client(settings, db)
    conversation_id = client.post("/api/ask", json={"question": "q"}).json()["conversation_id"]
    ConversationStore(settings.conversations_path)._db.execute("UPDATE conversations SET tokens_spent = 90000")

    restarted, agent = _client(settings, db)
    response = restarted.post("/api/ask", json={"question": "again", "conversation_id": conversation_id})
    assert response.status_code == 429 and response.json()["error"] == "conversation_budget"
    assert agent.questions == []


def _ask(client, question="How many have diabetes?", conversation_id=None, **kwargs):
    payload = {"question": question} | ({"conversation_id": conversation_id} if conversation_id else {})
    return client.post("/api/ask", json=payload, **kwargs).json()


def test_conversations_are_listed_most_recently_used_first(settings, db):
    client, _ = _client(settings, db)
    assert client.get("/api/conversations").json() == []
    first = _ask(client)["conversation_id"]
    second = _ask(client, "Which age band has the most visits?")["conversation_id"]
    _ask(client, "And heart disease?", first)
    listed = client.get("/api/conversations").json()
    assert [(item["id"], item["title"], item["turns"]) for item in listed] == [
        (first, "How many have diabetes?", 2),
        (second, "Which age band has the most visits?", 1),
    ]
    assert listed[0]["updated_at"] > listed[0]["created_at"]


def test_a_stored_conversation_is_returned_with_every_answer_as_it_was_sent(settings, db):
    client, _ = _client(settings, db)
    asked = _ask(client)
    followed = _ask(client, "And heart disease?", asked["conversation_id"])
    body = client.get(f"/api/conversations/{asked['conversation_id']}").json()
    assert body["title"] == "How many have diabetes?" and body["turns"] == 2 and body["busy"] is False
    assert [turn["answer"] for turn in body["history"]] == [asked, followed]
    assert body["history"][0]["steps"][0] == {"kind": "sql", "detail": "SELECT COUNT(*) AS n FROM conditions"}
    assert body["history"][0]["answer"]["definitions_used"][0]["status"] == "assumed"


def test_an_analysis_is_sent_with_its_label_settings_and_summary(settings, db):
    info = AnalysisInfo(
        tool="trend",
        parameters={"date_column": "start", "period": "month", "measure": "count", "value_column": None, "start": None},
        source_rows=545,
        summary=("No clear trend.",),
    )
    record = QueryRecord(
        sql="SELECT start FROM encounters", number=1, row_count=1, columns=("period", "count", "complete"),
        rows=(("2026-07", 36, "yes"),), analysis=info,
    )
    result = dataclasses.replace(_result("q"), queries=(record,))
    body = answer_payload(result, load_semantic_layer(), conversation_id="c" * 32, turn=1).model_dump(mode="json")
    assert body["queries"][0]["analysis"] == {
        "tool": "trend",
        "label": "trend by month over 545 rows",
        "parameters": info.parameters,
        "source_rows": 545,
        "summary": ["No clear trend."],
    }
    assert body["queries"][0]["rows"] == [["2026-07", 36, "yes"]]


def test_charts_are_sent_with_values_from_the_run(settings, db):
    structured = StructuredAnswer(
        headline="h",
        charts=[ChartRequest(query_number=1, kind="bar", x="n", y=["n"], title="Count")],
    )
    result = _result("q")
    charts, problems = resolve_charts(structured.charts, result.queries)
    result = dataclasses.replace(result, structured=structured, charts=charts)
    body = answer_payload(result, load_semantic_layer(), conversation_id="c" * 32, turn=1).model_dump(mode="json")
    assert problems == ()
    assert body["charts"] == [
        {
            "kind": "bar",
            "title": "Count",
            "query_number": 1,
            "x_label": "n",
            "y_label": "n",
            "x": ["8"],
            "series": [{"name": "n", "values": [8]}],
        }
    ]


def test_an_answer_stored_before_analytics_existed_still_opens(settings, db, tmp_path):
    settings = dataclasses.replace(settings, conversations_path=tmp_path / "conversations.db")
    client, _ = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    store = ConversationStore(settings.conversations_path)
    (answer_json,) = store._db.execute("SELECT answer_json FROM turns").fetchone()
    old = json.loads(answer_json)
    for query in old["queries"]:
        del query["analysis"]
    del old["charts"], old["issues"]["chart_problems"]
    store._db.execute("UPDATE turns SET answer_json = ?", (json.dumps(old),))
    store._db.commit()

    reopened, _ = _client(settings, db)
    response = reopened.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200
    answer = response.json()["history"][0]["answer"]
    assert answer["queries"][0]["analysis"] is None
    assert answer["charts"] == [] and answer["issues"]["chart_problems"] == []


def test_a_conversation_can_be_renamed_and_deleted(settings, db):
    client, agent = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "Diabetes counts"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Diabetes counts"
    for title in ("", "   ", "x" * 101):
        assert client.patch(f"/api/conversations/{conversation_id}", json={"title": title}).status_code == 422

    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert client.get("/api/conversations").json() == []
    for response in (
        client.get(f"/api/conversations/{conversation_id}"),
        client.delete(f"/api/conversations/{conversation_id}"),
        client.patch(f"/api/conversations/{conversation_id}", json={"title": "x"}),
        client.post("/api/ask", json={"question": "q", "conversation_id": conversation_id}),
    ):
        assert response.status_code == 404 and response.json()["error"] == "unknown_conversation"
    assert len(agent.questions) == 1


def test_a_conversation_can_be_pinned_and_unpinned(settings, db):
    client, _ = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    assert client.get("/api/conversations").json()[0]["pinned_at"] is None

    pinned = client.patch(f"/api/conversations/{conversation_id}", json={"pinned": True})
    assert pinned.status_code == 200 and pinned.json()["pinned_at"] is not None
    assert client.get("/api/conversations").json()[0]["pinned_at"] == pinned.json()["pinned_at"]

    both = client.patch(f"/api/conversations/{conversation_id}", json={"title": "Kept", "pinned": False})
    assert both.json()["title"] == "Kept" and both.json()["pinned_at"] is None
    for body in ({}, {"pinned": "yes please"}, {"title": None, "pinned": None}):
        assert client.patch(f"/api/conversations/{conversation_id}", json=body).status_code == 422


def test_conversations_can_be_searched(settings, db):
    client, _ = _client(settings, db)
    diabetes = _ask(client, "How many have diabetes?")["conversation_id"]
    _ask(client, "Emergency visits by month")
    found = client.get("/api/conversations", params={"q": "DIABETES"})
    assert found.status_code == 200 and [item["id"] for item in found.json()] == [diabetes]
    assert len(client.get("/api/conversations", params={"q": "  "}).json()) == 2
    assert client.get("/api/conversations", params={"q": "x" * 201}).status_code == 422


def test_a_conversation_still_answering_cannot_be_deleted(settings, db):
    store = ConversationStore()
    client, _ = _client(settings, db, conversations=store)
    conversation_id, _, _ = store.begin(None)
    response = client.delete(f"/api/conversations/{conversation_id}")
    assert response.status_code == 409 and response.json()["error"] == "busy"
    assert client.get(f"/api/conversations/{conversation_id}").json()["busy"] is True


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_managing_a_conversation_requires_the_token_and_a_well_formed_id(settings, db, method):
    client, _ = _client(settings, db, api_token=TOKEN)
    conversation_id = _ask(client, headers=AUTH)["conversation_id"]
    kwargs = {"json": {"title": "x"}} if method == "patch" else {}
    assert getattr(client, method)(f"/api/conversations/{conversation_id}", **kwargs).status_code == 401
    assert getattr(client, method)("/api/conversations/not-an-id", headers=AUTH, **kwargs).status_code == 422
    assert getattr(client, method)(f"/api/conversations/{conversation_id}", headers=AUTH, **kwargs).status_code in (200, 204)


def test_the_browser_may_rename_and_delete_from_the_configured_origin(settings, db):
    client, _ = _client(settings, db)
    for method in ("PATCH", "DELETE"):
        response = client.options(
            "/api/conversations/" + "0" * 32,
            headers={"Origin": "http://localhost:4200", "Access-Control-Request-Method": method},
        )
        assert response.status_code == 200 and method in response.headers["access-control-allow-methods"]


def test_a_stored_answer_downloads_as_a_self_contained_report(settings, db):
    client, _ = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    response = client.get(f"/api/conversations/{conversation_id}/turns/1/report")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="{conversation_id[:8]}-turn1-report.html"'
    assert response.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "<h1>How many have diabetes?</h1>" in response.text
    assert "Eight patients have diabetes." in response.text
    assert "A follow-up." not in response.text


def test_a_follow_ups_report_names_the_questions_before_it(settings, db):
    client, _ = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    _ask(client, "And heart disease?", conversation_id)
    html = client.get(f"/api/conversations/{conversation_id}/turns/2/report").text
    assert "<h1>And heart disease?</h1>" in html
    assert "<li>How many have diabetes?</li>" in html


def test_a_report_for_a_question_that_was_not_answered_is_refused(settings, db):
    client, _ = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    missing = client.get(f"/api/conversations/{conversation_id}/turns/2/report")
    assert missing.status_code == 404 and missing.json()["error"] == "unknown_turn"
    assert client.get(f"/api/conversations/{conversation_id}/turns/0/report").status_code == 422
    assert client.get(f"/api/conversations/{'f' * 32}/turns/1/report").json()["error"] == "unknown_conversation"


def test_a_report_requires_the_token(settings, db):
    client, _ = _client(settings, db, api_token=TOKEN)
    conversation_id = _ask(client, headers=AUTH)["conversation_id"]
    path = f"/api/conversations/{conversation_id}/turns/1/report"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=AUTH).status_code == 200
