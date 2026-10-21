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
    assert toolbox.queries[0].columns == ("encounterclass",)
    assert toolbox.queries[0].rows == (("wellness",),)
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
    assert len(toolbox.queries[0].rows) == 2


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


# The analytics tools


@pytest.fixture
def analysis_toolbox(sample_db_path):
    """Results capped at 2 rows for run_sql, but 10 for an analysis."""
    events = []
    box = ToolBox(
        db=ReadOnlyDatabase(sample_db_path, max_rows=2, timeout_seconds=5, analysis_max_rows=10),
        layer=load_semantic_layer(),
        as_of=AS_OF,
        on_event=lambda kind, detail: events.append((kind, detail)),
    )
    box.events = events
    return box


def test_the_toolbox_offers_the_analytics_tools(toolbox):
    names = [tool.name for tool in toolbox.tools()]
    assert names[-3:] == ["summarize", "trend", "compare_groups"]


def test_an_analysis_reads_past_the_result_cap_and_records_the_computed_table(analysis_toolbox):
    sql = "SELECT start FROM encounters"
    output = _tool(analysis_toolbox, "trend").invoke({"sql": sql, "date_column": "start"})
    [record] = analysis_toolbox.queries
    assert record.ok and record.number == 1
    assert record.analysis.tool == "trend"
    assert record.analysis.source_rows == 3
    assert record.analysis.parameters["period"] == "month"
    assert record.columns == ("period", "count", "complete")
    assert record.rows == (("2026-01", 1, "yes"), ("2026-02", 1, "yes"), ("2026-03", 1, "yes"))
    assert record.row_count == 3 and not record.truncated
    assert output.startswith("Query 1 | trend by month over 3 rows")
    assert "- Only 3 complete months, fewer than 4, so no direction is judged." in output
    assert analysis_toolbox.events == [("sql", sql), ("analysis", "trend by month over 3 rows")]


def test_analyses_and_queries_share_one_numbering(analysis_toolbox):
    _tool(analysis_toolbox, "run_sql").invoke({"query": "SELECT COUNT(*) FROM patients"})
    _tool(analysis_toolbox, "run_sql").invoke({"query": "DROP TABLE patients"})
    output = _tool(analysis_toolbox, "compare_groups").invoke(
        {
            "sql": "SELECT p.gender, CASE WHEN e.encounterclass = 'emergency' THEN 1 ELSE 0 END AS er "
            "FROM encounters e JOIN patients p ON p.id = e.patient",
            "group_column": "gender",
            "value_column": "er",
        }
    )
    assert [record.number for record in analysis_toolbox.queries] == [1, None, 2]
    assert output.startswith("Query 2 | comparison of rate of er by gender over 3 rows")
    assert analysis_toolbox.queries[2].rows[0][:3] == ("F", 2, 2)


def test_an_analysis_goes_through_the_same_guardrails(analysis_toolbox):
    write = _tool(analysis_toolbox, "summarize").invoke({"sql": "DELETE FROM patients", "value_column": "id"})
    blocked = _tool(analysis_toolbox, "summarize").invoke({"sql": "SELECT ssn FROM patients", "value_column": "ssn"})
    assert write.startswith("ERROR: UnsafeQueryError")
    assert blocked.startswith("ERROR: BlockedColumnError")
    assert not any(record.ok for record in analysis_toolbox.queries)


def test_an_analysis_refuses_to_compute_on_part_of_the_data(sample_db_path):
    box = ToolBox(
        db=ReadOnlyDatabase(sample_db_path, max_rows=2, timeout_seconds=5, analysis_max_rows=2),
        layer=load_semantic_layer(),
        as_of=AS_OF,
    )
    output = _tool(box, "trend").invoke({"sql": "SELECT start FROM encounters", "date_column": "start"})
    assert output == (
        "ERROR: AnalysisError: the query returned more than 2 rows, so trend would only see part of the data. "
        "Filter in SQL, or return fewer rows per item."
    )
    assert not box.queries[0].ok


def test_an_analysis_explains_bad_arguments(analysis_toolbox):
    output = _tool(analysis_toolbox, "summarize").invoke({"sql": "SELECT city FROM patients", "value_column": "age"})
    assert output == "ERROR: AnalysisError: There is no column 'age' to use as the values. The query returned: city."
    assert analysis_toolbox.events[-1] == ("sql_error", output.removeprefix("ERROR: "))


def test_summarize_and_trend_describe_their_settings(analysis_toolbox):
    _tool(analysis_toolbox, "summarize").invoke(
        {"sql": "SELECT gender, 1 AS one FROM patients", "value_column": "one", "group_column": "gender"}
    )
    _tool(analysis_toolbox, "trend").invoke(
        {"sql": "SELECT start, 2 AS cost FROM encounters", "date_column": "start", "measure": "sum", "value_column": "cost", "period": "quarter"}
    )
    assert [kind_detail for kind_detail in analysis_toolbox.events if kind_detail[0] == "analysis"] == [
        ("analysis", "summary of one by gender over 2 rows"),
        ("analysis", "trend of sum cost by quarter over 3 rows"),
    ]
