"""Ask a question about the synthetic patient database in plain language.

Run from the Backend folder:

    .venv/bin/python main.py "How many diabetic patients had an ER visit?"
    .venv/bin/python main.py --verbose "Compare ER visits for diabetic and other patients"
    .venv/bin/python main.py --no-sql "Which age band has the most hospital visits?"
"""

from __future__ import annotations

import argparse
import sys

import anthropic

from sql_agent.agent import AgentError, AgentResult, SqlAgent
from sql_agent.config import ConfigError


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


def print_result(result: AgentResult, *, show_sql: bool) -> None:
    print(f"\n{result.answer}\n")
    if show_sql and result.successful_queries:
        print("SQL that produced this answer")
        for position, record in enumerate(result.successful_queries, start=1):
            rows = f"{record.row_count} rows in {record.elapsed_ms:.0f} ms"
            print(f"\n  {position}. {rows}")
            for line in record.sql.strip().splitlines():
                print(f"     {line}")
        print()
    failed = [record for record in result.queries if not record.ok]
    summary = (
        f"{len(result.successful_queries)} queries, {len(failed)} failed, "
        f"{result.elapsed_s:.1f}s, {result.input_tokens:,} in and {result.output_tokens:,} out tokens, "
        f"as of {result.as_of}"
    )
    print(summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="the question to answer, in plain language")
    parser.add_argument("-v", "--verbose", action="store_true", help="show each step as it happens")
    parser.add_argument("--no-sql", action="store_true", help="hide the SQL behind the answer")
    args = parser.parse_args(argv)

    try:
        agent = SqlAgent()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    print(f"Question: {args.question}")
    if args.verbose:
        print(f"Model {agent.settings.model}, as-of date {agent.as_of}")

    try:
        result = agent.answer(args.question, on_event=print_event if args.verbose else None)
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

    print_result(result, show_sql=not args.no_sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
