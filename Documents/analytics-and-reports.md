# Analytics, charts and reports (Phase C)

This document records what Phase C adds, why it is built the way it is, and how far it has
got. It is kept up to date as each step lands, and it is the source for the Demo 2 slides on
this work. Step 14 is the analytics tools and the chart description; Step 15 is the
self-contained HTML reports.

## What changes, in short

- **The agent can compute statistics.** Three fixed tools summarise a value, follow a trend
  over time and compare groups. The model chooses the tool and writes its SQL; our code does
  the arithmetic and the statistical tests.
- **Answers can carry charts.** The model says which query to plot and how. The plotted
  numbers are read from that query's recorded result, never written by the model.
- **Every answer can be downloaded as a report.** One HTML file with the narrative, the
  charts, the tables and the SQL, which opens in a browser with no network.
- **Nothing about trust changes.** The safety layers are untouched, and every exact thing
  still comes from our own records.

## Before and after

| | v2.1.0 | Phase C |
|---|---|---|
| Statistics | Whatever SQLite can compute in one query | Summary statistics, trends and group comparisons with exact tests |
| "Is it increasing?" | The model's reading of the numbers | A Mann-Kendall test over complete periods |
| Rows a calculation can use | 200, the result cap | Up to 100,000, of which only the computed table reaches the model |
| Charts | None | Bar and line charts, drawn from recorded results |
| Reports | JSON and CSV downloads | A self-contained HTML report per answer |
| New dependencies | None | SciPy |

## Two traps in the data

- **The last month is partial.** The data ends on 2026-08-16, so August 2026 holds 22
  encounters against 36 to 63 in each of the eleven months before it. A monthly trend that
  counts August as a full month reports a decline that is not there. The trend tool marks
  the period holding the as-of date as incomplete and leaves it out of the verdict.
- **Statistics need more rows than the cap.** `run_sql` returns at most 200 rows, and
  `observations` alone has 68,648. A median lab value cannot be computed from capped rows,
  and SQLite has no median function. The analytics tools therefore run their own SQL with a
  larger cap and send the model only the computed table.

## Design

Filled in as each step lands.

### Analytics tools

### Charts

### Reports

## Decisions

| Decision | Why | Turned down |
|---|---|---|
| A fixed set of analytics tools | Settled on 28 September 2026; keeps the safety posture | Letting the model run Python |
| Tools take their own SQL | Full data, not capped rows; one step instead of two | Tools over an earlier query's capped rows |
| Exact tests from SciPy | Suited to cohorts of about 100 patients, and tested library code | Hand-written statistics; descriptive figures only |
| The direction of a trend is computed | "Increasing" must be checkable, not a judgement | Letting the model read the series |
| Chart data comes from the recorded result | The plotted numbers must be the ones that ran | The model writing chart values |
| Our own SVG in the interface and the report | Themed, accessible, no script, no network | matplotlib for the report only; a JavaScript chart library |
| One report per answer | Decided on 20 October 2026 | A report per conversation |

## Risks to state plainly

Filled in as each step lands.

## Status

Work is on the branch `sql_agent/analytics/dev`, cut from `main` at `dc67346`.

| Step | What | Status | Commit |
|---|---|---|---|
| 1 | Branch, this document, decision record 0004, SciPy | Done | `a9d9d10` |
| 2 | Backend: the analytics functions | Done | `bdf7343` |
| 3 | Backend: analytics tools, the analysis cap, records and steps | Done | `75d7b79` |
| 4 | Backend: chart requests, checked against the run | Done | `20491db` |
| 5 | Interface: charts and analysis records | Done | the commit after `20491db` |
| 6 | Evaluation cases, security catalogue, evaluation re-run | | |
| 7 | Backend: HTML report, endpoint and `--report` | | |
| 8 | Interface: report download | | |
| 9 | Documentation, results and browser checks | | |

## Results

Baseline on `main` at `dc67346`, 20 October 2026:

| Check | v2.1.0 | Phase C |
|---|---|---|
| Backend tests, no network | 272 passed, 3 skipped | |
| Interface tests, no network | 78 passed | |
| Security catalogue | 35 of 35 | |
| Evaluation | 20 of 20 | |

## Demo notes

Filled in at the end.
