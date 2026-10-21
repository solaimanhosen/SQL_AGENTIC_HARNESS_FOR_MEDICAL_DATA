"""The shape of an answer, and how it is rendered.

The model fills in a structured answer rather than free prose. That lets this module
render the parts that must be exact, such as which definitions were used and whether they
are confirmed, instead of trusting the model to describe them correctly. Each finding
carries the numbers of the queries behind it, so every figure can be traced to SQL that
actually ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from langchain_core.utils.json import parse_partial_json
from pydantic import BaseModel, Field

from .charts import MAX_CHARTS, resolve_charts
from .semantic import SemanticLayer, window_bounds
from .tools import QueryRecord


NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[float]:
    """Every number in the text, with thousands separators removed."""
    values = set()
    for token in NUMBER_PATTERN.findall(text or ""):
        try:
            values.add(float(token.replace(",", "")))
        except ValueError:
            continue
    return values


class Finding(BaseModel):
    statement: str = Field(description="One sentence giving a single result, including the number.")
    query_numbers: list[int] = Field(
        default_factory=list,
        description="Numbers of the queries this came from, as labelled in the run_sql results.",
    )


class TimeWindow(BaseModel):
    """The period an answer covers.

    When a standard window was used, the model gives the number of months and this code
    computes the dates, so the range shown always matches the range the SQL selected.
    """

    months: int | None = Field(
        default=None,
        description="Number of months back from the as-of date, when you restricted by date. Otherwise null.",
    )
    description: str = Field(
        default="",
        description="Used when months is null: 'all dates in the data', or the custom period you applied.",
    )


class ChartRequest(BaseModel):
    """A chart of one query's result. The values are read from that result, never given here."""

    query_number: int = Field(description="The query whose rows are plotted, as labelled in the results.")
    kind: Literal["bar", "line"] = Field(
        description="bar to compare categories or groups, line for a value over time."
    )
    x: str = Field(description="The column holding the categories or periods, in the order to plot them.")
    y: list[str] = Field(description="The numeric columns to plot, each drawn as one series.")
    series: str | None = Field(
        default=None,
        description="Optional column whose values split a single y column into series, such as one line per group.",
    )
    title: str = Field(description="A short title saying what is plotted.")


class StructuredAnswer(BaseModel):
    """An answer broken into parts so a reader can check every number."""

    headline: str = Field(description="One or two sentences answering the question directly, with the key number.")
    findings: list[Finding] = Field(
        default_factory=list, description="The supporting results, one sentence each, each tied to its queries."
    )
    definitions_used: list[str] = Field(
        default_factory=list,
        description="Names of shared definitions applied, such as diabetes or emergency_visit. Empty if none applied.",
    )
    time_window: TimeWindow = Field(
        default_factory=TimeWindow, description="The period the answer covers."
    )
    assumptions: list[str] = Field(
        default_factory=list, description="Choices you made that the user did not specify, such as how a term was read."
    )
    caveats: list[str] = Field(
        default_factory=list, description="Only what changes how the answer should be read, such as a small cohort."
    )
    charts: list[ChartRequest] = Field(
        default_factory=list,
        description=(
            f"At most {MAX_CHARTS} charts, only when a picture helps, such as a trend over time or several "
            "groups side by side. Leave it empty when the answer is one or two numbers."
        ),
    )


@dataclass(frozen=True)
class Draft:
    """The answer while the model is still writing it: text only, and not yet checked.

    It carries no citations, definitions or dates. Those are exact, so they are shown only
    once the answer is complete and has been checked against the run.
    """

    headline: str = ""
    findings: tuple[str, ...] = ()


def draft_from_partial(text: str) -> Draft | None:
    """Read a draft out of a structured answer that has only partly arrived, if it holds one."""
    if not text.lstrip().startswith("{"):
        return None
    try:
        partial = parse_partial_json(text)
    except ValueError:
        return None
    if not isinstance(partial, dict):
        return None
    headline = partial.get("headline")
    findings = partial.get("findings")
    statements = tuple(
        finding["statement"].strip()
        for finding in (findings if isinstance(findings, list) else [])
        if isinstance(finding, dict) and isinstance(finding.get("statement"), str) and finding["statement"].strip()
    )
    draft = Draft(headline=headline.strip() if isinstance(headline, str) else "", findings=statements)
    return draft if draft.headline or draft.findings else None


@dataclass(frozen=True)
class AnswerIssues:
    """Problems found by checking the model's answer against what actually happened."""

    unknown_definitions: tuple[str, ...] = ()
    missing_query_numbers: tuple[int, ...] = ()
    unsupported_findings: tuple[str, ...] = ()
    window_not_in_sql: str | None = None
    chart_problems: tuple[str, ...] = ()
    """Charts that could not be drawn from the run, each with its reason."""

    @property
    def any(self) -> bool:
        return bool(
            self.unknown_definitions
            or self.missing_query_numbers
            or self.unsupported_findings
            or self.window_not_in_sql
            or self.chart_problems
        )


def describe_window(window: TimeWindow, as_of: object) -> str:
    """The window as text, with the dates computed here rather than written by the model."""
    if window.months:
        start, end = window_bounds(str(as_of), window.months)
        return f"last {window.months} months ({start} to {end})"
    return window.description.strip() or "not stated"


def check_answer(
    answer: StructuredAnswer, queries: tuple[QueryRecord, ...], layer: SemanticLayer, *, as_of: object = None
) -> AnswerIssues:
    """Compare the answer with the run. Nothing here trusts the model's own account."""
    available = {record.number for record in queries if record.ok and record.number is not None}
    referenced = {number for finding in answer.findings for number in finding.query_numbers}
    window_problem = None
    months = answer.time_window.months
    if months and as_of is not None:
        start, end = window_bounds(str(as_of), months)
        markers = (f"-{months} months", start.isoformat(), end.isoformat())
        if not any(marker in record.sql for record in queries if record.ok for marker in markers):
            window_problem = f"last {months} months is claimed but no query filters on those dates"
    _, chart_problems = resolve_charts(answer.charts, queries)
    return AnswerIssues(
        window_not_in_sql=window_problem,
        chart_problems=chart_problems,
        unknown_definitions=tuple(name for name in answer.definitions_used if name.lower() not in layer.definitions),
        missing_query_numbers=tuple(sorted(referenced - available)),
        # A finding that states a figure must show where the figure came from. A
        # qualitative statement, such as explaining that a request was refused, needs no
        # query behind it.
        unsupported_findings=tuple(
            finding.statement
            for finding in answer.findings
            if not finding.query_numbers and numbers_in(finding.statement)
        ),
    )


def render_answer(
    answer: StructuredAnswer, queries: tuple[QueryRecord, ...], layer: SemanticLayer, *, as_of: object
) -> str:
    """Render the answer for a terminal, with the exact parts filled in from our own records."""
    lines = [answer.headline.strip()]

    if answer.findings:
        lines += ["", "Findings"]
        for finding in answer.findings:
            reference = (
                " [query " + ", ".join(str(number) for number in finding.query_numbers) + "]"
                if finding.query_numbers
                else " [no query cited]"
            )
            lines.append(f"  - {finding.statement.strip()}{reference}")

    charts, _ = resolve_charts(answer.charts, queries)
    if charts:
        lines += ["", "Charts"]
        lines += [f"  - {chart.title}: {chart.kind} chart [query {chart.query_number}]" for chart in charts]

    lines += ["", f"Time window: {describe_window(answer.time_window, as_of)}", f"As-of date: {as_of}"]

    if answer.definitions_used:
        lines += ["", "Definitions used"]
        for name in answer.definitions_used:
            definition = layer.definitions.get(name.lower())
            if definition is None:
                lines.append(f"  - {name}: not a shared definition, so the agent chose its own meaning")
                continue
            status = "confirmed" if definition.status == "confirmed" else "assumed, not yet confirmed"
            lines.append(f"  - {definition.label} ({definition.name}, {status}): {definition.summary}")

    for title, items in (("Assumptions", answer.assumptions), ("Caveats", answer.caveats)):
        if items:
            lines += ["", title]
            lines += [f"  - {item.strip()}" for item in items]

    return "\n".join(lines)
