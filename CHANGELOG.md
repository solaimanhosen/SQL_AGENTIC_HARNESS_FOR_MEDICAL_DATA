# Changelog

Notable changes to this project, newest first. Versions follow the project milestones:
v1 is the backend, v2 adds the web interface.

## v2.1.0 — unreleased

Conversations are kept, and answers appear as they are written. The design and the reasons
behind it are in `Documents/chat-history-and-streaming.md`.

### Added

- Stored conversations. Every question and answer is saved to its own SQLite file,
  `Backend/data/conversations.db`, so conversations survive a restart. New endpoints list
  them, return one in full, rename it and delete it.
- A conversation sidebar in the interface: start a new chat, reopen an earlier one with
  every answer, table and step as it was, carry on asking, rename and delete. It becomes a
  drawer at phone width, and the open conversation is kept in the address so a reload
  returns to it.
- Streamed answers. The headline and findings appear as a draft while the model writes
  them, through a new `answer_delta` event on `/api/ask/stream`. The checked answer, with
  its citations, definitions and dates, replaces the draft.
- The sidebar can be resized by dragging its edge, between 200 and 480 pixels and never
  more than half the window, or collapsed to give the chat the whole width. The browser
  remembers both.
- If the browser loses the stream, the interface fetches the finished answer from the
  service instead of showing a failure.
- Settings `SQL_AGENT_CONVERSATIONS_PATH` and `SQL_AGENT_STORE_RESULT_ROWS`.

### Changed

- The agent runs with LangChain's streaming interface. Its answers, checks and safety
  layers are unchanged.
- A conversation's token budget is stored with it, so a restart no longer resets it.
- The model still sees only the last six turns of a conversation, however long it grows.
- "New conversation" moved from the header into the sidebar as "New chat".
- The documentation moved from `docs/` into `Documents/`, so there is one folder for it.
  The project brief is no longer kept in the repository.

## v2.0.0 — 9 October 2026

The web interface. Ask a question in a browser, watch the agent work, and read an answer
with everything behind it: the queries each finding cites, the definitions and their
status, the SQL, the rows, and anything that could not be traced.

### Added

- The web interface, in Angular 22 under `Frontend/`. Ask a question in the browser and
  read the answer: its headline, findings with their query citations, and caveats. Each
  step appears live while the agent works, and follow-up questions continue the
  conversation. The page asks for the access token when the service requires one and keeps
  it in memory only.
- Transparency panels on every answer, matching what the command line prints: the time
  window and as-of date, definitions with their confirmation status, assumptions, caveats,
  each traceability warning, the SQL that ran with failed attempts kept apart, the steps
  the agent took, and what the run cost. Clicking a finding's citation opens the SQL at
  that query. While the agent works, the step log shows each query as it runs.
- Result tables under each query, a button to copy its SQL, and downloads: the rows of a
  query as CSV and the whole answer as JSON. CSV cells that a spreadsheet would run as a
  formula are defused.
- A development proxy from the interface to the service, so the browser sees one origin.
- Unit tests for the interface, including one proving that text from the data is shown as
  text and never run as markup.

### Changed

- The root README now describes the project instead of the repository template.

## v1.1.0 — 28 September 2026

The backend becomes a service the web interface can call. It adds an HTTP API over the same
agent, follow-up questions, live steps, and the access and spending controls a shared
instance needs.

### Added

- An HTTP service over `SqlAgent.answer`, run with `python -m sql_agent.serve`. It has
  endpoints for asking a question, health, the schema catalog and the definitions. Answers
  carry definition statuses and window dates from our own records, and each query carries
  its rows.
- Each recorded query keeps the rows it returned, so the interface can show the evidence.
  The run log still leaves the rows out.
- `SQL_AGENT_CORS_ORIGINS` limits which browser origins may call the service.
- Follow-up questions. `SqlAgent.answer` takes the earlier turns of a conversation, and the
  service keeps them in memory by conversation id. Earlier answers are context, not
  evidence: query numbers restart with each question and cited figures must be re-queried.
- `/api/ask/stream` sends each step as a server-sent event while the agent works, then the
  answer.
- Three follow-up questions in the evaluation set, asked after an earlier question in the
  same conversation.
- Service hardening:
  - a shared bearer token, `SQL_AGENT_API_TOKEN`, required on every endpoint except health.
    Without one, the service refuses to listen beyond this machine;
  - limits on questions running at once, on tokens per UTC day and on tokens per
    conversation, applied before the model is called. `/api/usage` reports them;
  - a 16 KB cap on request bodies;
  - one line per request in `logs/requests.jsonl`, refusals included.

### Changed

- The command line and the service share one wording for failures.
- The run log records the conversation id and the earlier questions of a follow-up.
- The live prompt injection test checks that the agent does not obey an instruction hidden
  in the data, rather than that it never mentions the instruction.

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
  deployment decision before any real patient data. See `Documents/security.md`.
- There is no authentication and no spending limit. Both belong with the web interface.
