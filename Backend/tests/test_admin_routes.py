"""The admin console's routes, with harmless jobs in place of the real checks."""

import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from sql_agent.jobs import Job, JobRunner, _last_lines
from tests.test_service import CSRF, TEST_PASSWORD, StubAgent, _ask, _second_user, _sign_in, db, settings  # noqa: F401
from sql_agent.service import create_app


def _job(job_id, code, **kwargs):
    return Job(
        id=job_id,
        label=job_id.title(),
        description=f"The {job_id} job.",
        cost="Free",
        command=lambda choices, scratch: [sys.executable, "-c", code],
        timeout_seconds=20,
        summarize=_last_lines,
        **kwargs,
    )


@pytest.fixture
def admin(settings, db):
    """A signed-in admin's client, on a service whose jobs only print."""
    agent = StubAgent(settings, db)
    app = create_app(agent, google=None)
    app.state.jobs.jobs = {
        job.id: job
        for job in (
            _job("echo", "print('one'); print('All good.')"),
            _job("slow", "import time; print('working', flush=True); time.sleep(2); print('done')"),
        )
    }
    client = TestClient(app, headers=CSRF)
    _sign_in(client, "admin@example.org", admin=True)
    return client


def _wait(client, run_id):
    for _ in range(200):
        record = client.get(f"/api/admin/runs/{run_id}").json()
        if record["status"] != "running":
            return record
        time.sleep(0.05)
    raise AssertionError("the run did not finish")


def test_only_admins_may_use_the_console(admin):
    user = _second_user(admin, "user@example.org")
    signed_out = TestClient(admin.app, headers=CSRF)
    for method, path in (
        ("get", "/api/admin/overview"),
        ("get", "/api/admin/metrics"),
        ("get", "/api/admin/jobs"),
        ("post", "/api/admin/jobs/echo/runs"),
        ("get", "/api/admin/users"),
        ("patch", "/api/admin/settings"),
    ):
        kwargs = {"json": {"registration_open": False}} if method == "patch" else {}
        if method == "post":
            kwargs = {"json": {}}
        response = getattr(user, method)(path, **kwargs)
        assert response.status_code == 403 and response.json()["error"] == "forbidden", path
        assert getattr(signed_out, method)(path, **kwargs).status_code == 401, path
    assert admin.get("/api/admin/settings").json() == {"registration_open": True}, "nothing was changed"


def test_the_overview_says_what_is_up_and_who_uses_it(admin):
    _ask(admin)
    overview = admin.get("/api/admin/overview").json()
    assert overview["database"] == {"ok": True, "tables": 2, "as_of": "2026-08-16"}
    assert overview["application_database"]["schema_version"] >= 5
    assert overview["people"] == {"accounts": 1, "admins": 1, "disabled": 0}
    assert overview["conversations"] == {"conversations": 1, "questions": 1}
    assert overview["budget"]["spent_today"] == 1350
    assert overview["google_enabled"] is False and overview["registration_open"] is True


def test_metrics_read_the_logs_and_name_people_only_for_admins(admin, settings):
    _ask(admin)
    metrics = admin.get("/api/admin/metrics", params={"days": 7}).json()
    assert len(metrics["requests"]["days"]) == 7 and metrics["requests"]["total"] >= 2
    assert metrics["runs"]["questions"] == 1
    assert metrics["runs"]["by_user"][0]["email"] == "admin@example.org"
    assert admin.get("/api/admin/metrics", params={"days": 0}).status_code == 422


def test_a_check_is_started_followed_live_and_kept(admin):
    jobs = {job["id"]: job for job in admin.get("/api/admin/jobs").json()}
    assert jobs["echo"]["latest"] is None and jobs["echo"]["enabled"] is True

    started = admin.post("/api/admin/jobs/echo/runs", json={})
    assert started.status_code == 202
    run_id = started.json()["id"]
    stream = admin.get(f"/api/admin/runs/{run_id}/stream")
    events = [
        (block.split("\n")[0].removeprefix("event: "), json.loads(block.split("\n")[1].removeprefix("data: ")))
        for block in stream.text.strip().split("\n\n")
    ]
    assert [data["text"] for name, data in events if name == "line"] == ["one", "All good."]
    assert events[-1][0] == "done" and events[-1][1]["status"] == "passed"

    record = admin.get(f"/api/admin/runs/{run_id}").json()
    assert record["output"] == "one\nAll good." and record["started_by"] == admin.user_id
    assert admin.get("/api/admin/runs").json()[0]["id"] == run_id
    assert {job["id"]: job for job in admin.get("/api/admin/jobs").json()}["echo"]["latest"]["status"] == "passed"


def test_a_second_check_waits_for_the_first_and_a_running_one_can_be_cancelled(admin):
    slow = admin.post("/api/admin/jobs/slow/runs", json={}).json()
    busy = admin.post("/api/admin/jobs/echo/runs", json={})
    assert busy.status_code == 409 and busy.json()["error"] == "job_busy"
    assert admin.post(f"/api/admin/runs/{slow['id']}/cancel").json() == {"cancelling": True}
    assert _wait(admin, slow["id"])["status"] == "cancelled"
    assert admin.post(f"/api/admin/runs/{slow['id']}/cancel").status_code == 409


def test_unknown_jobs_runs_and_settings_are_refused(admin):
    assert admin.post("/api/admin/jobs/nope/runs", json={}).status_code == 404
    assert admin.post("/api/admin/jobs/echo/runs", json={"choices": {"x": "y"}}).status_code == 422
    assert admin.post("/api/admin/jobs/tests.py/runs", json={}).status_code == 422
    assert admin.get("/api/admin/runs/0123456789abcdef").status_code == 404
    assert admin.get("/api/admin/runs/not-a-run").status_code == 422


def test_starting_a_check_needs_the_application_header(admin):
    bare = TestClient(admin.app)
    bare.cookies = admin.cookies
    response = bare.post("/api/admin/jobs/echo/runs", json={})
    assert response.status_code == 403 and response.json()["error"] == "cross_site"


def test_people_are_listed_promoted_disabled_and_given_a_temporary_password(admin):
    user = _second_user(admin, "user@example.org")
    _ask(user, "A question")
    people = {person["email"]: person for person in admin.get("/api/admin/users").json()}
    assert people["user@example.org"]["conversations"] == 1 and people["user@example.org"]["questions_this_month"] == 1
    assert "password_hash" not in json.dumps(people)
    target = people["user@example.org"]["id"]

    assert admin.patch(f"/api/admin/users/{target}", json={"role": "admin"}).json()["role"] == "admin"
    assert admin.patch(f"/api/admin/users/{target}", json={"role": "user"}).json()["role"] == "user"
    assert admin.patch(f"/api/admin/users/{target}", json={"disabled": True}).json()["disabled"] is True
    assert user.get("/api/auth/me").status_code == 401, "disabling signs them out at once"
    admin.patch(f"/api/admin/users/{target}", json={"disabled": False})

    temporary = admin.post(f"/api/admin/users/{target}/reset-password").json()["temporary_password"]
    assert len(temporary) >= 16
    fresh = TestClient(admin.app, headers=CSRF)
    assert fresh.post("/api/auth/login", json={"email": "user@example.org", "password": TEST_PASSWORD}).status_code == 401
    assert fresh.post("/api/auth/login", json={"email": "user@example.org", "password": temporary}).status_code == 200


def test_an_admin_cannot_lock_themselves_or_everyone_out(admin):
    me = admin.user_id
    for change in ({"role": "user"}, {"disabled": True}):
        response = admin.patch(f"/api/admin/users/{me}", json=change)
        assert response.status_code == 409 and response.json()["error"] == "self_change"
    other = _second_user(admin, "second@example.org")
    admin.patch(f"/api/admin/users/{other.user_id}", json={"role": "admin"})
    # Now there are two admins: demoting the other is fine, and leaves one.
    assert admin.patch(f"/api/admin/users/{other.user_id}", json={"role": "user"}).status_code == 200
    assert admin.patch("/api/admin/users/" + "0" * 32, json={"role": "admin"}).status_code == 404
    assert admin.patch(f"/api/admin/users/{other.user_id}", json={"role": "owner"}).status_code == 422


def test_registration_can_be_closed_from_the_console(admin):
    assert admin.patch("/api/admin/settings", json={"registration_open": False}).json() == {"registration_open": False}
    stranger = TestClient(admin.app, headers=CSRF)
    assert stranger.get("/api/auth/config").json()["registration_open"] is False
    refused = stranger.post("/api/auth/register", json={"email": "new@example.org", "password": TEST_PASSWORD})
    assert refused.status_code == 403
