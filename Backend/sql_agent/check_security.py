"""Run the attack catalogue against the database and report what happened.

Every attack here is also a test, so the catalogue and the test suite cannot disagree. The
suite runs without a model and without a network, because it exercises the query layer
rather than the agent's judgement. Prompt injection, which does need the model, is covered
by the opt-in live tests described in docs/security.md.

    .venv/bin/python -m sql_agent.check_security
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .config import ConfigError, load_settings
from .db import ReadOnlyDatabase


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
class AttackOutcome:
    attack: Attack
    blocked: bool
    detail: str

    @property
    def as_expected(self) -> bool:
        return self.blocked == self.attack.expect_blocked


def run_attacks(db: ReadOnlyDatabase, attacks: tuple[Attack, ...] = ATTACKS) -> list[AttackOutcome]:
    outcomes = []
    for attack in attacks:
        try:
            result = db.run_query(attack.sql)
            outcomes.append(AttackOutcome(attack, blocked=False, detail=f"returned {result.row_count} rows"))
        except Exception as exc:
            outcomes.append(AttackOutcome(attack, blocked=True, detail=f"{type(exc).__name__}: {exc}"))
    return outcomes


def main(argv: list[str] | None = None) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    db = ReadOnlyDatabase.from_settings(settings)
    before = {name: db.run_query(f'SELECT COUNT(*) FROM "{name}"').rows[0][0] for name in db.table_names()}

    print(f"Running {len(ATTACKS)} attacks against {settings.db_path.name}\n")
    outcomes = run_attacks(db)
    for outcome in outcomes:
        verdict = "blocked" if outcome.blocked else "allowed"
        mark = "OK  " if outcome.as_expected else "FAIL"
        print(f"  {mark} {outcome.attack.id:<22} {verdict:<8} {outcome.attack.goal}")
        if not outcome.as_expected:
            print(f"       {outcome.detail}")

    after = {name: db.run_query(f'SELECT COUNT(*) FROM "{name}"').rows[0][0] for name in db.table_names()}
    changed = [table for table, count in after.items() if before[table] != count]
    unexpected = [outcome for outcome in outcomes if not outcome.as_expected]

    print(f"\n{len(outcomes) - len(unexpected)} of {len(outcomes)} behaved as expected.")
    print("Row counts unchanged." if not changed else f"DATA CHANGED in {', '.join(changed)}")
    return 1 if unexpected or changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
