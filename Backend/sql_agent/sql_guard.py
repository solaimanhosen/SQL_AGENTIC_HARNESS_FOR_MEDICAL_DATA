"""Static checks on model-written SQL, applied before the database is opened.

This is one of three independent layers. `db.py` adds a SQLite authorizer that rejects
anything but reads inside the engine, and the connection itself is opened read-only.
No single layer is trusted on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

DIALECT = "sqlite"

# A statement is allowed only when its root node is one of these.
ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)

# Rejected anywhere in the tree, including inside common table expressions and subqueries.
# exp.Command is sqlglot's catch-all for statements it does not model, such as VACUUM.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Attach, exp.Detach, exp.Pragma, exp.Command,
    exp.Transaction, exp.Commit, exp.Rollback, exp.Set,
)

_READABLE_NAMES = {
    exp.Insert: "an INSERT",
    exp.Update: "an UPDATE",
    exp.Delete: "a DELETE",
    exp.Drop: "a DROP",
    exp.Create: "a CREATE",
    exp.Alter: "an ALTER",
    exp.TruncateTable: "a TRUNCATE",
    exp.Attach: "an ATTACH",
    exp.Detach: "a DETACH",
    exp.Pragma: "a PRAGMA",
    exp.Transaction: "a transaction statement",
    exp.Commit: "a COMMIT",
    exp.Rollback: "a ROLLBACK",
    exp.Set: "a SET",
}


class UnsafeQueryError(ValueError):
    """The query is not a single read-only SELECT. The caller should rewrite it."""


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    """The original text, with surrounding whitespace and any trailing semicolon removed."""
    tables: tuple[str, ...]
    """Table names referenced anywhere in the statement, for logging and later checks."""


def validate_query(sql: str) -> ValidatedQuery:
    """Return the validated query, or raise UnsafeQueryError explaining what to change."""
    text = (sql or "").strip()
    while text.endswith(";"):
        text = text[:-1].strip()
    if not text:
        raise UnsafeQueryError("The query is empty.")

    try:
        statements = [statement for statement in sqlglot.parse(text, dialect=DIALECT) if statement is not None]
    except sqlglot.ParseError as exc:
        raise UnsafeQueryError(f"The query is not valid SQLite SQL: {exc}") from None

    if len(statements) != 1:
        raise UnsafeQueryError(
            f"Send one statement at a time. This query contains {len(statements)} statements."
        )

    root = statements[0]
    if not isinstance(root, ALLOWED_ROOTS):
        raise UnsafeQueryError(
            f"Only read-only SELECT statements are allowed, and this is {_describe(root)}."
        )
    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(
                f"Only read-only SELECT statements are allowed. This query contains {_describe(node)}."
            )

    tables = tuple(sorted({table.name.lower() for table in root.find_all(exp.Table) if table.name}))
    return ValidatedQuery(sql=text, tables=tables)


def _describe(node: exp.Expression) -> str:
    for node_type, description in _READABLE_NAMES.items():
        if isinstance(node, node_type):
            return description
    if isinstance(node, exp.Command):
        keyword = str(node.this).strip() if node.this else "statement"
        return f"an unsupported statement ({keyword.upper()})"
    return f"an unsupported statement ({type(node).__name__.upper()})"
