"""The semantic layer: what the tables mean and how the shared terms are defined.

Two YAML files hold the content. `semantic/schema_catalog.yaml` describes tables, columns,
join keys and allowed values. `semantic/definitions.yaml` encodes the terms people ask
about, such as which codes count as diabetes and what an emergency visit is.

Both are rendered into text for the agent's prompt, and both are checked against the real
database. A definition whose numbers stop matching the data fails the test suite instead of
quietly changing answers.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .config import Settings
from .db import ReadOnlyDatabase

SEMANTIC_DIR = Path(__file__).parent / "semantic"
CATALOG_PATH = SEMANTIC_DIR / "schema_catalog.yaml"
DEFINITIONS_PATH = SEMANTIC_DIR / "definitions.yaml"


@dataclass(frozen=True)
class Check:
    """One assertion about a definition, run against the real data."""

    description: str
    sql: str
    equals: int | None = None
    minimum: int | None = None
    maximum: int | None = None

    @property
    def expectation(self) -> str:
        if self.equals is not None:
            return f"= {self.equals}"
        bounds = []
        if self.minimum is not None:
            bounds.append(f">= {self.minimum}")
        if self.maximum is not None:
            bounds.append(f"<= {self.maximum}")
        return " and ".join(bounds) if bounds else "any value"

    def holds_for(self, value: object) -> bool:
        if not isinstance(value, (int, float)):
            return False
        if self.equals is not None and value != self.equals:
            return False
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        return True


@dataclass(frozen=True)
class Definition:
    name: str
    label: str
    kind: str
    """cohort returns patient ids, filter is a WHERE predicate, expression is a value, grade_table is a banding."""
    status: str
    """confirmed means Telligen agreed it. assumed means it still needs review."""
    summary: str
    applies_to: str
    sql: str
    codes: dict[int, str] = field(default_factory=dict)
    excludes: dict[int, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    bands: tuple[dict, ...] = ()
    checks: tuple[Check, ...] = ()

    def resolved_sql(self, as_of: date | str) -> str:
        return self.sql.replace("{as_of}", str(as_of)).strip()

    def resolved_check_sql(self, check: Check, as_of: date | str) -> str:
        return check.sql.replace("{sql}", self.sql.strip()).replace("{as_of}", str(as_of)).strip()

    def render(self, as_of: date | str, *, compact: bool = False) -> str:
        marker = "" if self.status == "confirmed" else " [assumed, not yet confirmed]"
        lines = [f"### {self.label} ({self.name}){marker}", self.summary, "", "```sql", self.resolved_sql(as_of), "```"]
        if compact:
            return "\n".join(lines)
        if self.codes:
            lines.append("Codes: " + "; ".join(f"{code} {name}" for code, name in self.codes.items()))
        if self.excludes:
            lines.append("Excluded: " + "; ".join(f"{code} {why}" for code, why in self.excludes.items()))
        if self.bands:
            lines.append("Bands: " + "; ".join(str(band.get("label")) + " " + str(band.get("rule")) for band in self.bands))
        lines.extend(f"- {note}" for note in self.notes)
        return "\n".join(lines)


@dataclass(frozen=True)
class TableDoc:
    name: str
    grain: str
    description: str
    columns: dict[str, str]
    primary_key: str | None = None
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def render_summary(self) -> str:
        lines = [f"{self.name}: {self.grain} {self.description}", f"  columns: {', '.join(self.columns)}"]
        for column, values in self.enums.items():
            lines.append(f"  {column} values: {', '.join(values)}")
        return "\n".join(lines)

    def render_detail(self) -> str:
        lines = [f"## {self.name}", f"{self.grain} {self.description}"]
        if self.primary_key:
            lines.append(f"Primary key: {self.primary_key}")
        lines.append("")
        lines.extend(f"- {column}: {description}" for column, description in self.columns.items())
        for column, values in self.enums.items():
            lines.append(f"- {column} allowed values: {', '.join(values)}")
        if self.notes:
            lines.append("")
            lines.extend(f"Note: {note}" for note in self.notes)
        return "\n".join(lines)


@dataclass(frozen=True)
class SemanticLayer:
    tables: dict[str, TableDoc]
    definitions: dict[str, Definition]
    rules: tuple[str, ...]

    def table(self, name: str) -> TableDoc:
        try:
            return self.tables[name.lower()]
        except KeyError:
            raise KeyError(f"Unknown table {name!r}. Known tables: {', '.join(self.tables)}.") from None

    def definition(self, name: str) -> Definition:
        try:
            return self.definitions[name.lower()]
        except KeyError:
            raise KeyError(f"Unknown definition {name!r}. Known definitions: {', '.join(self.definitions)}.") from None

    def render_overview(self, as_of: date | str) -> str:
        """The compact description of the whole database, for the agent's prompt."""
        lines = [
            "# Database overview",
            "",
            f"As-of date: {as_of}. Relative windows such as the last 12 months count back from "
            "this date, which is the latest date in the data, not today.",
            "",
            "## Rules that always apply",
        ]
        lines.extend(f"- {rule}" for rule in self.rules)
        lines.extend(["", "## Tables"])
        lines.extend(table.render_summary() for table in self.tables.values())
        return "\n".join(lines)

    def render_definitions(self, as_of: date | str, *, compact: bool = False) -> str:
        blocks = [definition.render(as_of, compact=compact) for definition in self.definitions.values()]
        return "\n\n".join(["# Shared definitions", *blocks])


def load_semantic_layer(
    catalog_path: Path = CATALOG_PATH, definitions_path: Path = DEFINITIONS_PATH
) -> SemanticLayer:
    catalog = yaml.safe_load(catalog_path.read_text())
    definitions_file = yaml.safe_load(definitions_path.read_text())

    tables = {
        name.lower(): TableDoc(
            name=name.lower(),
            grain=entry.get("grain", ""),
            description=entry.get("description", ""),
            columns=dict(entry.get("columns", {})),
            primary_key=entry.get("primary_key"),
            enums={column: tuple(values) for column, values in (entry.get("enums") or {}).items()},
            notes=tuple(entry.get("notes", ())),
        )
        for name, entry in (catalog.get("tables") or {}).items()
    }

    definitions = {
        name.lower(): Definition(
            name=name.lower(),
            label=entry.get("label", name),
            kind=entry.get("kind", "filter"),
            status=entry.get("status", "assumed"),
            summary=entry.get("summary", ""),
            applies_to=entry.get("applies_to", ""),
            sql=entry.get("sql", "").strip(),
            codes=dict(entry.get("codes") or {}),
            excludes=dict(entry.get("excludes") or {}),
            notes=tuple(entry.get("notes", ())),
            bands=tuple(entry.get("bands", ())),
            checks=tuple(
                Check(
                    description=check.get("description", ""),
                    sql=check.get("sql", "").strip(),
                    equals=check.get("equals"),
                    minimum=check.get("min"),
                    maximum=check.get("max"),
                )
                for check in entry.get("checks", ())
            ),
        )
        for name, entry in (definitions_file.get("definitions") or {}).items()
    }

    return SemanticLayer(tables=tables, definitions=definitions, rules=tuple(catalog.get("rules", ())))


def resolve_as_of_date(settings: Settings, db: ReadOnlyDatabase) -> date:
    """Return the anchor for relative time windows, following docs/decisions/0002."""
    if settings.as_of == "today":
        return date.today()
    if settings.as_of == "latest":
        result = db.run_query("SELECT date(MAX(start)) FROM encounters")
        latest = result.rows[0][0] if result.rows else None
        if not latest:
            raise ValueError("The encounters table has no dates, so the as-of date cannot be resolved.")
        return date.fromisoformat(str(latest))
    return date.fromisoformat(settings.as_of)


WINDOW_MONTHS = (3, 6, 12, 24)


def window_bounds(as_of: date | str, months: int) -> tuple[date, date]:
    """First and last day of the last N months, using SQLite's own date arithmetic.

    The bounds are computed by the same engine that will run the query, so the dates shown
    to the reader cannot disagree with the dates the SQL selects.
    """
    conn = sqlite3.connect(":memory:")
    try:
        start, end = conn.execute(
            "SELECT date(?, ?, '+1 day'), date(?)", (str(as_of), f"-{months} months", str(as_of))
        ).fetchone()
    finally:
        conn.close()
    return date.fromisoformat(start), date.fromisoformat(end)


def describe_windows(as_of: date | str, months: tuple[int, ...] = WINDOW_MONTHS) -> str:
    """The exact date range of each common window, for the agent to quote rather than derive."""
    lines = []
    for count in months:
        start, end = window_bounds(as_of, count)
        lines.append(f"- last {count} months: {start} to {end}")
    return "\n".join(lines)


@dataclass(frozen=True)
class CheckResult:
    definition: str
    check: Check
    value: object = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and self.check.holds_for(self.value)


def run_definition_checks(layer: SemanticLayer, db: ReadOnlyDatabase, as_of: date | str) -> list[CheckResult]:
    """Run every definition's checks against the database."""
    results: list[CheckResult] = []
    for definition in layer.definitions.values():
        for check in definition.checks:
            sql = definition.resolved_check_sql(check, as_of)
            try:
                result = db.run_query(sql)
                value = result.rows[0][0] if result.rows else None
                results.append(CheckResult(definition.name, check, value=value))
            except Exception as exc:
                results.append(CheckResult(definition.name, check, error=f"{type(exc).__name__}: {exc}"))
    return results


def validate_catalog(layer: SemanticLayer, db: ReadOnlyDatabase) -> list[str]:
    """Compare the catalog with the live database. An empty list means they agree."""
    problems: list[str] = []
    live_tables = {name.lower() for name in db.table_names()}

    for missing in sorted(live_tables - set(layer.tables)):
        problems.append(f"Table {missing} exists in the database but is not documented.")
    for extra in sorted(set(layer.tables) - live_tables):
        problems.append(f"Table {extra} is documented but does not exist in the database.")

    for name, table in layer.tables.items():
        if name not in live_tables:
            continue
        live_columns = {column.name.lower() for column in db.table_columns(name, include_blocked=True)}
        blocked = db.blocked_columns_for(name)
        for column in table.columns:
            if column.lower() not in live_columns:
                problems.append(f"Column {name}.{column} is documented but does not exist.")
            elif column.lower() in blocked:
                problems.append(f"Column {name}.{column} is blocked and must not be documented.")
        if table.primary_key and table.primary_key.lower() not in live_columns:
            problems.append(f"Primary key {name}.{table.primary_key} does not exist.")
        for column, values in table.enums.items():
            if column.lower() not in live_columns:
                problems.append(f"Column {name}.{column} has documented values but does not exist.")
                continue
            result = db.run_query(f'SELECT DISTINCT "{column}" FROM "{name}" WHERE "{column}" IS NOT NULL')
            live_values = {str(row[0]) for row in result.rows}
            for undocumented in sorted(live_values - set(values)):
                problems.append(f"Value {undocumented!r} of {name}.{column} is in the data but not documented.")
            for stale in sorted(set(values) - live_values):
                problems.append(f"Value {stale!r} of {name}.{column} is documented but not in the data.")
    return problems
