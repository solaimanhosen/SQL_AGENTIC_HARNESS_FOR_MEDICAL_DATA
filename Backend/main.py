"""Ask a question about the synthetic patient database in plain language.

Run from the Backend folder:

    .venv/bin/python main.py "How many diabetic patients had an ER visit?"
    .venv/bin/python main.py --verbose "Compare ER visits for diabetic and other patients"
    .venv/bin/python main.py --json "Which age band has the most hospital visits?"

Every run is appended to logs/runs.jsonl unless --no-log is given.
"""

from __future__ import annotations

import argparse
import json
import sys

import anthropic

from sql_agent.agent import AgentError, AgentResult, SqlAgent
from sql_agent.config import ConfigError
from sql_agent.runlog import build_record, log_run


def print_event(kind: str, detail: str) -> None:
    if kind == "sql":
        print("\n  running SQL:")
        for line in detail.strip().splitlines():
            print(f"    {line}")
    elif kind == "sql_result":
        print(f"  -> {detail}")
    elif kind == "sql_error":
        print(f"  -> failed: {detail}")
    elif kind == "describe_table":
        print(f"  reading the schema of {detail}")
    elif kind == "lookup_definition":
        print(f"  looking up the definition of {detail}")
    sys.stdout.flush()


def print_queries(result: AgentResult) -> None:
    if not result.successful_queries:
        return
    print("\nSQL that produced this answer")
    for record in result.successful_queries:
        print(f"\n  Query {record.number}. {record.row_count} rows in {record.elapsed_ms:.0f} ms")
        for line in record.sql.strip().splitlines():
            print(f"     {line}")


def print_traceability(result: AgentResult) -> None:
    """Report anything in the answer that our own records do not back up."""
    issues = result.issues
    if not issues.any:
        return
    print("\nTraceability warnings")
    if issues.unknown_definitions:
        print(f"  - Named definitions that do not exist: {', '.join(issues.unknown_definitions)}")
    if issues.missing_query_numbers:
        numbers = ", ".join(str(number) for number in issues.missing_query_numbers)
        print(f"  - Cited query numbers that did not run: {numbers}")
    if issues.window_not_in_sql:
        print(f"  - Time window not backed by SQL: {issues.window_not_in_sql}")
    for statement in issues.unsupported_findings:
        print(f"  - No query cited for: {statement}")


def print_result(result: AgentResult, *, show_sql: bool) -> None:
    print(f"\n{result.answer}\n")
    if show_sql:
        print_queries(result)
    print_traceability(result)
    failed = len(result.queries) - len(result.successful_queries)
    print(
        f"\n{len(result.successful_queries)} queries, {failed} failed, {result.elapsed_s:.1f}s, "
        f"{result.input_tokens:,} in and {result.output_tokens:,} out tokens, as of {result.as_of}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="the question to answer, in plain language")
    parser.add_argument("-v", "--verbose", action="store_true", help="show each step as it happens")
    parser.add_argument("--no-sql", action="store_true", help="hide the SQL behind the answer")
    parser.add_argument("--json", action="store_true", help="print the whole run as JSON instead")
    parser.add_argument("--no-log", action="store_true", help="do not append this run to the log")
    args = parser.parse_args(argv)

    try:
        agent = SqlAgent()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    if not args.json:
        print(f"Question: {args.question}")
        if args.verbose:
            print(f"Model {agent.settings.model}, as-of date {agent.as_of}")

    try:
        result = agent.answer(args.question, on_event=print_event if args.verbose and not args.json else None)
    except AgentError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except anthropic.AuthenticationError:
        print("\nThe API key was rejected. Check ANTHROPIC_API_KEY in Backend/.env.", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as exc:
        print(f"\nThe Anthropic API returned an error: {exc.message}", file=sys.stderr)
        return 1
    except anthropic.APIConnectionError:
        print("\nCould not reach the Anthropic API. Check the network connection.", file=sys.stderr)
        return 1

    log_path = agent.settings.log_path
    if args.no_log or log_path is None:
        log_path = None
    else:
        log_run(result, log_path)

    if args.json:
        print(json.dumps(build_record(result), indent=2, ensure_ascii=False))
        return 0

    print_result(result, show_sql=not args.no_sql)
    if log_path is not None:
        print(f"Logged to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
