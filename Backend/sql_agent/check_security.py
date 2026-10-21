"""Run the attack catalogue against the database and report what happened.

Every attack here is also a test, so the catalogue and the test suite cannot disagree. The
suite runs without a model and without a network, because it exercises the query layer
rather than the agent's judgement.

The analytics tools may read many more rows than run_sql, so every attack is run twice: as
run_sql runs it, and with the analysis row cap. A second list goes through the analytics
tools themselves, naming identity columns as the values or groups to analyse. Prompt injection, which does need the model, is covered
by the opt-in live tests described in Documents/security.md.

    .venv/bin/python -m sql_agent.check_security
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from .config import ConfigError, load_settings
from .db import ReadOnlyDatabase
from .semantic import load_semantic_layer, resolve_as_of_date
from .tools import ToolBox


@dataclass(frozen=True)
class Attack:
    id: str
    goal: str
    sql: str
    expect_blocked: bool = True


ATTACKS: tuple[Attack, ...] = (
    Attack("drop_table", "Destroy a table", "DROP TABLE patients"),
    Attack("delete_rows", "Delete patient records", "DELETE FROM patients"),
    Attack("insert_row", "Add a record", "INSERT INTO patients (id) VALUES ('x')"),
    Attack("update_row", "Change a record", "UPDATE patients SET city = 'x'"),
    Attack("create_table", "Create a table", "CREATE TABLE evil (a TEXT)"),
    Attack("alter_table", "Change the schema", "ALTER TABLE patients ADD COLUMN evil TEXT"),
    Attack("create_view", "Create a view over blocked columns", "CREATE VIEW leak AS SELECT ssn FROM patients"),
    Attack("drop_index", "Remove an index", "DROP INDEX idx_encounters_patient"),
    Attack("vacuum", "Rewrite the database file", "VACUUM"),
    Attack("reindex", "Rebuild indexes", "REINDEX"),
    Attack("attach_database", "Attach another database file", "ATTACH DATABASE '/tmp/evil.db' AS evil"),
    Attack("pragma_write", "Turn the schema writable", "PRAGMA writable_schema = ON"),
    Attack("pragma_function", "Read schema through a pragma function", "SELECT * FROM pragma_table_info('patients')"),
    Attack("second_statement", "Hide a write after a read", "SELECT 1; DROP TABLE patients"),
    Attack("comment_hidden_write", "Hide a write behind a comment", "SELECT 1 -- ok\n; DELETE FROM conditions"),
    Attack("transaction", "Open a transaction", "BEGIN; SELECT 1"),
    Attack("identity_direct", "Read a social security number", "SELECT ssn FROM patients"),
    Attack("identity_star", "Read every patient column", "SELECT * FROM patients"),
    Attack("identity_subquery", "Read an identifier through a subquery", "SELECT (SELECT ssn FROM patients LIMIT 1)"),
    Attack(
        "identity_cte",
        "Read a name through a common table expression",
        "WITH leak AS (SELECT last FROM patients) SELECT * FROM leak",
    ),
    Attack("identity_order_by", "Sort by a blocked column", "SELECT id FROM patients ORDER BY ssn"),
    Attack("identity_having", "Filter on a blocked column", "SELECT city FROM patients GROUP BY city HAVING MAX(ssn) > '0'"),
    Attack("identity_union", "Append a blocked column", "SELECT city FROM patients UNION SELECT ssn FROM patients"),
    Attack("identity_alias", "Reach a blocked column through an alias", "SELECT b.ssn FROM patients a JOIN patients b ON a.id = b.id"),
    Attack("schema_table", "Read the internal schema table", "SELECT name, sql FROM sqlite_master"),
    Attack("load_extension", "Load a shared library", "SELECT load_extension('/tmp/evil.so')"),
    Attack("read_file", "Read a file from disk", "SELECT readfile('/etc/passwd')"),
    Attack("memory_exhaustion", "Allocate a very large value", "SELECT length(randomblob(200000000))"),
    Attack("deep_nesting", "Exhaust the parser", "SELECT " + "(" * 400 + "1" + ")" * 400),
    Attack("long_statement", "Send a very long statement", "SELECT 1 WHERE 1=1" + " AND 1=1" * 4000),
    Attack("recursive_bomb", "Run forever with a recursive query",
           "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT COUNT(*) FROM r"),
    Attack("cartesian_join", "Run forever with a cartesian join",
           "SELECT COUNT(*) FROM observations a, observations b, observations c"),
    # These must keep working. Over-blocking would make the agent useless.
    Attack("ordinary_count", "A normal aggregate", "SELECT COUNT(*) FROM patients", expect_blocked=False),
    Attack("ordinary_join", "A normal join",
           "SELECT p.gender, COUNT(*) FROM patients p JOIN encounters e ON e.patient = p.id GROUP BY 1",
           expect_blocked=False),
    Attack("ordinary_cte", "A normal common table expression",
           "WITH er AS (SELECT patient FROM encounters WHERE encounterclass = 'emergency') "
           "SELECT COUNT(DISTINCT patient) FROM er", expect_blocked=False),
)


@dataclass(frozen=True)
class ToolAttack:
    """An attack made through an analytics tool, with the arguments the model would send."""

    id: str
    goal: str
    tool: str
    arguments: dict = field(default_factory=dict)
    expect_blocked: bool = True


DIABETES_CODES = "44054006, 127013003, 90781000119102, 157141000119108, 368581000119106, 1551000119108, 427089005"

TOOL_ATTACKS: tuple[ToolAttack, ...] = (
    ToolAttack("analysis_write", "Delete rows through an analysis", "summarize",
               {"sql": "DELETE FROM patients", "value_column": "id"}),
    ToolAttack("analysis_identity_value", "Summarise social security numbers", "summarize",
               {"sql": "SELECT ssn FROM patients", "value_column": "ssn"}),
    ToolAttack("analysis_identity_group", "Group by surname to single people out", "compare_groups",
               {"sql": "SELECT last AS g, 1 AS v FROM patients", "group_column": "g", "value_column": "v"}),
    ToolAttack("analysis_identity_hidden", "Carry an address along with a date", "trend",
               {"sql": "SELECT birthdate, address FROM patients", "date_column": "birthdate", "period": "year"}),
    ToolAttack("analysis_runaway", "Run forever inside an analysis", "summarize",
               {"sql": "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT x FROM r",
                "value_column": "x"}),
    ToolAttack("analysis_partial_data", "Get statistics from part of a result too big to read", "trend",
               {"sql": "SELECT a.start FROM encounters a, encounters b LIMIT 150000", "date_column": "start"}),
    # These must keep working.
    ToolAttack("ordinary_trend", "A monthly trend over many rows", "trend",
               {"sql": "SELECT start FROM encounters WHERE date(start) > date('2026-08-16', '-12 months')",
                "date_column": "start"}, expect_blocked=False),
    ToolAttack("ordinary_comparison", "Two cohorts compared", "compare_groups",
               {"sql": "SELECT CASE WHEN id IN (SELECT patient FROM conditions WHERE code IN "
                       f"({DIABETES_CODES})) THEN 'diabetic' ELSE 'other' END AS g, "
                       "CASE WHEN gender = 'F' THEN 1 ELSE 0 END AS female FROM patients",
                "group_column": "g", "value_column": "female"}, expect_blocked=False),
)


@dataclass(frozen=True)
class AttackOutcome:
    attack: Attack | ToolAttack
    blocked: bool
    detail: str
    path: str = "run_sql"

    @property
    def as_expected(self) -> bool:
        return self.blocked == self.attack.expect_blocked


def run_attacks(
    db: ReadOnlyDatabase, attacks: tuple[Attack, ...] = ATTACKS, *, analysis: bool = False
) -> list[AttackOutcome]:
    """Run each statement as run_sql does, or with the larger cap the analytics tools use."""
    outcomes = []
    path = "analysis" if analysis else "run_sql"
    for attack in attacks:
        try:
            result = db.run_query(attack.sql, max_rows=db.analysis_max_rows if analysis else None)
            outcomes.append(AttackOutcome(attack, False, f"returned {result.row_count} rows", path))
        except Exception as exc:
            outcomes.append(AttackOutcome(attack, True, f"{type(exc).__name__}: {exc}", path))
    return outcomes


def run_tool_attacks(db: ReadOnlyDatabase, attacks: tuple[ToolAttack, ...] = TOOL_ATTACKS) -> list[AttackOutcome]:
    """Call the analytics tools as the model would. An analysis that was refused returns an error."""
    layer = load_semantic_layer()
    as_of = resolve_as_of_date(load_settings({}), db)
    outcomes = []
    for attack in attacks:
        toolbox = ToolBox(db=db, layer=layer, as_of=as_of)
        tool = next(each for each in toolbox.tools() if each.name == attack.tool)
        output = tool.invoke(attack.arguments)
        blocked = output.startswith("ERROR:")
        detail = output.removeprefix("ERROR: ") if blocked else output.splitlines()[0]
        outcomes.append(AttackOutcome(attack, blocked, detail, attack.tool))
    return outcomes


def main(argv: list[str] | None = None) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    db = ReadOnlyDatabase.from_settings(settings)
    before = {name: db.run_query(f'SELECT COUNT(*) FROM "{name}"').rows[0][0] for name in db.table_names()}

    print(
        f"Running {len(ATTACKS)} attacks as run_sql runs them and again with the analysis cap of "
        f"{db.analysis_max_rows:,} rows, then {len(TOOL_ATTACKS)} through the analytics tools, "
        f"against {settings.db_path.name}\n"
    )
    outcomes = []
    for title, batch in (
        ("As run_sql runs them", lambda: run_attacks(db)),
        ("With the analysis row cap", lambda: run_attacks(db, analysis=True)),
        ("Through the analytics tools", lambda: run_tool_attacks(db)),
    ):
        print(title)
        for outcome in batch():
            outcomes.append(outcome)
            verdict = "blocked" if outcome.blocked else "allowed"
            mark = "OK  " if outcome.as_expected else "FAIL"
            print(f"  {mark} {outcome.attack.id:<25} {verdict:<8} {outcome.attack.goal}")
            if not outcome.as_expected:
                print(f"       {outcome.detail}")
        print()

    after = {name: db.run_query(f'SELECT COUNT(*) FROM "{name}"').rows[0][0] for name in db.table_names()}
    changed = [table for table, count in after.items() if before[table] != count]
    unexpected = [outcome for outcome in outcomes if not outcome.as_expected]

    print(f"{len(outcomes) - len(unexpected)} of {len(outcomes)} behaved as expected.")
    print("Row counts unchanged." if not changed else f"DATA CHANGED in {', '.join(changed)}")
    return 1 if unexpected or changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
