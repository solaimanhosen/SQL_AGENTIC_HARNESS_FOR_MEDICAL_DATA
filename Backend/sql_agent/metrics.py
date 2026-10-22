"""Figures for the admin console, read from the two logs the service already writes.

`logs/requests.jsonl` has one line per HTTP request: when, which path, the status, how long
it took, and why it was refused. `logs/runs.jsonl` has one line per answered question: the
model, the effort, the tokens, and who asked, by id. Nothing new is recorded for this; a
line that cannot be read is skipped, never fatal.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .models import find_model

REFUSAL_STATUSES = frozenset({401, 403, 413, 429})


def _records(path: Path | None, since: date) -> Iterator[tuple[date, dict]]:
    if path is None or not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                day = datetime.fromisoformat(record["timestamp"]).astimezone(timezone.utc).date()
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if day >= since:
                yield day, record


def _days(since: date, until: date) -> list[str]:
    return [(since + timedelta(days=offset)).isoformat() for offset in range((until - since).days + 1)]


def percentile(values: list[float], share: float) -> float | None:
    """The value below which `share` of them fall, by the nearest-rank method."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def request_metrics(path: Path | None, *, days: int, today: date | None = None) -> dict:
    """Requests per day: how many, how many failed or were refused, and how long they took."""
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=days - 1)
    per_day: dict[str, dict] = {day: {"requests": 0, "errors": 0, "refused": 0, "times": []} for day in _days(since, today)}
    refusals: dict[str, int] = defaultdict(int)
    for day, record in _records(path, since):
        bucket = per_day.setdefault(day.isoformat(), {"requests": 0, "errors": 0, "refused": 0, "times": []})
        bucket["requests"] += 1
        status = record.get("status") or 0
        if status >= 500:
            bucket["errors"] += 1
        elif status in REFUSAL_STATUSES or record.get("refused"):
            bucket["refused"] += 1
            refusals[str(record.get("refused") or status)] += 1
        if isinstance(record.get("elapsed_ms"), (int, float)):
            bucket["times"].append(record["elapsed_ms"])
    all_times = [time for bucket in per_day.values() for time in bucket["times"]]
    return {
        "days": [
            {
                "day": day,
                "requests": bucket["requests"],
                "errors": bucket["errors"],
                "refused": bucket["refused"],
                "p50_ms": percentile(bucket["times"], 0.5),
                "p95_ms": percentile(bucket["times"], 0.95),
            }
            for day, bucket in sorted(per_day.items())
        ],
        "total": sum(bucket["requests"] for bucket in per_day.values()),
        "errors": sum(bucket["errors"] for bucket in per_day.values()),
        "refused": sum(bucket["refused"] for bucket in per_day.values()),
        "p50_ms": percentile(all_times, 0.5),
        "p95_ms": percentile(all_times, 0.95),
        "refusals": dict(sorted(refusals.items(), key=lambda item: -item[1])),
    }


def run_metrics(path: Path | None, *, days: int, today: date | None = None) -> dict:
    """Answered questions per day, and by model and by person, with tokens and estimated cost."""
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=days - 1)
    empty = lambda: {"questions": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}  # noqa: E731
    per_day: dict[str, dict] = {day: empty() for day in _days(since, today)}
    by_model: dict[str, dict] = defaultdict(empty)
    by_user: dict[str, dict] = defaultdict(empty)
    for day, record in _records(path, since):
        tokens_in = int(record.get("input_tokens") or 0)
        tokens_out = int(record.get("output_tokens") or 0)
        model = str(record.get("model") or "unknown")
        option = find_model(model)
        cost = option.cost(tokens_in, tokens_out) if option else 0.0
        user = record.get("user_id") or "before accounts"
        for bucket in (per_day.setdefault(day.isoformat(), empty()), by_model[model], by_user[user]):
            bucket["questions"] += 1
            bucket["input_tokens"] += tokens_in
            bucket["output_tokens"] += tokens_out
            bucket["estimated_cost_usd"] += cost

    def rounded(bucket: dict) -> dict:
        return {**bucket, "estimated_cost_usd": round(bucket["estimated_cost_usd"], 6)}

    return {
        "days": [{"day": day, **rounded(bucket)} for day, bucket in sorted(per_day.items())],
        "by_model": [
            {"model": model, "label": find_model(model).label if find_model(model) else model, **rounded(bucket)}
            for model, bucket in sorted(by_model.items(), key=lambda item: -item[1]["questions"])
        ],
        "by_user": [
            {"user_id": user, **rounded(bucket)}
            for user, bucket in sorted(by_user.items(), key=lambda item: -item[1]["input_tokens"])
        ],
        "questions": sum(bucket["questions"] for bucket in per_day.values()),
        "estimated_cost_usd": round(sum(bucket["estimated_cost_usd"] for bucket in per_day.values()), 6),
    }
