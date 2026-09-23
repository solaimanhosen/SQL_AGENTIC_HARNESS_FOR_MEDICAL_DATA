# Changelog

Notable changes to this project, newest first. Versions follow the project milestones:
v1 is the backend, v2 will add the web interface.

## v1.0.0 — 23 September 2026

The backend is complete. A question asked in plain language becomes an explained answer,
with the SQL and the evidence behind it, over a synthetic Synthea database of 108 patients.

### Added

**Asking questions**

- `main.py` answers a question from the command line, showing the answer, the SQL that ran
  and what the run cost. `--verbose` streams each step, `--json` prints the whole run.
- An agent loop built on LangChain with Claude Opus 5, using three tools: run a query,
  describe a table, and look up a shared definition.
- `SqlAgent.answer` is the reusable core. The command line is a thin wrapper around it, and
  the web service in v2 will call the same method.

**Meaning of the data**

- A schema catalog covering all 18 tables and 166 columns: what each column holds, how the
  tables join, which values a column can take, and the traps that produce wrong answers.
- Fifteen shared definitions with the SQL behind them, covering diabetes, prediabetes,
  heart disease, hypertension, emergency and hospital visits, age bands and A1c thresholds.
- Every definition carries checks that run against the real data, so a definition that
  stops matching the data fails the test suite instead of quietly changing answers.

**Safety**

- Three independent layers between model-written SQL and the data: a validator that accepts
  a single SELECT and nothing else, a SQLite authorizer that permits only reads and refuses
  patient identifier columns, and a read-only connection with a row cap and a time limit.
- Engine limits on value size, statement length and nesting depth.
- An attack catalogue of 35 cases, run both as a report and as tests.

**Trust**

- Structured answers where each finding cites the numbered queries behind it.
- Definitions are printed from the semantic layer with their confirmation status, and the
  dates of a time window are computed rather than written by the model.
- The run is checked against the answer, and anything unsupported is reported as a
  traceability warning.
- Every run is appended to a log with the question, the answer, the SQL and the cost.

**Measurement**

- An evaluation set of 17 questions with answers worked out by hand, covering cohorts,
  multi-table joins, time windows, a trend, grade tables, cost, an ambiguous question and
  two adversarial ones. All 17 pass.
- Each question carries the SQL that produces the right answer, checked before the agent is
  asked anything, so a change in the data cannot go unnoticed.

**Data**

- A loader that rebuilds the database from the committed CSV files, stores clinical codes as
  integers, creates the indexes the agent's joins need, verifies every table's row count
  against its source file, and swaps the database into place only when those checks pass.

### Documentation

- Decision records for the choice of agent framework and for the as-of date rule.
- Guides for the semantic layer, the evaluation harness and the security review.

### Known limitations

- The data is synthetic, so answers can be clinically odd while being correct about the
  database. Consistency with the data is the bar for this version.
- Every definition is marked assumed until Telligen confirms it. Three need a decision:
  whether urgent care counts as an emergency visit, what a hospital visit means, and which
  basis defines a diabetic cohort.
- The evaluation set passes completely, which says more about the set than the agent.
  Harder questions are the next addition.
- Query results are sent to the Anthropic API. That is fine for synthetic data and needs a
  deployment decision before any real patient data. See `docs/security.md`.
- There is no authentication and no spending limit. Both belong with the web interface.
