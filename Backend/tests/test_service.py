import dataclasses
import json
import time
from datetime import date

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from sql_agent.accounts import AccountStore
from sql_agent.agent import AgentError, AgentResult, AgentStopped
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


def _result(question: str, history=(), model="claude-opus-5", effort="high") -> AgentResult:
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
        model=model,
        effort=effort,
        elapsed_s=4.321,
        input_tokens=1200,
        output_tokens=150,
        history=tuple(history),
    )


class StubAgent:
    """Stands in for SqlAgent: real settings, database and layer, but no model calls."""

    def __init__(self, settings, db, *, fail_with: Exception | None = None, wait_to_be_stopped: bool = False):
        self.settings = settings
        self.db = db
        self.layer = load_semantic_layer()
        self.as_of = AS_OF
        self.fail_with = fail_with
        self.wait_to_be_stopped = wait_to_be_stopped
        self.questions = []
        self.histories = []
        self.choices = []

    def answer(self, question, *, history=(), on_event=None, on_draft=None, model=None, effort=None, should_stop=None):
        self.questions.append(question)
        self.histories.append(tuple(history))
        self.choices.append((model, effort))
        if on_event is not None:
            on_event("sql", "SELECT COUNT(*) AS n FROM conditions")
            on_event("sql_result", "1 rows in 3 ms")
        if on_draft is not None:
            on_draft(Draft(headline="Eight patients"))
            on_draft(Draft(headline="Eight patients have diabetes.", findings=("8 patients match",)))
        if self.fail_with is not None:
            raise self.fail_with
        if self.wait_to_be_stopped:
            # Like the real agent: it checks at each step, and ends once it is told to stop.
            deadline = time.monotonic() + 10
            while not (should_stop and should_stop()):
                if time.monotonic() > deadline:
                    raise AssertionError("never stopped")
                time.sleep(0.01)
            raise AgentStopped("Stopped before the answer was finished. Nothing was saved for this question.")
        return _result(question, history, model or self.settings.model, effort or self.settings.effort)


@pytest.fixture
def settings(sample_db_path, tmp_path):
    return dataclasses.replace(
        load_settings({}),
        db_path=sample_db_path,
        log_path=tmp_path / "runs.jsonl",
        request_log_path=tmp_path / "requests.jsonl",
        conversations_path=None,
        secure_cookies=False,
    )


@pytest.fixture
def db(sample_db_path):
    return ReadOnlyDatabase(sample_db_path, max_rows=10, timeout_seconds=5)


TEST_EMAIL = "ann@example.org"
TEST_PASSWORD = "a long enough password"
# What the interface sends with every request, so the cross-site check lets it through.
CSRF = {"X-Requested-With": "sql-agent"}


def _client(settings, db, *, conversations=None, limits=None, signed_in=True, admin=False, **kwargs):
    agent = StubAgent(settings, db, **kwargs)
    client = TestClient(create_app(agent, conversations, limits=limits, google=None), headers=CSRF)
    if signed_in:
        _sign_in(client, admin=admin)
    return client, agent


def _sign_in(client, email=TEST_EMAIL, *, admin=False):
    """Make the account if it is new, then sign in through the real route, as a browser would."""
    accounts = client.app.state.accounts
    user = accounts.find_by_email(email) or accounts.create_user(email, password=TEST_PASSWORD)
    if admin:
        accounts.set_role(user.id, "admin")
    response = client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    client.user_id = user.id
    return user


def _second_user(client, email="bo@example.org"):
    """Another person using the same service, in their own browser."""
    other = TestClient(client.app, headers=CSRF)
    _sign_in(other, email)
    return other


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
    conversation_id, _, _ = store.begin(None, owner=client.user_id)
    response = client.post("/api/ask", json={"question": "q", "conversation_id": conversation_id})
    assert response.status_code == 409 and response.json()["error"] == "busy"
    assert agent.questions == []


def test_a_failed_question_frees_the_conversation_and_adds_no_turn(settings, db):
    store = ConversationStore()
    client, agent = _client(settings, db, conversations=store, fail_with=AgentError("stopped"))
    conversation_id, _, _ = store.begin(None, owner=client.user_id)
    store.finish(conversation_id, None)
    assert client.post("/api/ask", json={"question": "q", "conversation_id": conversation_id}).status_code == 422
    _, history, turn = store.begin(conversation_id, owner=client.user_id)
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

    from sql_agent.service import _Choice, _claim, _start

    store = ConversationStore()
    limits = SpendingLimits.from_settings(settings)
    agent = StubAgent(settings, db)
    user = AccountStore(store.database).create_user("ann@example.org", password=TEST_PASSWORD)

    async def ask_and_walk_away():
        background = set()
        claim = _claim(store, limits, None, user)
        _start(agent, store, limits, claim, "How many have diabetes?", background, _Choice("claude-opus-5", "high"))
        await asyncio.gather(*background)
        return claim.conversation_id

    conversation_id = asyncio.run(ask_and_walk_away())
    _, history, turn = store.begin(conversation_id, owner=user.id)
    assert turn == 2 and history[0].question == "How many have diabetes?"
    assert json.loads(settings.log_path.read_text())["conversation_id"] == conversation_id
    assert limits.usage()["running"] == 0 and limits.usage()["spent_today"] == 1350


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/schema"),
        ("get", "/api/definitions"),
        ("get", "/api/usage"),
        ("get", "/api/models"),
        ("get", "/api/conversations"),
        ("post", "/api/ask"),
        ("post", "/api/ask/stream"),
    ],
)
def test_every_endpoint_but_health_and_signing_in_needs_a_session(settings, db, method, path):
    client, agent = _client(settings, db, signed_in=False)
    kwargs = {"json": {"question": "q"}} if method == "post" else {}
    for cookie in (None, "not-a-session"):
        if cookie:
            client.cookies.set("sql_agent_session", cookie)
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401 and response.json()["error"] == "unauthenticated"
    assert agent.questions == []
    client.cookies.clear()
    _sign_in(client)
    assert getattr(client, method)(path, **kwargs).status_code == 200


def test_health_and_the_sign_in_page_s_settings_stay_open(settings, db):
    client, _ = _client(settings, db, signed_in=False)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/config").json() == {"registration_open": True, "google_enabled": False}


def test_a_request_that_changes_something_must_come_from_the_application(settings, db):
    client, agent = _client(settings, db)
    bare = TestClient(client.app)  # no X-Requested-With, as a form on another site would send
    bare.cookies = client.cookies
    for response in (
        bare.post("/api/ask", json={"question": "q"}),
        client.post("/api/ask", json={"question": "q"}, headers={"Origin": "https://evil.example"}),
        bare.post("/api/auth/logout"),
    ):
        assert response.status_code == 403 and response.json()["error"] == "cross_site"
    assert agent.questions == []
    allowed = client.post("/api/ask", json={"question": "q"}, headers={"Origin": "http://localhost:4200"})
    assert allowed.status_code == 200
    assert bare.get("/api/conversations").status_code == 200, "reading needs no header"


def test_the_browser_preflight_allows_the_application_s_header(settings, db):
    client, _ = _client(settings, db, signed_in=False)
    response = client.options(
        "/api/ask",
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-requested-with,content-type",
        },
    )
    assert response.status_code == 200
    assert "x-requested-with" in response.headers["access-control-allow-headers"].lower()
    assert response.headers["access-control-allow-credentials"] == "true"


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
    _, history, turn = store.begin(conversation_id, owner=client.user_id)
    assert turn == 2 and len(history) == 1
    assert client.post("/api/ask", json={"question": "a new conversation"}).status_code == 200


def test_usage_reports_what_answered_questions_spent(settings, db):
    client, _ = _client(settings, db)
    client.post("/api/ask", json={"question": "q"})
    usage = client.get("/api/usage").json()
    assert usage["spent_today"] == 1350 and usage["running"] == 0 and usage["reserved_today"] == 0


def test_every_request_is_logged_by_user_id_including_refusals_and_never_the_session(settings, db):
    client, _ = _client(settings, db, signed_in=False)
    client.get("/api/health")
    client.post("/api/ask", json={"question": "q"})
    _sign_in(client)
    client.post("/api/ask", json={"question": "q"})
    text = settings.request_log_path.read_text()
    assert client.cookies.get("sql_agent_session") not in text and TEST_EMAIL not in text
    records = [json.loads(line) for line in text.splitlines()]
    health, refused, answered = records[0], records[1], records[-1]
    assert (health["path"], health["status"], health["user_id"]) == ("/api/health", 200, None)
    assert (refused["status"], refused["refused"], refused["user_id"]) == (401, "unauthenticated", None)
    assert (answered["path"], answered["status"], answered["user_id"], answered["refused"]) == (
        "/api/ask",
        200,
        client.user_id,
        None,
    )
    assert answered["elapsed_ms"] >= 0 and answered["method"] == "POST"
    assert json.loads(settings.log_path.read_text().splitlines()[-1])["user_id"] == client.user_id


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
    (turn,) = store.get(body["conversation_id"], owner=client.user_id).turns
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
    stored = store.get(body["conversation_id"], owner=client.user_id).turns[0].answer["queries"][0]
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


def test_the_models_on_offer_are_listed_with_the_default(settings, db):
    client, _ = _client(settings, db)
    body = client.get("/api/models").json()
    assert body["default_model"] == "claude-opus-5" and body["default_effort"] == "high"
    ids = [model["id"] for model in body["models"]]
    assert ids[0] == "claude-opus-5"
    assert "claude-haiku-5-5" in ids and "claude-sonnet-5-5" in ids
    assert "claude-fable-5-1" not in ids, "admins only, and nobody is an admin before accounts"
    haiku = next(model for model in body["models"] if model["id"] == "claude-haiku-5-5")
    assert haiku["efforts"] == ["low", "medium", "high", "xhigh", "max"]
    assert haiku["input_price"] == 0.10 and haiku["evaluated"] is None


def test_a_question_runs_on_the_model_and_effort_chosen_and_records_them(settings, db):
    client, agent = _client(settings, db)
    answer = client.post(
        "/api/ask", json={"question": "How many?", "model": "claude-haiku-5-5", "effort": "low"}
    ).json()
    assert agent.choices[-1] == ("claude-haiku-5-5", "low")
    assert (answer["model"], answer["effort"]) == ("claude-haiku-5-5", "low")

    summary = client.get("/api/conversations").json()[0]
    assert (summary["last_model"], summary["last_effort"]) == ("claude-haiku-5-5", "low")
    stored = client.get(f"/api/conversations/{answer['conversation_id']}").json()
    assert stored["history"][0]["answer"]["effort"] == "low"

    # A follow-up may switch model; the conversation then remembers the new one.
    client.post("/api/ask", json={"question": "And now?", "conversation_id": answer["conversation_id"]})
    assert agent.choices[-1] == ("claude-opus-5", "high")
    summary = client.get("/api/conversations").json()[0]
    assert (summary["last_model"], summary["last_effort"]) == ("claude-opus-5", "high")


def test_the_default_model_keeps_the_configured_effort_and_others_their_own(settings, db):
    settings = dataclasses.replace(settings, effort="medium")
    client, agent = _client(settings, db)
    client.post("/api/ask", json={"question": "q"})
    client.post("/api/ask", json={"question": "q", "model": "claude-sonnet-5-5"})
    assert agent.choices == [("claude-opus-5", "medium"), ("claude-sonnet-5-5", "high")]


@pytest.mark.parametrize(
    "choice",
    [
        {"model": "claude-fable-5-1"},
        {"model": "claude-haiku-4-5"},
        {"model": "gpt-5"},
        {"model": "claude-opus-5", "effort": "extreme"},
    ],
)
def test_a_model_or_effort_not_on_offer_is_refused_before_anything_runs(settings, db, choice):
    client, agent = _client(settings, db)
    response = client.post("/api/ask", json={"question": "q", **choice})
    assert response.status_code == 422
    stream = client.post("/api/ask/stream", json={"question": "q", **choice})
    assert stream.status_code == 422
    assert agent.questions == [] and client.get("/api/conversations").json() == []


def test_a_conversation_still_answering_cannot_be_deleted(settings, db):
    store = ConversationStore()
    client, _ = _client(settings, db, conversations=store)
    conversation_id, _, _ = store.begin(None, owner=client.user_id)
    response = client.delete(f"/api/conversations/{conversation_id}")
    assert response.status_code == 409 and response.json()["error"] == "busy"
    assert client.get(f"/api/conversations/{conversation_id}").json()["busy"] is True


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_managing_a_conversation_requires_a_session_and_a_well_formed_id(settings, db, method):
    client, _ = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    kwargs = {"json": {"title": "x"}} if method == "patch" else {}
    signed_out = TestClient(client.app, headers=CSRF)
    assert getattr(signed_out, method)(f"/api/conversations/{conversation_id}", **kwargs).status_code == 401
    assert getattr(client, method)("/api/conversations/not-an-id", **kwargs).status_code == 422
    assert getattr(client, method)(f"/api/conversations/{conversation_id}", **kwargs).status_code in (200, 204)


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


def test_a_report_requires_a_session_and_belongs_to_its_owner(settings, db):
    client, _ = _client(settings, db)
    conversation_id = _ask(client)["conversation_id"]
    path = f"/api/conversations/{conversation_id}/turns/1/report"
    assert TestClient(client.app).get(path).status_code == 401
    assert client.get(path).status_code == 200
    assert _second_user(client).get(path).status_code == 404


def test_each_person_sees_and_touches_only_their_own_conversations(settings, db):
    ann, agent = _client(settings, db)
    mine = _ask(ann, "Ann's question")["conversation_id"]
    bo = _second_user(ann)
    theirs = _ask(bo, "Bo's question")["conversation_id"]

    assert [item["id"] for item in ann.get("/api/conversations").json()] == [mine]
    assert [item["id"] for item in bo.get("/api/conversations").json()] == [theirs]
    assert bo.get("/api/conversations", params={"q": "Ann"}).json() == []
    for response in (
        bo.get(f"/api/conversations/{mine}"),
        bo.patch(f"/api/conversations/{mine}", json={"title": "taken"}),
        bo.patch(f"/api/conversations/{mine}", json={"pinned": True}),
        bo.delete(f"/api/conversations/{mine}"),
        bo.post("/api/ask", json={"question": "follow-up", "conversation_id": mine}),
        bo.post("/api/ask/stream", json={"question": "follow-up", "conversation_id": mine}),
    ):
        # Exactly what a conversation that does not exist gets, so nothing is revealed.
        assert response.status_code == 404 and response.json()["error"] == "unknown_conversation"
    assert ann.get(f"/api/conversations/{mine}").json()["title"] == "Ann's question"
    assert agent.questions == ["Ann's question", "Bo's question"]


def test_admins_may_pick_admin_only_models_and_nobody_else_may(settings, db):
    user, agent = _client(settings, db)
    assert "claude-fable-5-1" not in [model["id"] for model in user.get("/api/models").json()["models"]]
    assert user.post("/api/ask", json={"question": "q", "model": "claude-fable-5-1"}).status_code == 422

    admin = _second_user(user, "admin@example.org")
    user.app.state.accounts.set_role(admin.user_id, "admin")
    assert "claude-fable-5-1" in [model["id"] for model in admin.get("/api/models").json()["models"]]
    assert admin.post("/api/ask", json={"question": "q", "model": "claude-fable-5-1"}).status_code == 200
    assert agent.choices[-1] == ("claude-fable-5-1", "high")


def test_a_new_chat_starts_on_the_person_s_default_model(settings, db):
    client, agent = _client(settings, db)
    accounts = client.app.state.accounts
    accounts.update_profile(client.user_id, default_model="claude-haiku-5-5", default_effort="low")
    assert client.get("/api/models").json()["default_model"] == "claude-haiku-5-5"
    client.post("/api/ask", json={"question": "q"})
    assert agent.choices[-1] == ("claude-haiku-5-5", "low")
    # A default only admins may use falls back to the service's default.
    accounts.update_profile(client.user_id, default_model="claude-fable-5-1", default_effort="high")
    client.post("/api/ask", json={"question": "q"})
    assert agent.choices[-1] == ("claude-opus-5", "high")


def test_each_person_has_a_daily_budget_of_their_own(settings, db):
    limits = SpendingLimits(
        max_concurrent_runs=4,
        daily_token_budget=10**7,
        conversation_token_budget=10**7,
        user_daily_token_budget=100_000,
        reserve_tokens=60_000,
    )
    ann, agent = _client(settings, db, limits=limits)
    limits.settle(limits.reserve("elsewhere", user_id=ann.user_id), 50_000)
    response = ann.post("/api/ask", json={"question": "q"})
    assert response.status_code == 429 and response.json()["error"] == "user_budget"
    assert _second_user(ann).post("/api/ask", json={"question": "q"}).status_code == 200

def test_your_usage_shows_today_against_your_budget_and_this_month_by_model(settings, db):
    client, _ = _client(settings, db)
    client.post("/api/ask", json={"question": "q1"})
    client.post("/api/ask", json={"question": "q2", "model": "claude-haiku-5-5", "effort": "low"})
    client.post("/api/ask", json={"question": "q3", "model": "claude-haiku-5-5"})

    usage = client.get("/api/account/usage").json()
    assert usage["today_tokens"] == 3 * 1350 and usage["daily_budget"] == settings.user_daily_token_budget
    assert (usage["questions"], usage["input_tokens"], usage["output_tokens"]) == (3, 3600, 450)
    by_model = {item["model"]: item for item in usage["by_model"]}
    assert by_model["claude-haiku-5-5"]["questions"] == 2 and by_model["claude-haiku-5-5"]["label"] == "Haiku 5.5"
    # 1,200 in and 150 out at Opus 5's $5 and $25 per million.
    assert by_model["claude-opus-5"]["estimated_cost_usd"] == pytest.approx(0.00975)
    assert usage["estimated_cost_usd"] == pytest.approx(0.00975 + 2 * (1200 * 0.10 + 150 * 0.50) / 1e6, abs=1e-4)

    other = _second_user(client).get("/api/account/usage").json()
    assert other["questions"] == 0 and other["by_model"] == [] and other["today_tokens"] == 0


def test_a_restart_does_not_reset_a_person_s_daily_budget(settings, db):
    store = ConversationStore()
    first, _ = _client(settings, db, conversations=store)
    first.post("/api/ask", json={"question": "q"})  # 1,350 tokens, stored with the answer

    # A new service on the same store: its ledger starts empty, as after a restart.
    limits = SpendingLimits(
        max_concurrent_runs=4,
        daily_token_budget=10**7,
        conversation_token_budget=10**7,
        user_daily_token_budget=61_000,
        reserve_tokens=60_000,
    )
    again, agent = _client(settings, db, conversations=store, limits=limits)
    assert again.get("/api/account/usage").json()["today_tokens"] == 1350
    response = again.post("/api/ask", json={"question": "q"})
    assert response.status_code == 429 and response.json()["error"] == "user_budget"
    assert agent.questions == []


def test_a_question_can_be_stopped_and_nothing_is_saved_for_it(settings, db):
    import threading

    client, agent = _client(settings, db, wait_to_be_stopped=True)
    responses = []
    asking = threading.Thread(target=lambda: responses.append(client.post("/api/ask", json={"question": "q"})))
    asking.start()
    store = client.app.state.conversations
    conversation_id = None
    for _ in range(500):
        busy = [row[0] for row in store._db.execute("SELECT id FROM conversations")]
        if busy:
            conversation_id = busy[0]
            break
        time.sleep(0.01)
    assert conversation_id, "the question never started"

    stopped = client.post(f"/api/conversations/{conversation_id}/stop")
    assert stopped.status_code == 202 and stopped.json() == {"stopping": True}
    asking.join(timeout=10)
    assert responses[0].status_code == 409 and responses[0].json()["error"] == "stopped"
    assert store.get(conversation_id, owner=client.user_id).turns == ()
    assert client.post(f"/api/conversations/{conversation_id}/stop").status_code == 409, "nothing running now"
    assert _second_user(client).post(f"/api/conversations/{conversation_id}/stop").status_code == 404


def test_a_streamed_question_that_is_stopped_ends_with_a_stopped_event(settings, db):
    import threading

    client, _ = _client(settings, db, wait_to_be_stopped=True)
    holder = {}

    def ask():
        with client.stream("POST", "/api/ask/stream", json={"question": "q"}) as response:
            holder["text"] = "".join(response.iter_text())

    asking = threading.Thread(target=ask)
    asking.start()
    store = client.app.state.conversations
    for _ in range(500):
        rows = store._db.execute("SELECT id FROM conversations").fetchall()
        if rows:
            break
        time.sleep(0.01)
    client.post(f"/api/conversations/{rows[0][0]}/stop")
    asking.join(timeout=10)
    events = [block.split("\n")[0] for block in holder["text"].strip().split("\n\n")]
    assert events[0] == "event: conversation" and events[-1] == "event: error"
    assert '"error": "stopped"' in holder["text"]
