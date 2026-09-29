"""The HTTP service the web interface calls.

Like the command line, this is a thin layer over `SqlAgent.answer`. It adds nothing to the
answer except what the interface must not work out for itself: each definition's
confirmation status and the dates of the time window come from our own records, never from
the model's prose.

Run it from the Backend folder:

    .venv/bin/python -m sql_agent.serve

The agent runs in a worker thread, so a slow question does not block health checks or
other requests. Questions can belong to a conversation, so a follow-up such as "what about
heart disease?" is understood, and `/api/ask/stream` sends each step as it happens.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any, Literal

import anthropic
import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent import AgentError, AgentResult, SqlAgent, Turn, describe_failure
from .answer import describe_window
from .conversations import ConversationBusy, ConversationStore, UnknownConversation
from .runlog import log_run
from .semantic import SemanticLayer, window_bounds
from .tools import QueryRecord

MAX_QUESTION_CHARS = 2_000
CONVERSATION_ID_PATTERN = r"^[0-9a-f]{32}$"

logger = logging.getLogger(__name__)

# What each kind of failure means to a caller. The agent could not answer the question as
# asked, or the model provider failed, which is not the caller's fault.
FAILURE_STATUS = {"agent": 422, "auth": 502, "api": 502, "connection": 503}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    conversation_id: str | None = Field(
        default=None,
        pattern=CONVERSATION_ID_PATTERN,
        description="Continue this conversation. Leave it out to start a new one.",
    )


class FindingOut(BaseModel):
    statement: str
    query_numbers: list[int]


class DefinitionOut(BaseModel):
    name: str
    label: str
    status: Literal["confirmed", "assumed", "unknown"]
    """unknown means the model named a definition that does not exist."""
    summary: str


class TimeWindowOut(BaseModel):
    months: int | None
    start: date | None
    end: date | None
    description: str
    """The window as the command line shows it, with the dates computed here."""


class QueryOut(BaseModel):
    number: int | None
    sql: str
    ok: bool
    row_count: int | None
    elapsed_ms: float | None
    truncated: bool
    error: str | None
    columns: list[str]
    rows: list[list[Any]]


class IssuesOut(BaseModel):
    any: bool
    unknown_definitions: list[str]
    missing_query_numbers: list[int]
    unsupported_findings: list[str]
    window_not_in_sql: str | None


class AnswerOut(BaseModel):
    conversation_id: str
    turn: int
    """The position of this question in its conversation, starting at 1."""
    question: str
    answer: str
    """The rendered answer, the same text the command line prints."""
    structured: bool
    """False when the model answered in prose, so only `answer` is filled in."""
    headline: str | None
    findings: list[FindingOut]
    definitions_used: list[DefinitionOut]
    time_window: TimeWindowOut | None
    assumptions: list[str]
    caveats: list[str]
    queries: list[QueryOut]
    issues: IssuesOut
    as_of: date
    model: str
    elapsed_s: float
    input_tokens: int
    output_tokens: int


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    tables: int
    model: str
    as_of: date


class ColumnOut(BaseModel):
    name: str
    description: str


class TableOut(BaseModel):
    name: str
    grain: str
    description: str
    primary_key: str | None
    columns: list[ColumnOut]
    enums: dict[str, list[str]]
    notes: list[str]


class ErrorOut(BaseModel):
    error: str
    message: str


def create_app(agent: SqlAgent | None = None, conversations: ConversationStore | None = None) -> FastAPI:
    """Build the service around one agent, which is safe to share between requests.

    Each call to `answer` builds its own tools and graph, and the database opens a fresh
    read-only connection per query, so concurrent questions do not share state.
    """
    agent = agent or SqlAgent()
    conversations = ConversationStore() if conversations is None else conversations
    # Streaming runs outlive their connection, so they are held here until they finish.
    background: set[asyncio.Task] = set()
    app = FastAPI(
        title="SQL agent",
        summary="Questions about synthetic patient data, answered with traceable SQL.",
        responses={status: {"model": ErrorOut} for status in (404, 409, 422, 502, 503)},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(agent.settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'][1:]) or 'body'}: {error['msg']}"
            for error in exc.errors()
        )
        return _error(422, "invalid_request", problems)

    @app.exception_handler(AgentError)
    @app.exception_handler(anthropic.APIError)
    async def failed(_: Request, exc: Exception) -> JSONResponse:
        return _error(*_failure(exc))

    @app.exception_handler(UnknownConversation)
    async def unknown_conversation(_: Request, exc: UnknownConversation) -> JSONResponse:
        return _error(404, "unknown_conversation", "This conversation has expired or never existed. Start a new one.")

    @app.exception_handler(ConversationBusy)
    async def busy_conversation(_: Request, exc: ConversationBusy) -> JSONResponse:
        return _error(409, "busy", "This conversation is still answering the previous question.")

    @app.get("/api/health")
    def health() -> HealthOut:
        try:
            tables = len(agent.db.table_names())
        except Exception:
            tables = 0
        return HealthOut(
            status="ok" if tables else "degraded",
            database=bool(tables),
            tables=tables,
            model=agent.settings.model,
            as_of=agent.as_of,
        )

    @app.get("/api/schema")
    def schema() -> list[TableOut]:
        return schema_payload(agent)

    @app.get("/api/definitions")
    def definitions() -> list[DefinitionOut]:
        return [definition_payload(agent.layer, name) for name in agent.layer.definitions]

    @app.post("/api/ask")
    async def ask(request: AskRequest) -> AnswerOut:
        conversation_id, history, turn = conversations.begin(request.conversation_id)
        return await _run(agent, conversations, conversation_id, history, turn, request.question)

    @app.post(
        "/api/ask/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}, "description": STREAM_DESCRIPTION}},
    )
    async def ask_stream(request: AskRequest) -> StreamingResponse:
        # Claim the conversation and start the run before the stream starts, so an unknown
        # or busy conversation is an ordinary error response, and a reader that never
        # arrives cannot leave the conversation claimed.
        conversation_id, history, turn = conversations.begin(request.conversation_id)
        events = _start(agent, conversations, conversation_id, history, turn, request.question, background)
        return StreamingResponse(
            _relay(events, conversation_id, turn),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


STREAM_DESCRIPTION = """Server-sent events, read with fetch because the request is a POST.

- `conversation`: `{conversation_id, turn}`, sent first.
- `step`: `{kind, detail}` for each step, where kind is sql, sql_result, sql_error,
  describe_table or lookup_definition.
- `answer`: the same body `/api/ask` returns. The stream then ends.
- `error`: `{error, message, status}`. The stream then ends.
"""


async def _run(
    agent: SqlAgent,
    conversations: ConversationStore,
    conversation_id: str,
    history: tuple[Turn, ...],
    turn: int,
    question: str,
    on_event: Callable[[str, str], None] | None = None,
) -> AnswerOut:
    """Answer one question in a conversation that `begin` has already claimed."""
    answered = None
    try:
        result = await anyio.to_thread.run_sync(
            _answer_and_log, agent, question, history, conversation_id, on_event
        )
        answered = result.as_turn()
        return answer_payload(result, agent.layer, conversation_id=conversation_id, turn=turn)
    finally:
        conversations.finish(conversation_id, answered)


def _answer_and_log(
    agent: SqlAgent,
    question: str,
    history: tuple[Turn, ...],
    conversation_id: str,
    on_event: Callable[[str, str], None] | None,
) -> AgentResult:
    result = agent.answer(question, history=history, on_event=on_event)
    if agent.settings.log_path is not None:
        log_run(result, agent.settings.log_path, conversation_id=conversation_id)
    return result


def _start(
    agent: SqlAgent,
    conversations: ConversationStore,
    conversation_id: str,
    history: tuple[Turn, ...],
    turn: int,
    question: str,
    background: set[asyncio.Task],
) -> asyncio.Queue[tuple[str, dict]]:
    """Run the question as its own task, returning the queue its events arrive on.

    The run is not tied to the connection. If the reader goes away, the question is still
    answered, logged and added to the conversation, so a reconnecting interface finds the
    conversation free and up to date.
    """
    loop = asyncio.get_running_loop()
    events: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    def on_event(kind: str, detail: str) -> None:
        # Called from the worker thread, so the event is handed to the event loop.
        try:
            loop.call_soon_threadsafe(events.put_nowait, ("step", {"kind": kind, "detail": detail}))
        except RuntimeError:
            pass  # the event loop has closed, so nobody is listening

    async def run() -> None:
        try:
            answer = await _run(agent, conversations, conversation_id, history, turn, question, on_event)
            events.put_nowait(("answer", answer.model_dump(mode="json")))
        except (AgentError, anthropic.APIError) as exc:
            status, kind, message = _failure(exc)
            events.put_nowait(("error", {"error": kind, "message": message, "status": status}))
        except Exception:
            logger.exception("Streaming question failed")
            events.put_nowait(("error", {"error": "internal", "message": "The service failed unexpectedly.", "status": 500}))

    task = asyncio.create_task(run())
    background.add(task)
    task.add_done_callback(background.discard)
    return events


async def _relay(events: asyncio.Queue[tuple[str, dict]], conversation_id: str, turn: int) -> AsyncIterator[str]:
    """Server-sent events for one run, ending with its answer or its error."""
    yield _sse("conversation", {"conversation_id": conversation_id, "turn": turn})
    while True:
        event, data = await events.get()
        yield _sse(event, data)
        if event in ("answer", "error"):
            return


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _failure(exc: Exception) -> tuple[int, str, str]:
    """The status, kind and message for a failure of the agent or of the model provider."""
    kind, message = describe_failure(exc) or ("api", "The Anthropic API returned an unexpected response.")
    return FAILURE_STATUS[kind], kind, message


def _error(status: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorOut(error=kind, message=message).model_dump())


def schema_payload(agent: SqlAgent) -> list[TableOut]:
    """The documented catalog. Blocked columns are dropped even if someone documents one."""
    tables = []
    for doc in agent.layer.tables.values():
        blocked = agent.db.blocked_columns_for(doc.name)
        tables.append(
            TableOut(
                name=doc.name,
                grain=doc.grain,
                description=doc.description,
                primary_key=doc.primary_key,
                columns=[
                    ColumnOut(name=name, description=text)
                    for name, text in doc.columns.items()
                    if name.lower() not in blocked
                ],
                enums={column: list(values) for column, values in doc.enums.items() if column.lower() not in blocked},
                notes=list(doc.notes),
            )
        )
    return tables


def definition_payload(layer: SemanticLayer, name: str) -> DefinitionOut:
    """A definition as recorded in the semantic layer, or marked unknown if it is not there."""
    definition = layer.definitions.get(name.lower())
    if definition is None:
        return DefinitionOut(name=name, label=name, status="unknown", summary="")
    return DefinitionOut(
        name=definition.name,
        label=definition.label,
        status="confirmed" if definition.status == "confirmed" else "assumed",
        summary=definition.summary,
    )


def answer_payload(result: AgentResult, layer: SemanticLayer, *, conversation_id: str, turn: int) -> AnswerOut:
    structured = result.structured
    time_window = None
    if structured is not None:
        window = structured.time_window
        start = end = None
        if window.months:
            start, end = window_bounds(result.as_of, window.months)
        time_window = TimeWindowOut(
            months=window.months or None,
            start=start,
            end=end,
            description=describe_window(window, result.as_of),
        )
    issues = result.issues
    return AnswerOut(
        conversation_id=conversation_id,
        turn=turn,
        question=result.question,
        answer=result.answer,
        structured=structured is not None,
        headline=structured.headline if structured else None,
        findings=[
            FindingOut(statement=finding.statement, query_numbers=finding.query_numbers)
            for finding in (structured.findings if structured else [])
        ],
        definitions_used=[definition_payload(layer, name) for name in (structured.definitions_used if structured else [])],
        time_window=time_window,
        assumptions=list(structured.assumptions) if structured else [],
        caveats=list(structured.caveats) if structured else [],
        queries=[query_payload(record) for record in result.queries],
        issues=IssuesOut(
            any=issues.any,
            unknown_definitions=list(issues.unknown_definitions),
            missing_query_numbers=list(issues.missing_query_numbers),
            unsupported_findings=list(issues.unsupported_findings),
            window_not_in_sql=issues.window_not_in_sql,
        ),
        as_of=result.as_of,
        model=result.model,
        elapsed_s=round(result.elapsed_s, 2),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


def query_payload(record: QueryRecord) -> QueryOut:
    return QueryOut(
        number=record.number,
        sql=record.sql,
        ok=record.ok,
        row_count=record.row_count,
        elapsed_ms=record.elapsed_ms,
        truncated=record.truncated,
        error=record.error,
        columns=list(record.columns),
        rows=[[_cell(value) for value in row] for row in record.rows],
    )


def _cell(value: Any) -> Any:
    """SQLite values as JSON. Binary values are described rather than sent."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    return value
