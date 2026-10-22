"""The checks an admin can run from the browser, and the runner that runs them one at a time.

Every job is a fixed command, a list of arguments chosen here, run as a subprocess in the
Backend folder without a shell. The browser picks a job by name; the only other thing it may
send is a choice from a fixed list (the model for the live checks), checked against that
list before it becomes an argument. Nothing typed in the browser is ever part of a command.

A run's output is read line by line as it happens, so the console can show it live, and is
kept with the run, capped, in the application database. Only one job runs at a time, each
has a time limit, and a run still going when the service stops is marked interrupted when it
starts again (see ADR 0008).
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .appdb import AppDatabase
from .config import BACKEND_DIR
from .models import CATALOG, VALID_EFFORTS

# Kept with a run: enough for any check's report, small enough for the database. When a run
# writes more, its end is kept, since that is where the totals are.
MAX_OUTPUT_CHARS = 200_000
HISTORY_LIMIT = 50
LIVE_EVALUATION_FLAG = "SQL_AGENT_ADMIN_LIVE_EVAL"


class JobError(Exception):
    """The job cannot start. `kind` is a short code for the response."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class Choice:
    """A setting the browser may pick for a job, from a fixed list."""

    name: str
    label: str
    options: tuple[str, ...]
    default: str


@dataclass(frozen=True)
class Job:
    id: str
    label: str
    description: str
    cost: str
    """What running it spends, in words: "Free", or what model calls it makes."""
    command: Callable[[Mapping[str, str], Path], list[str]]
    """The arguments to run, from the chosen settings and a scratch folder for reports."""
    timeout_seconds: float
    choices: tuple[Choice, ...] = ()
    paid: bool = False
    """It calls the model and costs money, so the console asks before starting it."""
    enabled: Callable[[], bool] = lambda: True
    disabled_reason: str = ""
    summarize: Callable[[Path, list[str]], dict] | None = None
    """Reads the scratch folder and output into a short summary, such as test counts."""


def _python(*args: str) -> Callable[[Mapping[str, str], Path], list[str]]:
    return lambda _choices, _scratch: [sys.executable, *args]


def _last_lines(_scratch: Path, lines: list[str]) -> dict:
    """The final non-empty lines, which every check script ends with: its verdict."""
    tail = [line for line in lines if line.strip()][-2:]
    return {"verdict": " ".join(line.strip() for line in tail)}


def _pytest_summary(scratch: Path, lines: list[str]) -> dict:
    """Counts and failing test names from the JUnit report pytest wrote."""
    report = scratch / "junit.xml"
    if not report.exists():
        return _last_lines(scratch, lines)
    root = ElementTree.parse(report).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    counts = {key: int(suite.get(key, 0)) for key in ("tests", "failures", "errors", "skipped")}
    failed = [
        f"{case.get('classname')}::{case.get('name')}"
        for case in suite.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    ]
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    return {
        **counts,
        "failed": failed[:50],
        "verdict": f"{counts['passed']} passed, {counts['failures'] + counts['errors']} failed, {counts['skipped']} skipped",
    }


MODEL_CHOICE = Choice(
    "model", "Model", tuple(option.id for option in CATALOG), CATALOG[0].id
)
EFFORT_CHOICE = Choice("effort", "Effort", VALID_EFFORTS, "high")


def _live_evaluation_enabled() -> bool:
    return os.environ.get(LIVE_EVALUATION_FLAG, "").strip().lower() in ("1", "true", "yes")


JOBS: tuple[Job, ...] = (
    Job(
        id="tests",
        label="Unit tests",
        description="The backend's test suite (pytest). No network, no model calls.",
        cost="Free",
        command=lambda _choices, scratch: [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={scratch / 'junit.xml'}",
        ],
        timeout_seconds=600,
        summarize=_pytest_summary,
    ),
    Job(
        id="security",
        label="Security catalogue",
        description="Every attack in the catalogue, through run_sql, with the analysis cap, and through the analytics tools. Row counts must not change.",
        cost="Free",
        command=_python("-m", "sql_agent.check_security"),
        timeout_seconds=300,
        summarize=_last_lines,
    ),
    Job(
        id="semantics",
        label="Semantic layer",
        description="The table catalog against the live schema, and every definition's check against the data.",
        cost="Free",
        command=_python("-m", "sql_agent.check_semantics"),
        timeout_seconds=120,
        summarize=_last_lines,
    ),
    Job(
        id="evaluation_dry_run",
        label="Evaluation, dry run",
        description="The golden SQL of every evaluation question, run against the data. No model calls.",
        cost="Free",
        command=_python("-m", "sql_agent.evaluate", "--dry-run"),
        timeout_seconds=120,
        summarize=_last_lines,
    ),
    Job(
        id="connections",
        label="Setup and connections",
        description="Python, settings, the database, the API key, the models on offer against Anthropic's list, and one two-token call to the default model.",
        cost="A fraction of a cent",
        command=_python("-m", "sql_agent.check_setup"),
        timeout_seconds=120,
        paid=True,
        summarize=_last_lines,
    ),
    Job(
        id="models_ping",
        label="Ping every model",
        description="One two-token call to each model in the picker, to confirm each still accepts our request.",
        cost="About a tenth of a cent",
        command=_python("-m", "sql_agent.check_setup", "--all-models"),
        timeout_seconds=180,
        paid=True,
        summarize=_last_lines,
    ),
    Job(
        id="evaluation_live",
        label="Evaluation, live",
        description="All evaluation questions asked of the agent and scored. Takes several minutes.",
        cost="Paid: about $4 to $5 on Opus 5 at high effort, much less on Haiku 5.5",
        command=lambda choices, _scratch: [
            sys.executable,
            "-m",
            "sql_agent.evaluate",
            "--model",
            choices["model"],
            "--effort",
            choices["effort"],
        ],
        timeout_seconds=3600,
        choices=(MODEL_CHOICE, EFFORT_CHOICE),
        paid=True,
        enabled=_live_evaluation_enabled,
        disabled_reason=f"Switched off. Set {LIVE_EVALUATION_FLAG}=1 in Backend/.env to allow it.",
        summarize=_last_lines,
    ),
)


@dataclass
class Run:
    id: str
    job: str
    started_by: str
    started_at: str
    choices: dict
    status: str = "running"
    """running, passed, failed, timed_out, cancelled, error or interrupted."""
    finished_at: str | None = None
    exit_code: int | None = None
    summary: dict = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    truncated: bool = False
    dropped: int = 0
    """Lines dropped from the front of `lines` to keep the output under its cap."""

    def lines_after(self, seen: int) -> tuple[list[str], int]:
        """The lines written after the first `seen`, and the count written so far.

        Taken from one snapshot of the list, so a line the worker adds meanwhile is either in
        it or picked up next time, never skipped.
        """
        dropped = self.dropped
        lines = list(self.lines)
        return lines[max(0, seen - dropped):], dropped + len(lines)

    @property
    def done(self) -> bool:
        return self.status != "running"


class JobRunner:
    """Runs one job at a time in a worker thread, keeping each run's output and verdict."""

    def __init__(self, database: AppDatabase, *, jobs: tuple[Job, ...] = JOBS, cwd: Path = BACKEND_DIR) -> None:
        self.database = database
        self.jobs = {job.id: job for job in jobs}
        self.cwd = cwd
        self._lock = threading.Lock()
        self._current: Run | None = None
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        with database.lock:
            database.connection.execute(
                "UPDATE check_runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
                (_now(),),
            )

    def start(self, job_id: str, *, started_by: str, choices: Mapping[str, str] | None = None) -> Run:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobError("unknown_job", f"There is no job called {job_id}.")
        if not job.enabled():
            raise JobError("job_disabled", job.disabled_reason or "This job is switched off.")
        chosen = self._check_choices(job, choices or {})
        with self._lock:
            if self._current is not None and not self._current.done:
                raise JobError("job_busy", f"{self.jobs[self._current.job].label} is still running. Wait for it, or cancel it.")
            run = Run(id=secrets.token_hex(8), job=job.id, started_by=started_by, started_at=_now(), choices=chosen)
            self._current = run
            self._cancelled = False
        self._save(run)
        threading.Thread(target=self._run, args=(job, run), name=f"job-{job.id}", daemon=True).start()
        return run

    def current(self) -> Run | None:
        return self._current

    def live(self, run_id: str) -> Run | None:
        """The run in memory, while it is the current or latest one, for following its output."""
        run = self._current
        return run if run is not None and run.id == run_id else None

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            run = self._current
            if run is None or run.id != run_id or run.done:
                return False
            self._cancelled = True
            if self._process is not None:
                self._process.terminate()
            # Otherwise the worker has not started it yet, and stops it as soon as it does.
            return True

    def history(self, *, job: str | None = None, limit: int = HISTORY_LIMIT) -> list[dict]:
        query = (
            "SELECT id, job, status, started_by, started_at, finished_at, exit_code, choices_json, summary_json"
            " FROM check_runs"
        )
        params: tuple = ()
        if job:
            query += " WHERE job = ?"
            params = (job,)
        query += " ORDER BY started_at DESC LIMIT ?"
        with self.database.lock:
            rows = self.database.connection.execute(query, (*params, limit)).fetchall()
        return [_record(row) for row in rows]

    def get(self, run_id: str) -> dict | None:
        with self.database.lock:
            row = self.database.connection.execute("SELECT * FROM check_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        record = _record(row)
        record["output"] = row["output"]
        record["truncated"] = bool(row["truncated"])
        return record

    def latest_by_job(self) -> dict[str, dict]:
        with self.database.lock:
            rows = self.database.connection.execute(
                "SELECT r.* FROM check_runs r JOIN (SELECT job, MAX(started_at) AS latest FROM check_runs GROUP BY job) l"
                " ON r.job = l.job AND r.started_at = l.latest"
            ).fetchall()
        return {row["job"]: _record(row) for row in rows}

    # Internals ------------------------------------------------------------------------

    def _check_choices(self, job: Job, given: Mapping[str, str]) -> dict:
        unknown = set(given) - {choice.name for choice in job.choices}
        if unknown:
            raise JobError("invalid_choice", f"{job.label} takes no setting called {', '.join(sorted(unknown))}.")
        chosen = {}
        for choice in job.choices:
            value = given.get(choice.name, choice.default)
            if value not in choice.options:
                raise JobError("invalid_choice", f"{value} is not one of the {choice.label.lower()} options.")
            chosen[choice.name] = value
        return chosen

    def _run(self, job: Job, run: Run) -> None:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f"sql-agent-{job.id}-") as folder:
            scratch = Path(folder)
            try:
                env = {**os.environ, "PYTHONUNBUFFERED": "1"}
                env.pop("RUN_LIVE_TESTS", None)  # the test job never calls the model
                process = subprocess.Popen(
                    job.command(run.choices, scratch),
                    cwd=self.cwd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                self._finish(run, "error", None, {"verdict": f"Could not start: {exc}"})
                return
            with self._lock:
                self._process = process
                if self._cancelled:
                    process.terminate()
            timed_out = threading.Event()

            def stop() -> None:
                timed_out.set()
                process.kill()

            timer = threading.Timer(job.timeout_seconds, stop)
            timer.start()
            try:
                for line in process.stdout:
                    self._append(run, line.rstrip("\n"))
                code = process.wait()
            finally:
                timer.cancel()
            if self._cancelled:
                status = "cancelled"
            elif timed_out.is_set():
                status = "timed_out"
            else:
                status = "passed" if code == 0 else "failed"
            try:
                summary = job.summarize(scratch, run.lines) if job.summarize else {}
            except Exception as exc:  # a summary is a convenience; the output stays
                summary = {"verdict": f"No summary: {exc}"}
            if status == "timed_out":
                summary["verdict"] = f"Stopped after {int(job.timeout_seconds)} seconds."
            summary["seconds"] = round(time.monotonic() - started, 1)
            self._finish(run, status, code, summary)

    def _append(self, run: Run, line: str) -> None:
        run.lines.append(line)
        size = sum(len(item) + 1 for item in run.lines)
        while size > MAX_OUTPUT_CHARS and len(run.lines) > 1:
            size -= len(run.lines[0]) + 1
            run.dropped += 1  # counted before the line goes, so a reader never skips one
            run.lines.pop(0)
            run.truncated = True

    def _finish(self, run: Run, status: str, code: int | None, summary: dict) -> None:
        run.exit_code = code
        run.summary = summary
        run.finished_at = _now()
        with self._lock:
            self._process = None
        run.status = status  # set last, so a reader that sees the run done finds every field
        self._save(run)

    def _save(self, run: Run) -> None:
        with self.database.lock:
            self.database.connection.execute(
                "INSERT INTO check_runs (id, job, status, started_by, started_at, finished_at, exit_code,"
                " choices_json, summary_json, output, truncated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET status = excluded.status, finished_at = excluded.finished_at,"
                " exit_code = excluded.exit_code, summary_json = excluded.summary_json,"
                " output = excluded.output, truncated = excluded.truncated",
                (
                    run.id,
                    run.job,
                    run.status,
                    run.started_by,
                    run.started_at,
                    run.finished_at,
                    run.exit_code,
                    json.dumps(run.choices),
                    json.dumps(run.summary),
                    "\n".join(run.lines),
                    int(run.truncated),
                ),
            )


def _record(row) -> dict:
    return {
        "id": row["id"],
        "job": row["job"],
        "status": row["status"],
        "started_by": row["started_by"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "exit_code": row["exit_code"],
        "choices": json.loads(row["choices_json"] or "{}"),
        "summary": json.loads(row["summary_json"] or "{}"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
