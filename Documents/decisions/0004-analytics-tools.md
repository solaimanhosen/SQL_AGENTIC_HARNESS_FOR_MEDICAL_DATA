# ADR 0004: Analytics tools and charts

- **Status:** Accepted on 2026-10-20.
- **Decision:** Statistics come from three fixed tools that run their own read-only SQL and
  compute with pandas and SciPy. Charts are described by the model and drawn from the
  recorded result of the query they cite.

## Context

The brief asks that the agent "use Python to calculate statistics and automatically create
useful tables and charts". On 2026-09-28 it was settled that the model never executes
arbitrary Python: that would undo the read-only posture the security review tested.

Three things constrain the design:

- `run_sql` returns at most 200 rows, so the model's context stays small. Statistics over a
  cohort's lab values need many more rows than that, and SQLite has no median.
- Every figure in an answer must trace to a query that ran. A statistic or a plotted value
  that the model wrote itself would break that.
- Cohorts are small, about 100 patients in all, so differences and trends need tests that
  hold for small samples.

## Decision

1. Three tools: `summarize`, `trend` and `compare_groups`. Each takes a SQL statement and
   the names of the columns to use.
2. The SQL runs through `ReadOnlyDatabase.run_query` like any other query, so validation,
   the authorizer, the read-only connection, the timeout and the engine limits all apply.
   Only the row cap differs: up to `SQL_AGENT_ANALYSIS_MAX_ROWS` rows, default 100,000. A
   result over that cap is refused, not computed on in part.
3. Only the computed table goes back to the model. It is recorded as a numbered query, in
   the same sequence as `run_sql`, so a finding cites it as it cites any query.
4. Tests come from SciPy: Fisher's exact test for two rates, a permutation test with a fixed
   seed for two means, Kendall's tau against time for the direction of a trend (the
   Mann-Kendall test), and Wilson intervals for rates.
5. The period holding the as-of date is incomplete, and is shown but left out of a trend's
   verdict.
6. An answer may ask for up to three charts. Each names a query and its columns; the service
   reads the values from that query's recorded rows and refuses a chart it cannot resolve,
   listing the refusal as a traceability warning.
7. Charts are drawn by our own code: an Angular component in the interface and a Python
   function for reports, with the same palette and tick rule.

## Alternatives turned down

| Alternative | Why not |
|---|---|
| Letting the model run Python | Undoes the read-only guarantees, and was ruled out on 2026-09-28 |
| Tools over an earlier query's rows | Those rows are capped at 200, so the statistics would be wrong on any large cohort |
| Raising the `run_sql` cap | The rows would go into the model's context, at a cost per question and a risk of truncation |
| Hand-written tests | More to verify than tested library code, for no gain |
| Descriptive figures only | The model would decide by eye whether a series is rising |
| The model writing chart values | The plotted numbers could differ from the ones that ran |
| matplotlib for report charts | No dark mode, text drawn as paths, and a second look beside the interface |
| A JavaScript chart library | It would be inlined as a script in every report, losing the no-script guarantee |

## Consequences

- SciPy is a new dependency.
- An analysis query can read many more rows than `run_sql`. The timeout and the engine
  limits still bound its cost, and the source rows are not stored or logged: the SQL is
  kept so the result can be reproduced.
- A citation can point at a computed table rather than raw rows. The interface and the
  report label it as an analysis, with the tool and its settings.
