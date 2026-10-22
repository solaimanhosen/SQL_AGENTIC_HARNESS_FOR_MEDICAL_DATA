import sys
import time

import pytest

from sql_agent import jobs as jobs_module
from sql_agent.appdb import AppDatabase
from sql_agent.jobs import JOBS, Choice, Job, JobError, JobRunner, Run, _last_lines, _pytest_summary


def _job(job_id, code, *, timeout=20.0, **kwargs):
    """A job that runs a little Python, standing in for a real check."""
    return Job(
        id=job_id,
        label=job_id.title(),
        description="",
        cost="Free",
        command=lambda choices, scratch: [sys.executable, "-c", code, *choices.values()],
        timeout_seconds=timeout,
        summarize=_last_lines,
        **kwargs,
    )


FAKE_JOBS = (
    _job("echo", "print('one'); print('two'); print('All good.')"),
    _job("failing", "import sys; print('broken'); sys.exit(3)"),
    _job("slow", "import time; print('starting', flush=True); time.sleep(30)", timeout=0.5),
    _job("choosy", "import sys; print('chose', sys.argv[1])", choices=(Choice("colour", "Colour", ("red", "blue"), "red"),)),
    _job("off", "print('never')", enabled=lambda: False, disabled_reason="Switched off for the test."),
)


@pytest.fixture
def runner():
    return JobRunner(AppDatabase(), jobs=FAKE_JOBS)


def finished(runner, run, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not run.done and time.monotonic() < deadline:
        time.sleep(0.02)
    assert run.done, "the run did not finish"
    return runner.get(run.id)


def test_a_run_keeps_its_output_and_verdict(runner):
    record = finished(runner, runner.start("echo", started_by="admin-1"))
    assert record["status"] == "passed" and record["exit_code"] == 0
    assert record["output"] == "one\ntwo\nAll good."
    assert record["summary"]["verdict"] == "two All good." and record["summary"]["seconds"] >= 0
    assert record["started_by"] == "admin-1" and record["finished_at"]


def test_a_failing_check_is_failed_with_its_exit_code(runner):
    record = finished(runner, runner.start("failing", started_by="a"))
    assert (record["status"], record["exit_code"], record["output"]) == ("failed", 3, "broken")


def test_a_check_that_runs_too_long_is_stopped(runner):
    record = finished(runner, runner.start("slow", started_by="a"))
    assert record["status"] == "timed_out" and record["output"] == "starting"
    assert record["summary"]["verdict"] == "Stopped after 0 seconds."


def test_only_one_check_runs_at_a_time_and_it_can_be_cancelled(runner):
    slow = runner.start("slow", started_by="a")
    with pytest.raises(JobError) as busy:
        runner.start("echo", started_by="a")
    assert busy.value.kind == "job_busy"
    assert runner.cancel(slow.id)
    assert finished(runner, slow)["status"] == "cancelled"
    assert not runner.cancel(slow.id), "already finished"
    assert finished(runner, runner.start("echo", started_by="a"))["status"] == "passed"


def test_settings_come_only_from_the_job_s_fixed_list(runner):
    assert finished(runner, runner.start("choosy", started_by="a", choices={"colour": "blue"}))["output"] == "chose blue"
    assert finished(runner, runner.start("choosy", started_by="a"))["output"] == "chose red"
    for choices in ({"colour": "green; rm -rf /"}, {"shape": "round"}):
        with pytest.raises(JobError) as refused:
            runner.start("choosy", started_by="a", choices=choices)
        assert refused.value.kind == "invalid_choice"


def test_unknown_and_disabled_jobs_are_refused(runner):
    for job_id, kind in (("nope", "unknown_job"), ("off", "job_disabled")):
        with pytest.raises(JobError) as refused:
            runner.start(job_id, started_by="a")
        assert refused.value.kind == kind


def test_history_is_newest_first_and_names_the_latest_of_each_job(runner):
    finished(runner, runner.start("echo", started_by="a"))
    finished(runner, runner.start("failing", started_by="a"))
    latest = finished(runner, runner.start("echo", started_by="a"))
    assert [item["job"] for item in runner.history()] == ["echo", "failing", "echo"]
    assert [item["job"] for item in runner.history(job="failing")] == ["failing"]
    assert "output" not in runner.history()[0]
    assert runner.latest_by_job()["echo"]["id"] == latest["id"]


def test_a_run_cut_short_by_a_restart_is_marked_interrupted(runner):
    database = runner.database
    database.connection.execute(
        "INSERT INTO check_runs (id, job, status, started_by, started_at) VALUES ('0123456789abcdef', 'echo', 'running', 'a', '2026-10-21T00:00:00+00:00')"
    )
    JobRunner(database, jobs=FAKE_JOBS)
    assert database.connection.execute("SELECT status FROM check_runs").fetchone()[0] == "interrupted"


def test_long_output_keeps_its_end_and_following_it_never_skips_a_line(monkeypatch):
    monkeypatch.setattr(jobs_module, "MAX_OUTPUT_CHARS", 40)
    runner = JobRunner(AppDatabase(), jobs=(_job("loud", "print('\\n'.join(f'line {n:02}' for n in range(20)))"),))
    run = runner.start("loud", started_by="a")
    seen, followed = 0, []
    while not run.done:
        new, seen = run.lines_after(seen)
        followed += new
    new, seen = run.lines_after(seen)
    followed += new
    record = runner.get(run.id)
    assert record["truncated"] and record["output"].endswith("line 19") and len(record["output"]) <= 40
    assert followed[-1] == "line 19" and seen == 20


def test_following_from_a_snapshot_returns_only_new_lines():
    run = Run(id="r", job="j", started_by="a", started_at="t", choices={})
    run.lines = ["a", "b", "c"]
    assert run.lines_after(0) == (["a", "b", "c"], 3)
    run.lines.append("d")
    assert run.lines_after(3) == (["d"], 4)
    run.dropped, run.lines = 2, ["c", "d", "e"]
    assert run.lines_after(4) == (["e"], 5)


def test_a_pytest_report_is_summarised_with_the_failing_tests(tmp_path):
    (tmp_path / "junit.xml").write_text(
        '<testsuites><testsuite tests="4" failures="1" errors="0" skipped="1">'
        '<testcase classname="tests.test_a" name="test_ok"/>'
        '<testcase classname="tests.test_a" name="test_bad"><failure message="x"/></testcase>'
        '<testcase classname="tests.test_b" name="test_ok"/>'
        '<testcase classname="tests.test_b" name="test_skip"><skipped/></testcase>'
        "</testsuite></testsuites>"
    )
    summary = _pytest_summary(tmp_path, [])
    assert (summary["passed"], summary["failures"], summary["skipped"]) == (2, 1, 1)
    assert summary["failed"] == ["tests.test_a::test_bad"]
    assert summary["verdict"] == "2 passed, 1 failed, 1 skipped"


def test_every_real_job_is_a_fixed_command_without_a_shell(tmp_path, monkeypatch):
    monkeypatch.delenv("SQL_AGENT_ADMIN_LIVE_EVAL", raising=False)
    by_id = {job.id: job for job in JOBS}
    assert set(by_id) == {
        "tests", "security", "semantics", "evaluation_dry_run", "connections", "models_ping", "evaluation_live"
    }
    for job in JOBS:
        choices = {choice.name: choice.default for choice in job.choices}
        command = job.command(choices, tmp_path)
        assert command[0] == sys.executable and all(isinstance(part, str) for part in command)
        assert (job.paid) == (job.id in {"connections", "models_ping", "evaluation_live"})
    assert "RUN_LIVE_TESTS" not in " ".join(by_id["tests"].command({}, tmp_path))
    assert not by_id["evaluation_live"].enabled(), "a paid evaluation is off unless switched on"
    monkeypatch.setenv("SQL_AGENT_ADMIN_LIVE_EVAL", "1")
    assert by_id["evaluation_live"].enabled()
    assert by_id["evaluation_live"].command({"model": "claude-haiku-5-5", "effort": "low"}, tmp_path)[-4:] == [
        "--model", "claude-haiku-5-5", "--effort", "low"
    ]
