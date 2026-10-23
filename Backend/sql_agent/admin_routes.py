"""The admin console's routes. Every one needs an admin's session (ADR 0008).

- Overview: is everything up, who uses it, what it has spent, and the latest check of each kind.
- Metrics: requests, errors, latency, questions, tokens and estimated cost per day, read from
  the request and run logs.
- Checks: the fixed jobs in jobs.py, started one at a time, followed live, kept as history.
- People: list accounts, change a role, disable or enable, set a temporary password.
- Settings: whether anyone may sign up.

An admin sees totals and accounts, never the text of anyone's conversations.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .accounts import AccountError, AccountStore, User
from .auth import Sessions
from .conversations import ConversationStore
from .jobs import JobError, JobRunner
from .limits import SpendingLimits
from .metrics import request_metrics, run_metrics

TEMPORARY_PASSWORD_BYTES = 12  # 16 characters once encoded
RunId = Path(pattern=r"^[0-9a-f]{16}$")
UserId = Path(pattern=r"^[0-9a-f]{32}$")


class StartRun(BaseModel):
    choices: dict[str, str] = Field(default_factory=dict, max_length=4)


class UserChange(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(user|admin)$")
    disabled: bool | None = None


class SettingsChange(BaseModel):
    registration_open: bool


class SelfChange(Exception):
    """An admin may not demote or disable themselves, or remove the last admin."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def admin_router(
    *,
    agent,
    accounts: AccountStore,
    conversations: ConversationStore,
    limits: SpendingLimits,
    sessions: Sessions,
    jobs: JobRunner,
    google_enabled: bool,
    email_enabled: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin", dependencies=[Depends(sessions.admin)])
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    settings = agent.settings

    def registration_open() -> bool:
        return accounts.registration_open(default=settings.registration_open)

    @router.get("/overview")
    def overview() -> dict:
        """Whether each part is up, who uses the service, and the latest check of each kind."""
        try:
            tables = len(agent.db.table_names())
        except Exception:
            tables = 0
        users = accounts.list_users()
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        return {
            "service": {"started_at": started_at, "uptime_seconds": round(time.monotonic() - started)},
            "database": {"ok": tables > 0, "tables": tables, "as_of": str(agent.as_of)},
            "application_database": {"schema_version": conversations.schema_version()},
            "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
            "default_model": settings.model,
            "default_effort": settings.effort,
            "google_enabled": google_enabled,
            "email_enabled": email_enabled,
            "registration_open": registration_open(),
            "people": {
                "accounts": len(users),
                "admins": sum(user.is_admin for user in users),
                "disabled": sum(user.disabled for user in users),
            },
            "conversations": conversations.totals(since=midnight),
            "budget": limits.usage(),
            "latest_checks": jobs.latest_by_job(),
        }

    @router.get("/metrics")
    def metrics(days: int = Query(default=14, ge=1, le=90)) -> dict:
        """Per day, over the last `days` (UTC): requests, refusals, errors and latency; questions, tokens and cost."""
        runs = run_metrics(settings.log_path, days=days)
        emails = {user.id: user.email for user in accounts.list_users()}
        for row in runs["by_user"]:
            # The run log names people by id; only an admin's view turns that into an email.
            row["email"] = emails.get(row["user_id"])
        return {
            "days": days,
            "requests": request_metrics(settings.request_log_path, days=days),
            "runs": runs,
            "logs": {
                "requests": settings.request_log_path is not None,
                "runs": settings.log_path is not None,
            },
        }

    @router.get("/jobs")
    def list_jobs() -> list[dict]:
        latest = jobs.latest_by_job()
        current = jobs.current()
        return [
            {
                "id": job.id,
                "label": job.label,
                "description": job.description,
                "cost": job.cost,
                "paid": job.paid,
                "enabled": job.enabled(),
                "disabled_reason": None if job.enabled() else job.disabled_reason,
                "timeout_seconds": job.timeout_seconds,
                "choices": [
                    {"name": choice.name, "label": choice.label, "options": list(choice.options), "default": choice.default}
                    for choice in job.choices
                ],
                "running": current is not None and not current.done and current.job == job.id,
                "latest": latest.get(job.id),
            }
            for job in jobs.jobs.values()
        ]

    @router.post("/jobs/{job_id}/runs", status_code=202)
    def start_run(body: StartRun, job_id: str = Path(pattern=r"^[a-z_]{1,40}$"), user: User = Depends(sessions.admin)) -> dict:
        run = jobs.start(job_id, started_by=user.id, choices=body.choices)
        return {"id": run.id, "job": run.job, "status": run.status, "started_at": run.started_at, "choices": run.choices}

    @router.get("/runs")
    def list_runs(job: str | None = Query(default=None, pattern=r"^[a-z_]{1,40}$")) -> list[dict]:
        return jobs.history(job=job)

    @router.get("/runs/{run_id}")
    def get_run(run_id: str = RunId) -> dict:
        record = jobs.get(run_id)
        if record is None:
            raise JobError("unknown_run", "There is no such run.")
        return record

    @router.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str = RunId) -> dict:
        if not jobs.cancel(run_id):
            raise JobError("not_running", "That run is not running.")
        return {"cancelling": True}

    @router.get(
        "/runs/{run_id}/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    async def follow_run(request: Request, run_id: str = RunId) -> StreamingResponse:
        """The run's output as server-sent events: `line` for each line, then `done` with the record."""
        if jobs.live(run_id) is None and jobs.get(run_id) is None:
            raise JobError("unknown_run", "There is no such run.")

        async def events() -> AsyncIterator[str]:
            seen = 0
            while True:
                run = jobs.live(run_id)
                if run is None:
                    # Finished before, or before a restart: replay what was kept.
                    record = jobs.get(run_id) or {}
                    for line in (record.get("output") or "").splitlines():
                        yield _event("line", {"text": line})
                    yield _event("done", {key: value for key, value in record.items() if key != "output"})
                    return
                new, seen = run.lines_after(seen)
                for line in new:
                    yield _event("line", {"text": line})
                if run.done:
                    yield _event("done", jobs.get(run_id) or {})
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @router.get("/users")
    def list_users() -> list[dict]:
        month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        counts = conversations.owner_counts(since=month)
        return [
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "disabled": user.disabled,
                "has_password": user.has_password,
                "google_linked": user.google_linked,
                "created_at": user.created_at,
                "last_seen_at": user.last_seen_at,
                "conversations": counts.get(user.id, {}).get("conversations", 0),
                "questions_this_month": counts.get(user.id, {}).get("questions", 0),
            }
            for user in accounts.list_users()
        ]

    @router.patch("/users/{user_id}")
    def change_user(body: UserChange, user_id: str = UserId, admin: User = Depends(sessions.admin)) -> dict:
        target = accounts.get_user(user_id)
        if target is None:
            raise AccountError("unknown_user", "No such account.")
        if target.id == admin.id and (body.role == "user" or body.disabled):
            raise SelfChange("You cannot remove your own admin role or disable your own account.")
        removes_admin = target.is_admin and not target.disabled and (body.role == "user" or body.disabled)
        if removes_admin and _enabled_admins(accounts) <= 1:
            raise SelfChange("This is the last enabled admin. Make someone else an admin first.")
        if body.role is not None:
            accounts.set_role(user_id, body.role)
        if body.disabled is not None:
            accounts.set_disabled(user_id, body.disabled)
        updated = accounts.get_user(user_id)
        return {"id": updated.id, "role": updated.role, "disabled": updated.disabled}

    @router.post("/users/{user_id}/reset-password")
    def reset_password(user_id: str = UserId) -> dict:
        """Give the person a temporary password, shown once here, and end all their sessions."""
        if accounts.get_user(user_id) is None:
            raise AccountError("unknown_user", "No such account.")
        temporary = secrets.token_urlsafe(TEMPORARY_PASSWORD_BYTES)
        accounts.reset_password(user_id, temporary)
        return {"temporary_password": temporary}

    @router.get("/settings")
    def get_settings() -> dict:
        return {"registration_open": registration_open()}

    @router.patch("/settings")
    def change_settings(body: SettingsChange) -> dict:
        accounts.set_registration(body.registration_open)
        return {"registration_open": registration_open()}

    return router


def _enabled_admins(accounts: AccountStore) -> int:
    return sum(1 for user in accounts.list_users() if user.is_admin and not user.disabled)


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

