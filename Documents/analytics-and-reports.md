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
| Statistics | What SQLite can compute: counts, sums, averages | Also medians, quartiles, spread, trends and group comparisons with significance tests |
| "Is it increasing?" | The model's reading of the numbers | A Mann-Kendall test over complete periods |
| Rows the agent can work from outside SQL | 200, the result cap | Up to 100,000, of which only the computed table reaches the model |
| Charts | None | Bar and line charts, drawn from recorded results |
| Reports | JSON and CSV downloads | A self-contained HTML report per answer |
| New dependencies | None | SciPy |

## Three traps in the data

- **The last month is partial.** The data ends on 2026-08-16, so August 2026 holds 22
  encounters against 36 to 63 in each of the eleven months before it. A monthly trend that
  counts August as a full month reports a decline that is not there. The trend tool marks
  the period holding the as-of date as incomplete and leaves it out of the verdict.
- **Statistics need more rows than the cap.** `run_sql` returns at most 200 rows, and
  `observations` alone has 68,648. A median lab value cannot be computed from capped rows,
  and SQLite has no median function. The analytics tools therefore run their own SQL with a
  larger cap and send the model only the computed table.
- **BMI is recorded twice.** `Body mass index (BMI) [Ratio]` is BMI; `[Percentile] Per age
  and sex` is a child's percentile, on a 0 to 100 scale. A median over both is wrong. The
  evaluation's BMI question is limited to the ratio.

## Design

### Analytics tools

Three tools sit beside `run_sql`, `describe_table` and `lookup_definition`:

| Tool | The model gives | Our code returns |
|---|---|---|
| `summarize` | SQL with one row per value, the value column, optionally a group column | Count, excluded values, mean, standard deviation, minimum, quartiles, median and maximum, overall or per group |
| `trend` | SQL with one row per event and its date, a period (month, quarter or year), count, sum or mean, and the window's first date | A value per period, each marked complete or not, and the direction by a Mann-Kendall test with Sen's slope |
| `compare_groups` | SQL with one row per member, its group, and 1 or 0 (rate) or a value (mean) | Each group's rate with a 95% Wilson interval, or its mean, sd and median; for two groups the difference, the ratio and an exact p-value |

How a call runs:

1. The SQL goes through the same `run_query` as every other statement, so validation, the
   authorizer, the read-only connection, the time limit and the engine limits all apply.
   Only the row cap differs: up to 100,000 rows instead of 200.
2. A result over the cap is refused, not computed on in part.
3. `analytics.py` computes the table and writes the sentences that describe it. It has no
   database or model code, so every result is unit tested on fixed data, several against
   values worked out by hand.
4. The table is recorded as a numbered query, in the same sequence as `run_sql`. The model
   sees only the table and the sentences, never the source rows, and cites the number like
   any other query.

The verdicts are computed, not judged. A trend's direction is "increasing" or "decreasing"
only when the Mann-Kendall test gives p < 0.05, and "no clear trend" otherwise. A
comparison says whether "a difference this large is unlikely to be chance alone" from
Fisher's exact test or a permutation test with a fixed seed, so the same rows always give
the same p-value. Groups with fewer than 20 members are named as small. The prompt tells
the model to state these as given.

The partial-period rule is the one that matters in this data. A period is complete only if
it lies wholly within the data: it ends on or before the as-of date, and it starts on or
after the first date the SQL kept, which the model passes as `start` for a "last 12 months"
window. Incomplete periods stay in the table, marked "no", and are left out of the verdict.

### Charts

The model may ask for up to three bar or line charts. A request names a query, the column
for the categories, the columns to plot (or one column split by a series column) and a
title. It carries no numbers. `charts.py` reads the values from that query's recorded rows
and refuses a chart it cannot resolve:

- a query that did not run, or kept only part of its rows,
- a missing or non-numeric column,
- two rows for the same point,
- more than 60 bars, 400 line points or 8 series.

A refused chart is not drawn, and its reason becomes a traceability warning, so it also
fails the evaluation's traceability check.

The interface draws a chart as SVG with Angular template bindings, so every label is text.

- Bars start at zero and have a rounded end at the value. A line breaks at a missing value
  rather than bridging it.
- Ticks step by 1, 2 or 5.
- The eight series colours come in a fixed order, checked for colour-blind separation
  against the page's light and dark surfaces.
- Several series get a legend, and a line's last value is written at its end.
- Hovering, or focusing the chart and using the arrow keys, shows every series at one point.
- Each chart has a "Query N" button that opens the table it was drawn from.

### Reports

A report is one answer as a single HTML file. It is made from the same answer the service
sends and the conversation stores, so a report from the command line, from a live answer
or from a conversation reopened later reads the same. In order, it holds:

- the question, the data's as-of date, the model, and the earlier questions of a follow-up,
- the headline and findings, each citation a link to its query further down,
- the charts as inline SVG, with a tooltip on each mark,
- the time window, the definitions with their status, assumptions, caveats and warnings,
- every query's SQL, an analysis's summary, and the rows,
- the failed attempts, and what the run cost.

It needs nothing else to open:

- the styles are inline,
- there is no script and no external reference,
- a Content-Security-Policy, in the file and on the download, forbids loading anything,
- every value is escaped, so a stored row holding `<script>` stays text,
- print styles keep it light, with tables and charts unbroken across pages.

Reports come from `GET /api/conversations/{id}/turns/{turn}/report`, from the "Download
report (HTML)" button under each answer, and from `main.py --report FILE`.

## Decisions

| Decision | Why | Turned down |
|---|---|---|
| A fixed set of analytics tools | Settled on 28 September 2026; keeps the safety posture | Letting the model run Python |
| Tools take their own SQL | Full data, not capped rows; one step instead of two | Tools over an earlier query's capped rows |
| Tests from SciPy that suit small samples | Fisher's exact test, and a permutation test that is exact for small groups and samples 9,999 rearrangements for large ones; tested library code | Hand-written statistics; descriptive figures only |
| The direction of a trend is computed | "Increasing" must be checkable, not a judgement | Letting the model read the series |
| Chart data comes from the recorded result | The plotted numbers must be the ones that ran | The model writing chart values |
| Our own SVG in the interface and the report | Themed, accessible, no script, no network | matplotlib for the report only; a JavaScript chart library |
| One report per answer | Decided on 20 October 2026 | A report per conversation |

## Risks to state plainly

- A downloaded report holds the SQL and the rows behind the answer. Once saved it is an
  ordinary file. That is fine for synthetic data; with real data it is a query extract.
  `SQL_AGENT_STORE_RESULT_ROWS=false` keeps rows out of stored answers and their reports.
- Small groups are flagged, not suppressed. A minimum group size is still to be decided
  with Telligen.
- The tests suit small samples, but they do not make small samples tell more. With 8
  diabetic patients, one frequent attender can create a "significant" trend. The agent has
  said so in its caveats on every run seen, but that is the model's judgement, not a check.
- A chart is drawn only when the model asks for one. The prompt now asks for one with every
  trend and comparison. The evaluation checks it on two questions, not every answer.
- Each question now sends about 1,550 more input tokens per model call: the longer
  instructions and three more tool descriptions. Over the 20 questions that v2.1 also
  answered, input tokens rose 29% in one full run and 43% in another. Prompt caching is not
  switched on yet and would recover this and more.

## Status

Work is on the branch `sql_agent/analytics/dev`, cut from `main` at `dc67346`.

| Step | What | Status | Commit |
|---|---|---|---|
| 1 | Branch, this document, decision record 0004, SciPy | Done | `a9d9d10` |
| 2 | Backend: the analytics functions | Done | `bdf7343` |
| 3 | Backend: analytics tools, the analysis cap, records and steps | Done | `75d7b79` |
| 4 | Backend: chart requests, checked against the run | Done | `20491db` |
| 5 | Interface: charts and analysis records | Done | `22b77c1` |
| 6 | Evaluation cases, security catalogue, evaluation re-run | Done | `1b6d7e2` |
| 7 | Backend: HTML report, endpoint and `--report` | Done | `51a3862` |
| 8 | Interface: report download | Done | `16e30d6` |
| 9 | Documentation, results and browser checks | Done | the commit after `16e30d6` |

Not yet merged into `main`. The prompt change that asks for a chart with every trend and
comparison is its own commit, `4537dd3`, between steps 6 and 7.

## Results

Measured on 20 October 2026 with Claude Opus 5. The baseline is `main` at `dc67346`.

| Check | v2.1.0 | Phase C |
|---|---|---|
| Backend tests, no network | 272 passed, 3 skipped | 375 passed, 3 skipped |
| Interface tests, no network | 78 passed | 108 passed |
| Security catalogue | 35 of 35 | 78 of 78: the 35 on both query paths, and 8 through the analytics tools |
| Evaluation | 20 of 20 | 23 of 23, all 3 analytics questions included |
| Evaluation cost, whole set | 417,750 in, 23,739 out, 5.4 minutes | 610,548 in, 29,658 out, 6.3 minutes |
| Evaluation cost, the 20 questions both answered | 417,750 in, 23,739 out | 538,842 in, 25,991 out |
| New dependencies | | SciPy |

The full evaluation ran twice on 20 October, before and after the chart prompt was made
firmer. Both scored 23 of 23. The figures above are from the second, which matches the code
as committed.

What the analytics found in this data, each computed by the tools:

| Question | Result |
|---|---|
| Emergency visits by month, last 12 months | 71 visits. Over the 11 complete months, increasing (Kendall's tau 0.54, p = 0.028), about 0.25 more a month. Both partial Augusts left out |
| Diabetic and non-diabetic patients with an emergency visit, last 12 months | 3 of 8 (37.5%) against 12 of 100 (12%). Fisher's exact test p = 0.080: the difference could be chance. The diabetic group is flagged as small |
| Median BMI of the prediabetes cohort | 28.2 over 530 measurements, middle half 27.7 to 30.2 |

Checked by hand in headless Chrome, against a real service and a real answer:

- The chart in light and dark themes and at 390 px, with no sideways scroll. The readout
  works from the pointer and the keyboard at both edges, and the source button opens the
  query it was drawn from.
- "Download report (HTML)" saved `9707ebcf-turn1-report.html`. Opened with every network
  request blocked, it made no requests, ran no script, logged no error, and showed its
  chart and all seven tables. A report written by `main.py --report` with three charts
  behaved the same.
- The print view stays light with the screen in dark mode, and tables and charts are not
  split across pages.

## Demo notes

A suggested order for showing this live, about four minutes. Ask the questions before the
demo too, so a stored conversation is there if the network is slow.

1. **Ask the brief's own example:** "Compare emergency department visits for diabetic and
   non-diabetic patients over the last year, by month." While it works, point at the step
   "Computed a comparison of rate of ... over 108 rows". The model chose the analysis; our
   code did the arithmetic.
2. **Read the answer with the chart.**
   - Hover the chart, or focus it and use the arrow keys, to show both series at one month.
   - Click the chart's "Query N" button. It opens the exact table the lines were drawn from.
   - Point at the Fisher p-value in the findings, and at "Fewer than 20 values in:
     diabetic". The verdict and the warning were computed, not written by the model.
3. **Ask "Show hospital visits by month and explain whether they are increasing or
   decreasing."** Open the trend's query and point at August 2026 marked "no" in the
   complete column. The data ends on 16 August; counting that month whole would invent a
   fall. The verdict uses the complete months only.
4. **Download the report** from under the answer. Turn Wi-Fi off and open the file: charts,
   tables, SQL and definitions all there. Show print preview: it stays light and whole.
5. **Optionally**, from the terminal: `main.py --report visits.html "..."` writes the same
   report without the interface.

Lines worth having ready:

- "The model never writes a statistic or a plotted number. It picks the tool and writes
  the SQL; the numbers come from our code and from the rows that ran."
- "Increasing means a Mann-Kendall test said so, over complete months only."
- "The report is one file with no script and no network access, and a security policy that
  forbids loading anything."
- "Same three safety layers. The analytics tools go through the same query path, and the
  attack catalogue now runs every attack through it too: 78 of 78."

Limits to state if asked:

- Cohorts are small. The tests are suited to small samples, but 8 diabetic patients are
  still 8, and one frequent attender can drive a trend.
- Small groups are flagged, not hidden. The minimum group size is Telligen's call.
- A downloaded report contains the rows behind the answer.
- Each question costs more input tokens than in v2.1, 29% to 43% more on the same
  questions, because the instructions and tools are longer. Prompt caching would recover it.

Screenshots for slides can be taken from the running interface: a chart with the readout
showing, the trend table with its incomplete month, and the report open offline.
