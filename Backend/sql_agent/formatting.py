"""Turning query results into text for a terminal or for the model to read."""

from __future__ import annotations

MAX_CELL_CHARS = 60


def format_table(columns: tuple[str, ...], rows: tuple[tuple, ...], *, max_cell: int = MAX_CELL_CHARS) -> str:
    """Render columns and rows as a plain text table."""
    if not columns:
        return "(no columns)"

    def cell(value: object) -> str:
        text = "" if value is None else str(value)
        return text[: max_cell - 1] + "…" if len(text) > max_cell else text

    header = [cell(column) for column in columns]
    body = [[cell(value) for value in row] for row in rows]
    widths = [len(value) for value in header]
    for row in body:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def line(values: list[str]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values)).rstrip()

    return "\n".join([line(header), "  ".join("-" * width for width in widths), *(line(row) for row in body)])
