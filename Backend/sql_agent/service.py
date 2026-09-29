"""The HTTP service the web interface calls.

Like the command line, this is a thin layer over `SqlAgent.answer`. It adds nothing to the
answer except what the interface must not work out for itself: each definition's
confirmation status and the dates of the time window come from our own records, never from
the model's prose.

Run it from the Backend folder:

    .venv/bin/python -m sql_agent.serve

The agent runs in a worker thread, so a slow question does not block health checks or
other requests.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

import anthropic
import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agent import AgentError, AgentResult, SqlAgent, describe_failure
from .answer import describe_window
from .runlog import log_run
from .semantic import SemanticLayer, window_bounds
from .tools import QueryRecord

MAX_QUESTION_CHARS = 2_000

# What each kind of failure means to a caller. The agent could not answer the question as
# asked, or the model provider failed, which is not the caller's fault.
FAILURE_STATUS = {"agent": 422, "auth": 502, "api": 502, "connection": 503}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


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


def create_app(agent: SqlAgent | None = None) -> FastAPI:
    """Build the service around one agent, which is safe to share between requests.

    Each call to `answer` builds its own tools and graph, and the database opens a fresh
    read-only connection per query, so concurrent questions do not share state.
    """
    agent = agent or SqlAgent()
    app = FastAPI(
        title="SQL agent",
        summary="Questions about synthetic patient data, answered with traceable SQL.",
        responses={422: {"model": ErrorOut}, 502: {"model": ErrorOut}, 503: {"model": ErrorOut}},
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
        kind, message = describe_failure(exc) or ("api", "The Anthropic API returned an unexpected response.")
        return _error(FAILURE_STATUS[kind], kind, message)

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
        result = await anyio.to_thread.run_sync(_answer_and_log, agent, request.question)
        return answer_payload(result, agent.layer)

    return app


def _answer_and_log(agent: SqlAgent, question: str) -> AgentResult:
    result = agent.answer(question)
    if agent.settings.log_path is not None:
        log_run(result, agent.settings.log_path)
    return result


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


def answer_payload(result: AgentResult, layer: SemanticLayer) -> AnswerOut:
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
