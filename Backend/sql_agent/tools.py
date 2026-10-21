"""The tools the agent can call.

Tools are built per question so every query is recorded as it runs. What the user is shown
afterwards is that recording, not SQL the model claims to have run.

The analytics tools run their own SQL through the same read-only database, compute with
analytics.py and record the computed table as a numbered query, so a finding cites a
statistic exactly as it cites any other result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, Callable, Literal

from langchain_core.tools import tool

from . import analytics
from .analytics import AnalysisError, AnalysisResult
from .db import QueryExecutionError, ReadOnlyDatabase
from .formatting import format_table
from .semantic import SemanticLayer

# Tool output goes straight into the model's context, so it is capped.
MAX_RESULT_CHARS = 6_000


@dataclass(frozen=True)
class AnalysisInfo:
    """What an analytics tool computed, and from how many rows."""

    tool: str
    parameters: dict[str, Any]
    source_rows: int
    """Rows the SQL returned. They are not kept: the SQL is, so the result can be reproduced."""
    summary: tuple[str, ...]
    """What the computed table shows, in sentences whose figures were all computed here."""

    def describe(self) -> str:
        """A short label, such as "trend by month over 5,571 rows"."""
        options = self.parameters
        if self.tool == "summarize":
            label = f"summary of {options['value_column']}"
            if options.get("group_column"):
                label += f" by {options['group_column']}"
        elif self.tool == "trend":
            measure = "" if options["measure"] == "count" else f" of {options['measure']} {options['value_column']}"
            label = f"trend{measure} by {options['period']}"
        else:
            label = f"comparison of {options['measure']} of {options['value_column']} by {options['group_column']}"
        return f"{label} over {self.source_rows:,} rows"


@dataclass(frozen=True)
class QueryRecord:
    """One attempt to run SQL, successful or not."""

    sql: str
    number: int | None = None
    """Position among the successful queries of a run, used when citing a result."""
    row_count: int | None = None
    elapsed_ms: float | None = None
    truncated: bool = False
    error: str | None = None
    columns: tuple[str, ...] = ()
    rows: tuple[tuple, ...] = ()
    """The rows returned, already capped at the row limit, so the evidence can be shown.

    For an analysis these are the computed table, which is what a citation points at.
    """
    analysis: AnalysisInfo | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class ToolBox:
    """The tools for one question, plus the record of what they did."""

    db: ReadOnlyDatabase
    layer: SemanticLayer
    as_of: date
    on_event: Callable[[str, str], None] | None = None
    queries: list[QueryRecord] = field(default_factory=list)

    def _announce(self, kind: str, detail: str) -> None:
        if self.on_event is not None:
            self.on_event(kind, detail)

    def tools(self) -> list:
        return [
            self._run_sql_tool(),
            self._describe_table_tool(),
            self._lookup_definition_tool(),
            self._summarize_tool(),
            self._trend_tool(),
            self._compare_groups_tool(),
        ]

    def _next_number(self) -> int:
        return sum(1 for record in self.queries if record.ok) + 1

    def _fail(self, sql: str, message: str) -> str:
        self.queries.append(QueryRecord(sql=sql.strip(), error=message))
        self._announce("sql_error", message)
        return f"ERROR: {message}"

    def _run_sql_tool(self):
        @tool("run_sql", parse_docstring=False)
        def run_sql(query: str) -> str:
            """Run one read-only SELECT statement and return the rows.

            Only a single SELECT is allowed; writes and multiple statements are rejected.
            Results are capped, so aggregate in SQL rather than listing many rows. If the
            statement fails, the error explains what to change.

            Each successful result is labelled with a query number. Cite those numbers in
            your findings so the reader can trace every figure back to the SQL that ran.
            """
            self._announce("sql", query)
            try:
                result = self.db.run_query(query)
            except Exception as exc:
                return self._fail(query, f"{type(exc).__name__}: {exc}")

            number = self._next_number()
            self.queries.append(
                QueryRecord(
                    sql=result.sql,
                    number=number,
                    row_count=result.row_count,
                    elapsed_ms=result.elapsed_ms,
                    truncated=result.truncated,
                    columns=result.columns,
                    rows=result.rows,
                )
            )
            self._announce("sql_result", f"{result.row_count} rows in {result.elapsed_ms:.0f} ms")

            header = f"Query {number} | {result.row_count} rows in {result.elapsed_ms:.0f} ms"
            if result.truncated:
                header += (
                    f". Only the first {self.db.max_rows} rows are shown and more matched, "
                    "so aggregate in SQL instead of listing rows"
                )
            body = format_table(result.columns, result.rows)
            text = f"{header}\n\n{body}"
            if len(text) > MAX_RESULT_CHARS:
                text = text[:MAX_RESULT_CHARS] + "\n... output truncated. Return fewer columns or aggregate."
            return text

        return run_sql

    def _describe_table_tool(self):
        @tool("describe_table", parse_docstring=False)
        def describe_table(tables: str) -> str:
            """Describe one or more tables, including what each column means.

            Pass a single table name or several separated by commas. Use this when the
            overview in the instructions does not say enough about a column.
            """
            self._announce("describe_table", tables)
            blocks = []
            for name in [part.strip() for part in tables.split(",") if part.strip()]:
                try:
                    doc = self.layer.table(name)
                except KeyError as exc:
                    blocks.append(str(exc))
                    continue
                lines = [doc.render_detail()]
                try:
                    live_columns = self.db.table_columns(doc.name)
                except QueryExecutionError:
                    lines.append("This table is documented but is not present in the database.")
                else:
                    undocumented = sorted(
                        {column.name.lower() for column in live_columns} - {column.lower() for column in doc.columns}
                    )
                    if undocumented:
                        lines.append(
                            "Other columns that exist but are not documented: " + ", ".join(undocumented)
                        )
                blocks.append("\n".join(lines))
            return "\n\n".join(blocks) if blocks else "Name at least one table."

        return describe_table

    def _lookup_definition_tool(self):
        @tool("lookup_definition", parse_docstring=False)
        def lookup_definition(name: str) -> str:
            """Show the full definition of a term, including its codes and warnings.

            The instructions already list every definition in short form. Use this when you
            need the code list, the excluded codes or the notes behind one of them.
            """
            self._announce("lookup_definition", name)
            try:
                definition = self.layer.definition(name)
            except KeyError as exc:
                return str(exc)
            return definition.render(self.as_of)

        return lookup_definition

    def _analyse(
        self, name: str, sql: str, parameters: dict[str, Any], compute: Callable[[tuple, tuple], AnalysisResult]
    ) -> str:
        """Run the SQL with the analysis cap, compute, and record the computed table."""
        self._announce("sql", sql)
        cap = self.db.analysis_max_rows
        try:
            result = self.db.run_query(sql, max_rows=cap)
        except Exception as exc:
            return self._fail(sql, f"{type(exc).__name__}: {exc}")
        if result.truncated:
            return self._fail(
                sql,
                f"AnalysisError: the query returned more than {cap:,} rows, so {name} would only see part of "
                "the data. Filter in SQL, or return fewer rows per item.",
            )
        try:
            computed = compute(result.columns, result.rows)
        except AnalysisError as exc:
            return self._fail(sql, f"AnalysisError: {exc}")

        number = self._next_number()
        info = AnalysisInfo(tool=name, parameters=parameters, source_rows=result.row_count, summary=computed.summary)
        self.queries.append(
            QueryRecord(
                sql=result.sql,
                number=number,
                row_count=len(computed.rows),
                elapsed_ms=result.elapsed_ms,
                columns=computed.columns,
                rows=computed.rows,
                analysis=info,
            )
        )
        self._announce("analysis", info.describe())
        text = "\n\n".join(
            [
                f"Query {number} | {info.describe()}",
                format_table(computed.columns, computed.rows),
                "\n".join(f"- {line}" for line in computed.summary),
            ]
        )
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n... output truncated. Use fewer groups or a longer period."
        return text

    def _summarize_tool(self):
        cap = self.db.analysis_max_rows

        @tool(
            "summarize",
            description=(
                "Summary statistics of one numeric column: count, mean, standard deviation, minimum, "
                "quartiles, median and maximum, overall or for each group. Write a SELECT returning one "
                "row per value, such as one row per lab measurement, and do not aggregate it first. "
                f"Up to {cap:,} rows are read and only the computed table comes back, so use this for "
                "medians, spreads and averages over many rows. Numbers stored as text are read as "
                "numbers; other values are counted and left out."
            ),
        )
        def summarize(
            sql: Annotated[str, "One read-only SELECT returning a row per value."],
            value_column: Annotated[str, "The column holding the numbers."],
            group_column: Annotated[str | None, "Optional column of group labels, at most 50 groups."] = None,
        ) -> str:
            return self._analyse(
                "summarize",
                sql,
                {"value_column": value_column, "group_column": group_column},
                lambda columns, rows: analytics.summarize(
                    columns, rows, value_column=value_column, group_column=group_column
                ),
            )

        return summarize

    def _trend_tool(self):
        cap = self.db.analysis_max_rows

        @tool(
            "trend",
            description=(
                "A value per month, quarter or year, and whether it is increasing, decreasing or shows "
                "no clear trend, judged by a Mann-Kendall test. Write a SELECT returning one row per "
                "event with its date, such as one row per encounter, and do not group it first. "
                "count counts those rows; sum and mean use value_column. A period the data only "
                "partly covers, such as the month holding the as-of date, is marked incomplete and "
                "left out of the verdict. If your SQL keeps dates from partway through a period, as "
                "a last-12-months filter does, pass the first date it keeps as start. "
                f"Up to {cap:,} rows are read."
            ),
        )
        def trend(
            sql: Annotated[str, "One read-only SELECT returning a row per event, with its date."],
            date_column: Annotated[str, "The column holding each row's date."],
            period: Literal["month", "quarter", "year"] = "month",
            measure: Literal["count", "sum", "mean"] = "count",
            value_column: Annotated[str | None, "The column to sum or average. Leave it out for count."] = None,
            start: Annotated[
                str | None, "The first date the SQL keeps, as YYYY-MM-DD, when it filters by date."
            ] = None,
        ) -> str:
            return self._analyse(
                "trend",
                sql,
                {
                    "date_column": date_column,
                    "period": period,
                    "measure": measure,
                    "value_column": value_column,
                    "start": start,
                },
                lambda columns, rows: analytics.trend(
                    columns,
                    rows,
                    date_column=date_column,
                    as_of=self.as_of,
                    value_column=value_column,
                    period=period,
                    measure=measure,
                    start=start,
                ),
            )

        return trend

    def _compare_groups_tool(self):
        cap = self.db.analysis_max_rows

        @tool(
            "compare_groups",
            description=(
                "Compare groups, such as diabetic and non-diabetic patients. With measure rate, each "
                "row holds 1 when the event happened and 0 when it did not, one row per member, and "
                "each group's share is given with a 95% interval. With measure mean, each row holds "
                "a value. With exactly two groups the difference is tested: Fisher's exact test for "
                "rates, a permutation test for means. Groups under 20 are flagged as small. "
                f"Up to {cap:,} rows are read."
            ),
        )
        def compare_groups(
            sql: Annotated[str, "One read-only SELECT returning a row per member, with its group and value."],
            group_column: Annotated[str, "The column holding each row's group label, at most 50 groups."],
            value_column: Annotated[str, "The column holding 1 or 0 for rate, or the number for mean."],
            measure: Literal["rate", "mean"] = "rate",
        ) -> str:
            return self._analyse(
                "compare_groups",
                sql,
                {"group_column": group_column, "value_column": value_column, "measure": measure},
                lambda columns, rows: analytics.compare_groups(
                    columns, rows, group_column=group_column, value_column=value_column, measure=measure
                ),
            )

        return compare_groups
