import math
from datetime import date

import pytest

from sql_agent.analytics import AnalysisError, _round, compare_groups, summarize, trend

AS_OF = date(2026, 8, 16)


def _monthly(counts, *, year=2026, first_month=1, day=10):
    """One row per event, `counts[i]` events in the i-th month."""
    rows = []
    for offset, count in enumerate(counts):
        month = first_month + offset
        rows += [(f"{year + (month - 1) // 12}-{(month - 1) % 12 + 1:02d}-{day:02d}",)] * count
    return rows


def _line(result, start):
    return next(line for line in result.summary if line.startswith(start))


# summarize


def test_summarize_reads_numbers_stored_as_text_and_counts_what_it_leaves_out():
    rows = [("1",), ("2",), (3,), ("4.0",), ("5",), ("high",), (None,), ("",)]
    result = summarize(("value",), rows, value_column="value")
    assert result.columns == ("n", "excluded", "mean", "sd", "min", "p25", "median", "p75", "max")
    assert result.rows == ((5, 3, 3, 1.58, 1, 2, 3, 4, 5),)
    assert "3 values were empty or not numbers and were left out." in result.summary
    assert _line(result, "Median") == "Median 3, middle half 2 to 4, mean 3, range 1 to 5."


def test_summarize_by_group_flags_small_groups():
    rows = [("a", 10)] * 20 + [("b", 1), ("b", 3)]
    result = summarize(("grp", "v"), rows, value_column="v", group_column="grp")
    assert result.columns[0] == "grp"
    assert [row[:2] for row in result.rows] == [("a", 20), ("b", 2)]
    assert _line(result, "Median by grp") == "Median by grp: a 10; b 2."
    assert _line(result, "Fewer than 20") == "Fewer than 20 values in: b (2), so read those figures as small numbers."


def test_summarize_column_names_are_matched_without_case():
    result = summarize(("Value",), [(1,), (2,)], value_column="value")
    assert result.rows[0][0] == 2


@pytest.mark.parametrize(
    ("columns", "rows", "kwargs", "message"),
    [
        (("a",), [(1,)], {"value_column": "b"}, "There is no column 'b' to use as the values. The query returned: a."),
        (("a", "a"), [(1, 2)], {"value_column": "a"}, "More than one column is named 'a'"),
        (("a",), [], {"value_column": "a"}, "returned no rows"),
        (("a",), [("x",), (None,)], {"value_column": "a"}, "No value in 'a' is a number"),
    ],
)
def test_summarize_explains_what_to_change(columns, rows, kwargs, message):
    with pytest.raises(AnalysisError, match=message.replace("(", r"\(").replace(")", r"\)")):
        summarize(columns, rows, **kwargs)


def test_too_many_groups_are_refused():
    rows = [(str(index), 1) for index in range(51)]
    with pytest.raises(AnalysisError, match="51 groups, more than 50"):
        summarize(("g", "v"), rows, value_column="v", group_column="g")


# trend


def test_the_month_holding_the_as_of_date_is_not_read_as_a_decline():
    # Flat at 40 a month, then 16 days of August. Counting August as a full month would
    # turn this into a fall.
    rows = _monthly([40, 40, 40, 40, 40, 40, 40, 20])
    result = trend(("start",), rows, date_column="start", as_of=AS_OF)
    assert result.rows[-1] == ("2026-08", 20, "no")
    assert all(row[2] == "yes" for row in result.rows[:-1])
    assert "Incomplete, so shown but not used for the direction: 2026-08 (the data ends on 2026-08-16)." in result.summary
    assert "decreasing" not in " ".join(result.summary)
    assert "no change, every value is the same" in _line(result, "Direction")


def test_a_month_that_ends_on_the_as_of_date_is_complete():
    rows = _monthly([1, 2, 3, 4, 5, 6, 7, 8])
    result = trend(("start",), rows, date_column="start", as_of=date(2026, 8, 31))
    assert result.rows[-1][2] == "yes"


def test_start_marks_a_first_period_the_sql_entered_partway_through():
    rows = _monthly([10, 40, 40, 40, 40], first_month=3, day=20)
    result = trend(("d",), rows, date_column="d", as_of=AS_OF, start="2026-03-17")
    assert result.rows[0] == ("2026-03", 10, "no")
    assert result.rows[1][2] == "yes"
    assert "the rows start on 2026-03-17 and the data ends on 2026-08-16" in _line(result, "Incomplete")


def test_a_steady_rise_is_increasing():
    rows = _monthly([1, 2, 3, 4, 5, 6, 7])
    result = trend(("d",), rows, date_column="d", as_of=AS_OF)
    direction = _line(result, "Direction")
    # Seven values in order: one permutation in 5,040 is this extreme each way.
    assert direction.startswith("Direction over the 7 complete months: increasing")
    assert "Kendall's tau 1.00, p < 0.001" in direction
    assert _line(result, "Typical change") == "Typical change 1 per month (Sen's slope)."
    assert _line(result, "From") == "From 1 in 2026-01 to 7 in 2026-07."


def test_the_direction_test_matches_a_value_worked_out_by_hand():
    # y = 1, 3, 2, 5, 4: 8 concordant and 2 discordant pairs, so tau = 0.6. Of the 120
    # orderings of five values, 14 have two or fewer inversions, so p = 2 * 14 / 120.
    rows = _monthly([1, 3, 2, 5, 4])
    result = trend(("d",), rows, date_column="d", as_of=AS_OF)
    direction = _line(result, "Direction")
    assert "no clear trend" in direction
    assert f"Kendall's tau 0.60, p = {28 / 120:.3f}" in direction


def test_too_few_complete_periods_are_not_judged():
    rows = _monthly([5, 9, 30], first_month=6)
    result = trend(("d",), rows, date_column="d", as_of=AS_OF)
    assert _line(result, "Only 2 complete months") == "Only 2 complete months, fewer than 4, so no direction is judged."


def test_empty_months_count_as_zero_and_mixed_formats_are_read():
    rows = [("2026-01-05",), ("2026-01-20T08:00:00Z",), ("2026-03-02",), ("not a date",), (None,)]
    result = trend(("d",), rows, date_column="d", as_of=AS_OF)
    assert [row[:2] for row in result.rows] == [("2026-01", 2), ("2026-02", 0), ("2026-03", 1)]
    assert "2 rows had no readable date in d and were left out." in result.summary


def test_a_timestamp_is_read_in_utc_as_sqlite_date_reads_it():
    rows = [("2026-01-31T23:30:00-05:00",)]
    result = trend(("d",), rows, date_column="d", as_of=AS_OF)
    assert result.rows[0][0] == "2026-02"


def test_mean_by_quarter_leaves_empty_quarters_empty():
    rows = [("2025-01-10", "10"), ("2025-02-10", "20"), ("2025-08-01", "x"), ("2025-11-01", 7)]
    result = trend(("d", "v"), rows, date_column="d", value_column="v", measure="mean", period="quarter", as_of=AS_OF)
    assert result.columns == ("period", "mean", "n", "complete")
    assert result.rows == (
        ("2025-Q1", 15, 2, "yes"),
        ("2025-Q2", None, 0, "yes"),
        ("2025-Q3", None, 0, "yes"),
        ("2025-Q4", 7, 1, "yes"),
    )
    assert "1 values were empty or not numbers and were left out." in result.summary


def test_sum_by_year():
    rows = [("2024-03-01", 2.5), ("2024-09-01", 2.5), ("2026-01-01", 4)]
    result = trend(("d", "cost"), rows, date_column="d", value_column="cost", measure="sum", period="year", as_of=AS_OF)
    assert [row[:2] for row in result.rows] == [("2024", 5), ("2025", 0), ("2026", 4)]
    assert result.rows[-1][-1] == "no"
    assert result.summary[0] == "Sum of cost by year, 2024 to 2026, from 3 rows."


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"period": "week"}, "period must be one of month, quarter, year"),
        ({"measure": "median"}, "measure must be one of count, sum, mean"),
        ({"value_column": "d"}, "count counts rows"),
        ({"measure": "mean"}, "mean needs value_column"),
        ({"start": "last spring"}, "start must be a date"),
    ],
)
def test_trend_explains_bad_arguments(kwargs, message):
    with pytest.raises(AnalysisError, match=message):
        trend(("d",), [("2026-01-01",)], date_column="d", as_of=AS_OF, **kwargs)


def test_too_many_periods_are_refused():
    rows = [("1942-11-26",), ("2026-08-16",)]
    with pytest.raises(AnalysisError, match="span 1006 months, more than 400"):
        trend(("d",), rows, date_column="d", as_of=AS_OF)


def test_no_readable_dates_is_an_error():
    with pytest.raises(AnalysisError, match="No value in 'd' is a date"):
        trend(("d",), [("soon",)], date_column="d", as_of=AS_OF)


# compare_groups: rates


def _rate_rows(label, events, n):
    return [(label, 1)] * events + [(label, 0)] * (n - events)


def test_rates_match_fishers_tea_tasting_example():
    # Fisher's own 2 by 2 table, 3 of 4 against 1 of 4: the two-sided p-value is 34 / 70.
    rows = _rate_rows("milk first", 3, 4) + _rate_rows("tea first", 1, 4)
    result = compare_groups(("g", "hit"), rows, group_column="g", value_column="hit")
    assert result.columns == ("g", "n", "events", "rate_pct", "ci_low_pct", "ci_high_pct")
    assert [row[:4] for row in result.rows] == [("milk first", 4, 3, 75), ("tea first", 4, 1, 25)]
    assert _line(result, "milk first minus") == "milk first minus tea first: 50 percentage points, 3 times the rate."
    assert _line(result, "Fisher") == f"Fisher's exact test: p = {34 / 70:.3f}, so the difference could be chance."


def test_rate_intervals_are_wilson_intervals():
    rows = _rate_rows("a", 3, 8) + _rate_rows("b", 10, 100)
    result = compare_groups(("g", "v"), rows, group_column="g", value_column="v")
    p, n, z = 3 / 8, 8, 1.959963984540054
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert result.rows[0][4:] == (_round(100 * (centre - half)), _round(100 * (centre + half)))
    assert "a: 3 of 8, 37.5% (13.68% to 69.43%)." in result.summary
    assert _line(result, "Fewer than 20") == "Fewer than 20 values in: a (8), so read those figures as small numbers."


def test_a_clear_difference_in_rates_is_reported_as_unlikely_to_be_chance():
    rows = _rate_rows("a", 40, 50) + _rate_rows("b", 5, 50)
    result = compare_groups(("g", "v"), rows, group_column="g", value_column="v")
    assert _line(result, "Fisher") == "Fisher's exact test: p < 0.001, so a difference this large is unlikely to be chance alone."


def test_no_ratio_when_the_second_group_has_no_events():
    rows = _rate_rows("a", 2, 30) + _rate_rows("b", 0, 30)
    result = compare_groups(("g", "v"), rows, group_column="g", value_column="v")
    assert _line(result, "a minus b") == "a minus b: 6.67 percentage points."


def test_more_than_two_groups_are_described_but_not_tested():
    rows = _rate_rows("a", 1, 20) + _rate_rows("b", 2, 20) + _rate_rows("c", 3, 20)
    result = compare_groups(("g", "v"), rows, group_column="g", value_column="v")
    assert len(result.rows) == 3
    assert "Tests are run only between exactly two groups." in " ".join(result.summary)
    assert not any(line.startswith("Fisher") for line in result.summary)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([("a", 1), ("b", 2)], "rate needs 0 or 1 in every row of 'v', and group b holds other values"),
        ([("a", 1), ("b", None)], "COALESCE"),
        ([("a", 1), ("a", 0)], "holds only one group"),
    ],
)
def test_rates_explain_what_to_change(rows, message):
    with pytest.raises(AnalysisError, match=message):
        compare_groups(("g", "v"), rows, group_column="g", value_column="v")


def test_empty_group_labels_are_named():
    rows = _rate_rows(None, 1, 2) + _rate_rows("b", 1, 2)
    result = compare_groups(("g", "v"), rows, group_column="g", value_column="v")
    assert [row[0] for row in result.rows] == ["(empty)", "b"]


# compare_groups: means


def test_mean_difference_uses_an_exact_permutation_test_on_small_groups():
    # Two groups of five that do not overlap: 2 of the 252 ways to split ten values are
    # this extreme, so p = 2 / 252.
    rows = [("a", value) for value in (1, 2, 3, 4, 5)] + [("b", str(value)) for value in (6, 7, 8, 9, 10)]
    result = compare_groups(("g", "v"), rows, group_column="g", value_column="v", measure="mean")
    assert result.columns == ("g", "n", "excluded", "mean", "sd", "median")
    assert result.rows == (("a", 5, 0, 3, 1.58, 3), ("b", 5, 0, 8, 1.58, 8))
    assert _line(result, "a minus b") == "a minus b: -5."
    assert _line(result, "Permutation") == (
        f"Permutation test of the difference in means: p = {2 / 252:.3f}, "
        "so a difference this large is unlikely to be chance alone."
    )


def test_the_permutation_test_gives_the_same_answer_every_time():
    rows = [("a", (index * 7) % 13) for index in range(40)] + [("b", (index * 5) % 11) for index in range(40)]
    first = compare_groups(("g", "v"), rows, group_column="g", value_column="v", measure="mean")
    second = compare_groups(("g", "v"), rows, group_column="g", value_column="v", measure="mean")
    assert first.summary == second.summary


def test_a_group_with_one_value_is_not_tested():
    rows = [("a", 1), ("b", 2), ("b", 3), ("a", "n/a")]
    result = compare_groups(("g", "v"), rows, group_column="g", value_column="v", measure="mean")
    assert "A group has fewer than two values, so the difference is not tested." in result.summary
    assert "1 values were empty or not numbers and were left out." in result.summary
    assert result.rows[0] == ("a", 1, 1, 1, None, 1)


def test_compare_refuses_an_unknown_measure():
    with pytest.raises(AnalysisError, match="measure must be one of rate, mean"):
        compare_groups(("g", "v"), [("a", 1), ("b", 0)], group_column="g", value_column="v", measure="median")


@pytest.mark.parametrize(
    ("value", "rounded"),
    [(27.4321, 27.43), (0.012344, 0.01234), (0.5, 0.5), (3.0, 3), (1234.567, 1234.57), (None, None), (float("nan"), None)],
)
def test_figures_are_rounded_as_reported(value, rounded):
    assert _round(value) == rounded
