"""Check the semantic layer against the real database.

Run from the Backend folder:
    .venv/bin/python -m sql_agent.check_semantics
    .venv/bin/python -m sql_agent.check_semantics --show-prompt

It compares the schema catalog with the live tables and columns, then runs every
definition's checks. It exits non-zero if anything disagrees, so it doubles as a guard
against the data and the definitions drifting apart.
"""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_settings
from .db import ReadOnlyDatabase
from .semantic import load_semantic_layer, resolve_as_of_date, run_definition_checks, validate_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the semantic layer against the database.")
    parser.add_argument("--show-prompt", action="store_true", help="print the text the agent will be given")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    db = ReadOnlyDatabase.from_settings(settings)
    layer = load_semantic_layer()

    try:
        as_of = resolve_as_of_date(settings, db)
    except Exception as exc:
        print(f"Could not resolve the as-of date: {exc}", file=sys.stderr)
        return 1

    print(f"As-of date: {as_of}, from the setting {settings.as_of!r}\n")

    if args.show_prompt:
        print(layer.render_overview(as_of))
        print()
        print(layer.render_definitions(as_of))
        return 0

    problems = validate_catalog(layer, db)
    documented_columns = sum(len(table.columns) for table in layer.tables.values())
    if problems:
        print(f"Catalog: {len(problems)} problems")
        for problem in problems:
            print(f"  FAIL {problem}")
    else:
        print(f"Catalog: matches the database, {len(layer.tables)} tables and {documented_columns} columns documented")

    results = run_definition_checks(layer, db, as_of)
    print(f"\nDefinition checks ({len(layer.definitions)} definitions)")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        got = result.error if result.error else f"got {result.value}"
        print(f"  {status}  {result.definition:<24} {result.check.description:<46} expected {result.check.expectation:<8} {got}")

    failed = [result for result in results if not result.passed]
    assumed = [d.name for d in layer.definitions.values() if d.status != "confirmed"]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    if assumed:
        print(f"{len(assumed)} definitions are still marked assumed and need Telligen review.")

    return 1 if failed or problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
