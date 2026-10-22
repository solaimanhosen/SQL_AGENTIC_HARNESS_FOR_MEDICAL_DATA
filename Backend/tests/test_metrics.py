import json
from datetime import date

import pytest

from sql_agent.metrics import percentile, request_metrics, run_metrics

TODAY = date(2026, 10, 21)


def _write(path, records):
    path.write_text("\n".join(records) + "\n")


def test_requests_are_counted_per_day_with_errors_refusals_and_latency(tmp_path):
    log = tmp_path / "requests.jsonl"
    rows = [
        {"timestamp": "2026-10-20T10:00:00+00:00", "status": 200, "elapsed_ms": 10, "refused": None},
        {"timestamp": "2026-10-21T10:00:00+00:00", "status": 200, "elapsed_ms": 20, "refused": None},
        {"timestamp": "2026-10-21T10:01:00+00:00", "status": 401, "elapsed_ms": 1, "refused": "unauthenticated"},
        {"timestamp": "2026-10-21T10:02:00+00:00", "status": 429, "elapsed_ms": 2, "refused": "user_budget"},
        {"timestamp": "2026-10-21T10:03:00+00:00", "status": 502, "elapsed_ms": 900, "refused": None},
        {"timestamp": "2026-09-01T10:00:00+00:00", "status": 200, "elapsed_ms": 5},  # before the window
    ]
    _write(log, [json.dumps(row) for row in rows] + ["not json", '{"timestamp": "nonsense"}'])
    metrics = request_metrics(log, days=2, today=TODAY)
    assert [day["day"] for day in metrics["days"]] == ["2026-10-20", "2026-10-21"]
    today = metrics["days"][1]
    assert (today["requests"], today["errors"], today["refused"]) == (4, 1, 2)
    assert today["p95_ms"] == 900 and metrics["days"][0]["p50_ms"] == 10
    assert (metrics["total"], metrics["errors"], metrics["refused"]) == (5, 1, 2)
    assert metrics["refusals"] == {"unauthenticated": 1, "user_budget": 1}


def test_a_missing_log_gives_empty_days_not_an_error(tmp_path):
    metrics = request_metrics(tmp_path / "absent.jsonl", days=3, today=TODAY)
    assert [day["requests"] for day in metrics["days"]] == [0, 0, 0]
    assert metrics["p50_ms"] is None
    assert run_metrics(None, days=1, today=TODAY)["questions"] == 0


def test_questions_are_counted_by_day_model_and_person_with_estimated_cost(tmp_path):
    log = tmp_path / "runs.jsonl"
    rows = [
        {"timestamp": "2026-10-21T09:00:00+00:00", "model": "claude-opus-5", "input_tokens": 1_000_000, "output_tokens": 100_000, "user_id": "u1"},
        {"timestamp": "2026-10-21T09:30:00+00:00", "model": "claude-haiku-5-5", "input_tokens": 1_000_000, "output_tokens": 0, "user_id": "u2"},
        {"timestamp": "2026-10-20T09:30:00+00:00", "model": "claude-retired", "input_tokens": 10, "output_tokens": 5},
    ]
    _write(log, [json.dumps(row) for row in rows])
    metrics = run_metrics(log, days=2, today=TODAY)
    assert [day["questions"] for day in metrics["days"]] == [1, 2]
    by_model = {row["model"]: row for row in metrics["by_model"]}
    assert by_model["claude-opus-5"]["estimated_cost_usd"] == pytest.approx(7.5)
    assert by_model["claude-haiku-5-5"]["label"] == "Haiku 5.5" and by_model["claude-haiku-5-5"]["estimated_cost_usd"] == pytest.approx(0.1)
    assert by_model["claude-retired"]["estimated_cost_usd"] == 0
    assert [row["user_id"] for row in metrics["by_user"]] == ["u1", "u2", "before accounts"]
    assert metrics["estimated_cost_usd"] == pytest.approx(7.6)


def test_percentiles_use_the_nearest_rank():
    assert percentile([], 0.5) is None
    assert percentile([5], 0.95) == 5
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert percentile([3, 1, 2], 0.5) == 2
