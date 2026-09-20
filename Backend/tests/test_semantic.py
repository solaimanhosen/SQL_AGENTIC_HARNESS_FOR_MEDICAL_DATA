from datetime import date

import pytest

from sql_agent.config import load_settings
from sql_agent.db import BLOCKED_COLUMNS, ReadOnlyDatabase
from sql_agent.semantic import (
    load_semantic_layer,
    resolve_as_of_date,
    run_definition_checks,
    validate_catalog,
)

AS_OF = date(2026, 8, 16)


@pytest.fixture(scope="module")
def layer():
    return load_semantic_layer()


@pytest.fixture(scope="module")
def real_db():
    settings = load_settings({})
    if not settings.db_path.exists():
        pytest.skip("synthea.db not built; run python -m sql_agent.load_data")
    return ReadOnlyDatabase.from_settings(settings)


def test_layer_loads(layer):
    assert len(layer.tables) == 18
    assert layer.rules
    assert {"diabetes", "emergency_visit", "age_band"} <= set(layer.definitions)


def test_blocked_columns_are_never_documented(layer):
    for name, table in layer.tables.items():
        leaked = {column.lower() for column in table.columns} & BLOCKED_COLUMNS.get(name, frozenset())
        assert not leaked, f"{name} documents blocked columns {leaked}"


def test_every_definition_carries_a_check_and_a_known_status(layer):
    for definition in layer.definitions.values():
        assert definition.checks, f"{definition.name} has no check against the data"
        assert definition.status in {"assumed", "confirmed"}
        assert definition.summary and definition.sql


def test_as_of_is_substituted_into_sql(layer):
    sql = layer.definition("patient_age").resolved_sql(AS_OF)
    assert "2026-08-16" in sql and "{as_of}" not in sql


def test_check_sql_reuses_the_definition_sql(layer):
    definition = layer.definition("diabetes")
    sql = definition.resolved_check_sql(definition.checks[0], AS_OF)
    assert "44054006" in sql and "{sql}" not in sql


def test_diabetes_excludes_prediabetes(layer):
    definition = layer.definition("diabetes")
    assert 714628002 in definition.excludes
    assert "714628002" not in definition.sql


def test_unknown_names_list_the_known_ones(layer):
    with pytest.raises(KeyError, match="Known definitions"):
        layer.definition("nope")
    with pytest.raises(KeyError, match="Known tables"):
        layer.table("nope")


def test_overview_states_the_as_of_date_and_stays_compact(layer):
    overview = layer.render_overview(AS_OF)
    assert "2026-08-16" in overview
    assert "encounterclass values: ambulatory" in overview
    # Roughly 2,000 tokens. The prompt has to stay affordable on every agent turn.
    assert len(overview) < 8_000


def test_definitions_render_marks_assumptions(layer):
    text = layer.render_definitions(AS_OF)
    assert "[assumed, not yet confirmed]" in text
    assert "{as_of}" not in text


def test_catalog_matches_the_database(layer, real_db):
    assert validate_catalog(layer, real_db) == []


def test_every_definition_check_passes_against_the_data(layer, real_db):
    failures = [
        f"{result.definition}: {result.check.description} expected {result.check.expectation}, "
        f"got {result.error or result.value}"
        for result in run_definition_checks(layer, real_db, AS_OF)
        if not result.passed
    ]
    assert not failures, failures


def test_as_of_resolution_follows_the_setting(real_db):
    assert resolve_as_of_date(load_settings({}), real_db) == AS_OF
    assert resolve_as_of_date(load_settings({"SQL_AGENT_AS_OF_DATE": "2024-01-31"}), real_db) == date(2024, 1, 31)
    assert resolve_as_of_date(load_settings({"SQL_AGENT_AS_OF_DATE": "today"}), real_db) == date.today()
