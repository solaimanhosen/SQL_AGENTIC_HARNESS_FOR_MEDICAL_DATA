"""The attack catalogue, run against the real database. No model and no network involved."""

import pytest

from sql_agent.check_security import ATTACKS, TOOL_ATTACKS, run_attacks, run_tool_attacks
from sql_agent.config import load_settings
from sql_agent.db import BlockedColumnError, ReadOnlyDatabase
from sql_agent.sql_guard import MAX_QUERY_CHARS, UnsafeQueryError


@pytest.fixture(scope="module")
def db():
    settings = load_settings({})
    if not settings.db_path.exists():
        pytest.skip("synthea.db not built; run python -m sql_agent.load_data")
    # A short timeout keeps the two runaway-query attacks from slowing the suite.
    return ReadOnlyDatabase(settings.db_path, max_rows=50, timeout_seconds=1)


@pytest.fixture(scope="module")
def outcomes(db):
    return run_attacks(db)


def test_every_attack_behaves_as_expected(outcomes):
    unexpected = [
        f"{outcome.attack.id} ({outcome.attack.goal}) was "
        f"{'blocked' if outcome.blocked else 'allowed'}: {outcome.detail}"
        for outcome in outcomes
        if not outcome.as_expected
    ]
    assert not unexpected, unexpected


def test_every_attack_behaves_the_same_with_the_analysis_row_cap(db):
    unexpected = [outcome.attack.id for outcome in run_attacks(db, analysis=True) if not outcome.as_expected]
    assert not unexpected, unexpected


@pytest.fixture(scope="module")
def tool_outcomes(db):
    return {outcome.attack.id: outcome for outcome in run_tool_attacks(db)}


def test_every_attack_through_the_analytics_tools_behaves_as_expected(tool_outcomes):
    unexpected = {
        name: outcome.detail for name, outcome in tool_outcomes.items() if not outcome.as_expected
    }
    assert not unexpected, unexpected
    assert {attack.id for attack in TOOL_ATTACKS} == set(tool_outcomes)


def test_identity_columns_cannot_be_analysed(tool_outcomes):
    for name in ("analysis_identity_value", "analysis_identity_group", "analysis_identity_hidden"):
        assert tool_outcomes[name].detail.startswith("BlockedColumnError"), name


def test_an_analysis_too_big_to_read_whole_is_refused_by_the_cap(tool_outcomes):
    assert "more than 100,000 rows" in tool_outcomes["analysis_partial_data"].detail


def test_the_catalogue_covers_the_main_categories():
    goals = {attack.id for attack in ATTACKS}
    assert {"drop_table", "identity_direct", "attach_database", "second_statement"} <= goals
    assert any(not attack.expect_blocked for attack in ATTACKS), "must prove we do not over-block"


def test_the_database_is_untouched_by_the_whole_catalogue(db, outcomes):
    assert db.run_query("SELECT COUNT(*) FROM patients").rows[0][0] == 108
    assert db.run_query("SELECT COUNT(*) FROM conditions").rows[0][0] == 3517


def test_large_allocations_are_refused(db):
    with pytest.raises(UnsafeQueryError, match="too big"):
        db.run_query("SELECT length(randomblob(200000000))")


def test_internal_schema_tables_are_not_readable(db):
    with pytest.raises(UnsafeQueryError, match="describe_table"):
        db.run_query("SELECT name FROM sqlite_master")


def test_over_long_statements_are_refused(db):
    with pytest.raises(UnsafeQueryError, match="character limit"):
        db.run_query("SELECT 1 WHERE " + "1=1 AND " * 5000 + "1=1")


def test_deeply_nested_statements_are_refused(db):
    with pytest.raises(UnsafeQueryError, match="nested too deeply"):
        db.run_query("SELECT " + "(" * 400 + "1" + ")" * 400)


def test_a_normal_query_is_still_comfortably_within_the_limits(db):
    sql = "SELECT COUNT(*) FROM encounters WHERE encounterclass = 'emergency'"
    assert len(sql) < MAX_QUERY_CHARS
    assert db.run_query(sql).rows[0][0] == 270


def test_blocked_column_errors_name_the_column_so_the_agent_can_recover(db):
    with pytest.raises(BlockedColumnError, match="patients.ssn"):
        db.run_query("SELECT ssn FROM patients")
