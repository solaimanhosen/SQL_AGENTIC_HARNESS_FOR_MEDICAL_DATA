"""Score the agent against questions whose answers are known.

Each question in evals/questions.yaml carries the SQL that produces the right answer. The
harness runs that SQL first, so a change in the data is caught before the agent is asked
anything. Then it asks the agent and checks the answer on several dimensions: the numbers,
the definitions it says it used, whether every claim is traceable to a query, and, for the
safety questions, that the database is untouched.

    .venv/bin/python -m sql_agent.evaluate --dry-run   # golden SQL only, no model calls
    .venv/bin/python -m sql_agent.evaluate             # full run
    .venv/bin/python -m sql_agent.evaluate --category safety --only patient_count
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import anthropic
import yaml

from .agent import AgentResult, SqlAgent
from .answer import numbers_in
from .config import BACKEND_DIR, ConfigError, load_settings
from .db import ReadOnlyDatabase

DEFAULT_QUESTIONS_PATH = BACKEND_DIR / "evals" / "questions.yaml"
DEFAULT_RESULTS_DIR = BACKEND_DIR / "evals" / "results"

NUMBER_TOLERANCE = 0.01


class EvalSetError(ValueError):
    """The evaluation set itself is wrong, for example a golden answer that no longer holds."""


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question: str
    golden_sql: str | None = None
    golden_value: object = None
    expect: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CheckOutcome:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    checks: tuple[CheckOutcome, ...]
    result: AgentResult | None = None
    error: str | None = None
    unavailable: bool = False
    """True when the model could not be reached at all, so the agent was never tested."""

    @property
    def passed(self) -> bool:
        return self.error is None and all(check.passed for check in self.checks)

    @property
    def failed(self) -> bool:
        """A wrong answer, as opposed to a question that could not be asked."""
        return not self.passed and not self.unavailable

    @property
    def failures(self) -> tuple[CheckOutcome, ...]:
        return tuple(check for check in self.checks if not check.passed)


def load_cases(path: Path = DEFAULT_QUESTIONS_PATH) -> list[EvalCase]:
    document = yaml.safe_load(path.read_text()) or {}
    cases = [
        EvalCase(
            id=entry["id"],
            category=entry.get("category", "general"),
            question=entry["question"].strip(),
            golden_sql=(entry.get("golden_sql") or "").strip() or None,
            golden_value=entry.get("golden_value"),
            expect=dict(entry.get("expect") or {}),
        )
        for entry in document.get("questions", [])
    ]
    identifiers = [case.id for case in cases]
    duplicates = {name for name in identifiers if identifiers.count(name) > 1}
    if duplicates:
        raise EvalSetError(f"Duplicate question ids: {', '.join(sorted(duplicates))}")
    return cases


def verify_golden_answers(cases: list[EvalCase], db: ReadOnlyDatabase) -> list[str]:
    """Run each golden query and compare it with the recorded answer. Empty list means agreement."""
    problems = []
    for case in cases:
        if not case.golden_sql:
            continue
        try:
            result = db.run_query(case.golden_sql)
        except Exception as exc:
            problems.append(f"{case.id}: golden SQL failed, {type(exc).__name__}: {exc}")
            continue
        if not result.rows:
            problems.append(f"{case.id}: golden SQL returned no rows")
            continue
        actual = result.rows[0][0]
        if case.golden_value is not None and str(actual) != str(case.golden_value):
            problems.append(f"{case.id}: golden SQL now returns {actual!r}, the set says {case.golden_value!r}")
    return problems


def contains_number(text: str, value: float) -> bool:
    return any(abs(found - value) <= NUMBER_TOLERANCE for found in numbers_in(text))


def claim_text(result: AgentResult) -> str:
    """The model's own claims: the headline and findings, not the parts this code renders."""
    if result.structured is None:
        return result.answer
    parts = [result.structured.headline, *(finding.statement for finding in result.structured.findings)]
    return "\n".join(parts)


def fingerprint(db: ReadOnlyDatabase) -> dict[str, int]:
    """Row counts for every table, used to prove a run changed nothing."""
    return {name: db.run_query(f'SELECT COUNT(*) FROM "{name}"').rows[0][0] for name in db.table_names()}


def score_case(case: EvalCase, result: AgentResult, db: ReadOnlyDatabase, before: dict[str, int]) -> list[CheckOutcome]:
    checks: list[CheckOutcome] = []
    expect = case.expect
    claims = claim_text(result)
    whole_answer = result.answer

    expected_numbers = expect.get("numbers") or []
    if expected_numbers:
        missing = []
        for wanted in expected_numbers:
            value = case.golden_value if wanted == "golden" else wanted
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not contains_number(claims, number):
                missing.append(_tidy_number(number))
        checks.append(
            CheckOutcome("value", not missing, "" if not missing else f"missing {', '.join(missing)} from the answer")
        )

    if expect.get("phrases"):
        missing = [phrase for phrase in expect["phrases"] if phrase.lower() not in whole_answer.lower()]
        checks.append(CheckOutcome("phrases", not missing, "" if not missing else f"missing {', '.join(missing)}"))

    if expect.get("phrases_any"):
        found = any(phrase.lower() in whole_answer.lower() for phrase in expect["phrases_any"])
        checks.append(CheckOutcome("phrases_any", found, "" if found else "said none of the expected things"))

    if expect.get("definitions"):
        used = {name.lower() for name in (result.structured.definitions_used if result.structured else [])}
        missing = [name for name in expect["definitions"] if name.lower() not in used]
        checks.append(
            CheckOutcome("definitions", not missing, "" if not missing else f"did not cite {', '.join(missing)}")
        )

    if expect.get("forbidden"):
        present = [text for text in expect["forbidden"] if text.lower() in whole_answer.lower()]
        checks.append(CheckOutcome("forbidden", not present, "" if not present else f"contains {', '.join(present)}"))

    if expect.get("assumptions_required"):
        recorded = bool(result.structured and result.structured.assumptions)
        checks.append(CheckOutcome("assumptions", recorded, "" if recorded else "recorded no assumption"))

    if expect.get("database_unchanged"):
        if not before:
            checks.append(CheckOutcome("database_unchanged", False, "no row counts were taken before the run"))
        else:
            after = fingerprint(db)
            changed = [table for table, count in after.items() if table in before and before[table] != count]
            missing = sorted(set(after) - set(before))
            detail = ""
            if changed:
                detail = f"changed {', '.join(changed)}"
            elif missing:
                detail = f"not covered by the baseline: {', '.join(missing)}"
            checks.append(CheckOutcome("database_unchanged", not changed and not missing, detail))

    if expect.get("max_queries") is not None:
        count = len(result.successful_queries)
        within = count <= expect["max_queries"]
        checks.append(CheckOutcome("max_queries", within, "" if within else f"used {count} queries"))

    checks.append(
        CheckOutcome("traceability", not result.issues.any, "" if not result.issues.any else _issue_text(result))
    )
    return checks


def _issue_text(result: AgentResult) -> str:
    issues = result.issues
    parts = []
    if issues.unknown_definitions:
        parts.append(f"invented definitions {', '.join(issues.unknown_definitions)}")
    if issues.missing_query_numbers:
        parts.append(f"cited queries that did not run: {issues.missing_query_numbers}")
    if issues.unsupported_findings:
        parts.append(f"{len(issues.unsupported_findings)} findings cite no query")
    if issues.window_not_in_sql:
        parts.append(issues.window_not_in_sql)
    return "; ".join(parts)


def _tidy_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


@dataclass
class EvalReport:
    results: list[CaseResult]
    elapsed_s: float
    model: str
    as_of: str

    @property
    def passed(self) -> int:
        return sum(1 for case in self.results if case.passed)

    @property
    def unavailable(self) -> int:
        return sum(1 for case in self.results if case.unavailable)

    @property
    def answered(self) -> int:
        return len(self.results) - self.unavailable

    def dimension_totals(self) -> dict[str, tuple[int, int]]:
        totals: dict[str, list[int]] = {}
        for case in self.results:
            for check in case.checks:
                entry = totals.setdefault(check.name, [0, 0])
                entry[0] += int(check.passed)
                entry[1] += 1
        return {name: (passed, total) for name, (passed, total) in totals.items()}

    def to_dict(self) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": self.model,
            "as_of": self.as_of,
            "score": {
                "passed": self.passed,
                "answered": self.answered,
                "total": len(self.results),
                "unavailable": self.unavailable,
            },
            "dimensions": {name: list(counts) for name, counts in self.dimension_totals().items()},
            "elapsed_s": round(self.elapsed_s, 1),
            "input_tokens": sum(case.result.input_tokens for case in self.results if case.result),
            "output_tokens": sum(case.result.output_tokens for case in self.results if case.result),
            "cases": [
                {
                    "id": case.case.id,
                    "category": case.case.category,
                    "question": case.case.question,
                    "passed": case.passed,
                    "unavailable": case.unavailable,
                    "error": case.error,
                    "checks": [
                        {"name": check.name, "passed": check.passed, "detail": check.detail} for check in case.checks
                    ],
                    "queries": [record.sql for record in case.result.successful_queries] if case.result else [],
                    "headline": case.result.structured.headline
                    if case.result and case.result.structured
                    else None,
                    "elapsed_s": round(case.result.elapsed_s, 1) if case.result else None,
                    "input_tokens": case.result.input_tokens if case.result else 0,
                    "output_tokens": case.result.output_tokens if case.result else 0,
                }
                for case in self.results
            ],
        }

    def summary_text(self) -> str:
        share = self.passed / max(self.answered, 1)
        lines = [f"\nScore {self.passed}/{self.answered} answered ({share:.0%})"]
        if self.unavailable:
            lines.append(
                f"  {self.unavailable} question(s) could not be asked because the Anthropic API "
                "was unavailable, so they are not scored."
            )
        for name, (passed, total) in sorted(self.dimension_totals().items()):
            lines.append(f"  {name:<20} {passed}/{total}")
        data = self.to_dict()
        lines.append(
            f"Cost: {data['input_tokens']:,} in and {data['output_tokens']:,} out tokens "
            f"over {self.elapsed_s / 60:.1f} minutes"
        )
        return "\n".join(lines)


def run_evaluation(
    cases: list[EvalCase],
    agent: SqlAgent,
    db: ReadOnlyDatabase,
    on_case: Callable[[CaseResult], None] | None = None,
) -> EvalReport:
    started = time.perf_counter()
    results = []
    for case in cases:
        before = fingerprint(db) if case.expect.get("database_unchanged") else {}
        try:
            answer = agent.answer(case.question)
            checks = score_case(case, answer, db, before)
            case_result = CaseResult(case=case, checks=tuple(checks), result=answer)
        except Exception as exc:  # a crash is a failure, not a reason to stop the run
            case_result = CaseResult(
                case=case,
                checks=(),
                error=f"{type(exc).__name__}: {exc}",
                # An API problem such as an expired key, no credit or a rate limit says
                # nothing about the agent, so it must not be scored as a wrong answer.
                unavailable=isinstance(exc, anthropic.APIError),
            )
        results.append(case_result)
        if on_case is not None:
            on_case(case_result)
    return EvalReport(
        results=results,
        elapsed_s=time.perf_counter() - started,
        model=agent.settings.model,
        as_of=str(agent.as_of),
    )


def _print_case(case_result: CaseResult) -> None:
    case = case_result.case
    if case_result.error:
        detail = case_result.error
    else:
        failures = case_result.failures
        detail = "; ".join(f"{check.name}: {check.detail}" for check in failures) if failures else "all checks passed"
    cost = ""
    if case_result.result:
        cost = f"{len(case_result.result.successful_queries)} queries, {case_result.result.elapsed_s:.0f}s"
    mark = "PASS" if case_result.passed else ("SKIP" if case_result.unavailable else "FAIL")
    print(f"  {mark}  {case.id:<28} {case.category:<12} {cost:<18} {detail}")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the agent against known answers.")
    parser.add_argument("--dry-run", action="store_true", help="only check the golden SQL, no model calls")
    parser.add_argument("--only", action="append", help="run just this question id, repeatable")
    parser.add_argument("--category", action="append", help="run just this category, repeatable")
    parser.add_argument("--limit", type=int, help="stop after this many questions")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH, help="the question file")
    parser.add_argument("--out", type=Path, help="where to write the JSON report")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    db = ReadOnlyDatabase.from_settings(settings)
    cases = load_cases(args.questions)
    if args.only:
        cases = [case for case in cases if case.id in set(args.only)]
    if args.category:
        cases = [case for case in cases if case.category in set(args.category)]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("No questions matched.", file=sys.stderr)
        return 1

    problems = verify_golden_answers(cases, db)
    if problems:
        print(f"The evaluation set disagrees with the data ({len(problems)} problems):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Golden answers verified against the data for {len(cases)} questions.")
    if args.dry_run:
        return 0

    agent = SqlAgent(settings)
    print(f"Asking {agent.settings.model}, as-of date {agent.as_of}\n")
    report = run_evaluation(cases, agent, db, on_case=_print_case)
    print(report.summary_text())

    out_path = args.out or DEFAULT_RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    print(f"Report written to {out_path}")
    if report.unavailable:
        return 2  # nothing is known about those questions, which is not the same as a pass
    return 0 if report.passed == len(report.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
