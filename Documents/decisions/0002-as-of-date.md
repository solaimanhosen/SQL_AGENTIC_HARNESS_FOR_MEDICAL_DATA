# ADR 0002: As-of date for relative time windows

- **Status:** Accepted on 2026-09-19.
- **Decision:** Relative windows such as "last 12 months" are measured back from the latest date in the data.

## Context

Questions such as "How many diabetic patients had an ER visit in the last 12 months?" need an anchor
date. Synthea generates data up to a fixed simulation date. If the anchor were today's real date and
the data ended earlier, recent windows would be empty or partial, and answers would change every day.

We checked every event table. None has an event after the last encounter start date.

| Table and column | Latest value |
|---|---|
| encounters.start | 2026-08-16 |
| observations.date, procedures.start, medications.start | 2026-08-16 |
| claims.servicedate, claims_transactions.fromdate | 2026-08-16 |
| conditions.start, careplans.start | 2026-08-14 |

## Decision

1. The as-of date is the calendar date of the latest encounter start. Today that is **2026-08-16**.
2. "Last N months" means events whose date is after the as-of date minus N months, up to and
   including the as-of date. For 12 months that is 2025-08-17 through 2026-08-16.
3. Every answer that uses a relative window states the as-of date and the window it used.
4. The setting `SQL_AGENT_AS_OF_DATE` controls the anchor:
   - `latest` is the default and uses the rule above.
   - `today` uses the real current date. We expect to switch to it once the agent runs on live data.
   - A fixed `YYYY-MM-DD` date keeps evaluation answers stable when the data is reloaded.

## Implementation notes

- Date columns mix full timestamps such as `2026-08-16T23:50:14Z` with plain dates such as
  `2026-08-14`. Queries must compare `date(column)`, not the raw text.
- The window in SQLite is `date(col) > date(:as_of, '-12 months') AND date(col) <= :as_of`.
- The resolver and the definitions file that uses it are built in Step 3, the semantic layer.
