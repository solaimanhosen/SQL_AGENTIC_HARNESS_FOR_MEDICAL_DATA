"""The tools the agent can call.

Tools are built per question so every query is recorded as it runs. What the user is shown
afterwards is that recording, not SQL the model claims to have run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from langchain_core.tools import tool

from .db import QueryExecutionError, ReadOnlyDatabase
from .formatting import format_table
from .semantic import SemanticLayer

# Tool output goes straight into the model's context, so it is capped.
MAX_RESULT_CHARS = 6_000


@dataclass(frozen=True)
class QueryRecord:
    """One attempt to run SQL, successful or not."""

    sql: str
    row_count: int | None = None
    elapsed_ms: float | None = None
    truncated: bool = False
    error: str | None = None

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
        return [self._run_sql_tool(), self._describe_table_tool(), self._lookup_definition_tool()]

    def _run_sql_tool(self):
        @tool("run_sql", parse_docstring=False)
        def run_sql(query: str) -> str:
            """Run one read-only SELECT statement and return the rows.

            Only a single SELECT is allowed; writes and multiple statements are rejected.
            Results are capped, so aggregate in SQL rather than listing many rows. If the
            statement fails, the error explains what to change.
            """
            self._announce("sql", query)
            try:
                result = self.db.run_query(query)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.queries.append(QueryRecord(sql=query.strip(), error=message))
                self._announce("sql_error", message)
                return f"ERROR: {message}"

            self.queries.append(
                QueryRecord(
                    sql=result.sql,
                    row_count=result.row_count,
                    elapsed_ms=result.elapsed_ms,
                    truncated=result.truncated,
                )
            )
            self._announce("sql_result", f"{result.row_count} rows in {result.elapsed_ms:.0f} ms")

            header = f"{result.row_count} rows in {result.elapsed_ms:.0f} ms"
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
