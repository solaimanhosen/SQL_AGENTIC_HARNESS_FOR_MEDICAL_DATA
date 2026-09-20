from datetime import date

import pytest

from sql_agent.db import ReadOnlyDatabase
from sql_agent.formatting import format_table
from sql_agent.semantic import load_semantic_layer
from sql_agent.tools import ToolBox

AS_OF = date(2026, 8, 16)


@pytest.fixture
def toolbox(sample_db_path):
    events = []
    box = ToolBox(
        db=ReadOnlyDatabase(sample_db_path, max_rows=2, timeout_seconds=5),
        layer=load_semantic_layer(),
        as_of=AS_OF,
        on_event=lambda kind, detail: events.append((kind, detail)),
    )
    box.events = events
    return box


def _tool(toolbox, name):
    return next(tool for tool in toolbox.tools() if tool.name == name)


def test_run_sql_returns_rows_and_records_them(toolbox):
    output = _tool(toolbox, "run_sql").invoke({"query": "SELECT encounterclass FROM encounters WHERE id = 'e2'"})
    assert "wellness" in output
    assert len(toolbox.queries) == 1
    assert toolbox.queries[0].ok and toolbox.queries[0].row_count == 1
    assert ("sql", "SELECT encounterclass FROM encounters WHERE id = 'e2'") in toolbox.events


def test_run_sql_reports_errors_for_the_model_to_correct(toolbox):
    output = _tool(toolbox, "run_sql").invoke({"query": "DROP TABLE patients"})
    assert output.startswith("ERROR:") and "read-only SELECT" in output
    assert toolbox.queries[0].error and not toolbox.queries[0].ok


def test_run_sql_reports_blocked_columns(toolbox):
    output = _tool(toolbox, "run_sql").invoke({"query": "SELECT ssn FROM patients"})
    assert "prohibited" in output and "Identity columns" in output


def test_run_sql_warns_when_rows_were_cut_off(toolbox):
    output = _tool(toolbox, "run_sql").invoke({"query": "SELECT id FROM encounters"})
    assert "Only the first 2 rows" in output
    assert toolbox.queries[0].truncated


def test_describe_table_merges_docs_and_handles_unknown_names(toolbox):
    output = _tool(toolbox, "describe_table").invoke({"tables": "encounters, nope"})
    assert "One row per visit" in output
    assert "Known tables" in output


def test_describe_table_survives_a_table_missing_from_the_database(toolbox):
    """The sample database has no conditions table, but the catalog documents one."""
    output = _tool(toolbox, "describe_table").invoke({"tables": "conditions"})
    assert "SNOMED" in output
    assert "not present in the database" in output


def test_lookup_definition_returns_codes(toolbox):
    output = _tool(toolbox, "lookup_definition").invoke({"name": "diabetes"})
    assert "44054006" in output and "714628002" in output
    assert "Known definitions" in _tool(toolbox, "lookup_definition").invoke({"name": "nope"})


def test_format_table_handles_nulls_and_long_values():
    text = format_table(("a", "b"), ((None, "x" * 80), (1, "y")), max_cell=10)
    assert "…" in text
    assert text.splitlines()[0].startswith("a")
