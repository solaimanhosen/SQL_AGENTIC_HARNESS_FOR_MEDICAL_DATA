"""The answer as it leaves the agent: the shape the service sends, stores and reports.

The HTTP service, the stored conversations, the command line's report and the report
endpoint all use this one shape, so an answer reads the same wherever it is seen. Each
definition's status and the dates of the time window are filled in here from our own
records, never from the model's prose.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from .agent import AgentResult
from .answer import describe_window
from .charts import Chart
from .semantic import SemanticLayer, window_bounds
from .tools import AnalysisInfo, QueryRecord


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


class AnalysisOut(BaseModel):
    tool: Literal["summarize", "trend", "compare_groups"]
    label: str
    """A short description, such as "trend by month over 5,571 rows"."""
    parameters: dict[str, Any]
    source_rows: int
    """Rows the SQL returned. The query's own rows are the table computed from them."""
    summary: list[str]
    """What the computed table shows. Every figure in it was computed by the service."""


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
    analysis: AnalysisOut | None = None
    """Set when an analytics tool produced this result. Answers stored before it existed lack it."""


class IssuesOut(BaseModel):
    any: bool
    unknown_definitions: list[str]
    missing_query_numbers: list[int]
    unsupported_findings: list[str]
    window_not_in_sql: str | None
    chart_problems: list[str] = []
    """Charts asked for that could not be drawn from the run, each with its reason."""


class SeriesOut(BaseModel):
    name: str
    values: list[float | None]
    """One value per category, in the order of the chart's x. None is a gap."""


class ChartOut(BaseModel):
    kind: Literal["bar", "line"]
    title: str
    """Written by the model. Every value is read from the cited query's rows."""
    query_number: int
    x_label: str
    y_label: str
    x: list[str]
    series: list[SeriesOut]


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
    charts: list[ChartOut] = []
    """Drawn only from the run. Answers stored before charts existed have none."""
    as_of: date
    model: str
    elapsed_s: float
    input_tokens: int
    output_tokens: int



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
            chart_problems=list(issues.chart_problems),
        ),
        charts=[chart_payload(chart) for chart in result.charts],
        as_of=result.as_of,
        model=result.model,
        elapsed_s=round(result.elapsed_s, 2),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


def chart_payload(chart: Chart) -> ChartOut:
    return ChartOut(
        kind=chart.kind,
        title=chart.title,
        query_number=chart.query_number,
        x_label=chart.x_label,
        y_label=chart.y_label,
        x=list(chart.x),
        series=[SeriesOut(name=series.name, values=list(series.values)) for series in chart.series],
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
        analysis=analysis_payload(record.analysis) if record.analysis else None,
    )


def analysis_payload(info: AnalysisInfo) -> AnalysisOut:
    return AnalysisOut(
        tool=info.tool,
        label=info.describe(),
        parameters=dict(info.parameters),
        source_rows=info.source_rows,
        summary=list(info.summary),
    )


def _cell(value: Any) -> Any:
    """SQLite values as JSON. Binary values are described rather than sent."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    return value
