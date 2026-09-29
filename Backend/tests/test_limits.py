from datetime import date

import pytest

from sql_agent.limits import LimitExceeded, SpendingLimits


class Clock:
    def __init__(self):
        self.day = date(2026, 9, 28)

    def __call__(self):
        return self.day


def _limits(clock=None, **overrides):
    settings = dict(max_concurrent_runs=2, daily_token_budget=100_000, conversation_token_budget=80_000, reserve_tokens=30_000)
    settings.update(overrides)
    return SpendingLimits(today=clock or Clock(), **settings)


def _refused(limits, conversation_id="c1"):
    with pytest.raises(LimitExceeded) as caught:
        limits.reserve(conversation_id)
    return caught.value.kind


def test_a_run_reserves_then_settles_to_what_it_used():
    limits = _limits()
    reservation = limits.reserve("c1")
    assert limits.usage()["reserved_today"] == 30_000 and limits.usage()["running"] == 1
    limits.settle(reservation, 12_000)
    usage = limits.usage()
    assert (usage["spent_today"], usage["reserved_today"], usage["running"]) == (12_000, 0, 0)


def test_a_failed_run_keeps_its_reservation_because_its_cost_is_unknown():
    limits = _limits()
    limits.settle(limits.reserve("c1"), None)
    assert limits.usage()["spent_today"] == 30_000


def test_runs_beyond_the_concurrency_limit_are_refused_not_queued():
    limits = _limits()
    first, _ = limits.reserve("a"), limits.reserve("b")
    assert _refused(limits, "c") == "too_many_runs"
    limits.settle(first, 1_000)
    limits.reserve("c")


def test_runs_still_in_progress_count_against_the_daily_budget():
    limits = _limits(max_concurrent_runs=10)
    limits.reserve("a")
    limits.reserve("b")
    limits.reserve("c")
    assert _refused(limits, "d") == "daily_budget", "90,000 reserved leaves no room for another 30,000"


def test_the_daily_budget_counts_finished_runs_and_resets_at_midnight_utc():
    clock = Clock()
    limits = _limits(clock, daily_token_budget=50_000, conversation_token_budget=10**6)
    limits.settle(limits.reserve("a"), 25_000)
    assert _refused(limits, "b") == "daily_budget"
    clock.day = date(2026, 9, 29)
    limits.reserve("b")
    assert limits.usage()["day"] == "2026-09-29"


def test_a_run_from_yesterday_does_not_charge_today():
    clock = Clock()
    limits = _limits(clock)
    reservation = limits.reserve("a")
    clock.day = date(2026, 9, 29)
    limits.settle(reservation, 20_000)
    usage = limits.usage()
    assert (usage["spent_today"], usage["reserved_today"], usage["running"]) == (0, 0, 0)


def test_one_conversation_cannot_use_up_the_day():
    limits = _limits(daily_token_budget=10**6, conversation_token_budget=70_000)
    limits.settle(limits.reserve("long"), 45_000)
    assert _refused(limits, "long") == "conversation_budget", "45,000 spent plus 30,000 reserved passes 70,000"
    limits.reserve("fresh")


def test_refusals_explain_themselves():
    limits = _limits(max_concurrent_runs=1)
    limits.reserve("a")
    with pytest.raises(LimitExceeded, match="Try again shortly"):
        limits.reserve("b")
