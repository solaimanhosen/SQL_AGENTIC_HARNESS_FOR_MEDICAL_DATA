# Security review

This document records what the agent is protected against, how each protection is proven,
and what remains a risk. It covers the backend, its HTTP service, the analytics tools and
the HTML reports as they stand, running against a synthetic database.

```bash
cd Backend
.venv/bin/python -m sql_agent.check_security          # run the attack catalogue
.venv/bin/python -m pytest tests/test_security.py -q  # the same attacks, as tests
RUN_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_agent_live.py -q   # prompt injection
.venv/bin/python -m pytest tests/test_service.py tests/test_limits.py tests/test_serve.py -q   # the service
```

## What we are protecting

The database is the asset. Nothing in it may be changed, and the direct identifiers in the
patients table must never reach a user or a model. The data is synthetic, so the real
purpose is to prove the pattern works before the system is pointed at anything sensitive.

## What we treat as untrusted

Four inputs are assumed hostile, whatever they look like:

1. **The user's question.** Anyone who can run the agent can write anything in it.
2. **The SQL the model writes.** A language model is not a safety boundary. It may be
   wrong, or talked into being wrong.
3. **The text stored in the database.** A row can hold an instruction aimed at the model.
   In a real deployment this is the likeliest attack, because the attacker may be able to
   write a record long before anyone asks a question.
4. **Anything returned by a tool.** It is data to be reported, never a command to follow.

## Controls and the evidence for each

| Threat | Control | Evidence |
|---|---|---|
| Any write, schema change or file attach | Three independent layers: the file is opened read-only, a SQLite authorizer permits only reads, and a validator accepts a single SELECT and nothing else | Attacks 1 to 16 in the catalogue, plus tests that defeat each layer separately and confirm the others still hold |
| Reading names, addresses or identifiers | The authorizer refuses those columns inside the engine, so aliases, subqueries, unions, sorts and filters cannot reach them either | Eight identity attacks, including through a common table expression and a self join |
| Learning the schema through the back door | Internal schema tables are not readable, and pragma statements are refused. Schema questions go through the documented catalog instead | Two attacks, covering the internal table and the pragma function |
| Exhausting memory | The engine caps the size of any single value, so a request for a 200 MB value fails instead of allocating | One attack, previously the only one that succeeded |
| Running forever | A time limit stops a query, whether it is a recursive loop or a cartesian join | Two attacks, both stopped |
| Exhausting the parser | Statements are capped in length and nesting depth before parsing | Two attacks |
| Flooding the model's context | Results are capped in rows and characters, and the agent is told when rows were cut | Covered by the query layer tests |
| An instruction hidden in the data | The agent is told that stored text is data and must be reported rather than obeyed | A live test against a database whose condition description tells the model to reply with a single word |
| An answer that claims more than it checked | Findings must cite the queries behind them, and the run is compared with the answer afterwards | The traceability checks, scored on every evaluation question |
| An earlier answer reused as evidence | A follow-up sees earlier answers with their citations stripped, query numbers restart per question, and stated figures must be re-queried | Offline tests of what a follow-up is sent, and three follow-up questions in the evaluation, all traceable |
| Anyone who can reach the service using it | With `SQL_AGENT_API_TOKEN` set, every endpoint except health requires it as a bearer token, compared in constant time. Without a token the service refuses to listen beyond this machine | Tests for a missing, wrong and unprefixed token on every protected endpoint, and for the refusal to bind without one |
| Cost as a denial of service | Before a question reaches the model: a limit on questions running at once, a token budget per UTC day, and a token budget per conversation. Runs still in progress hold a reservation, so a burst cannot overspend, and a run whose reader left still counts | Unit tests of the ledger, and service tests showing each limit refuses with a 429 before the model is called |
| Oversized requests | Bodies over 16 KB are refused whether or not they declare their length, and a question is capped at 2,000 characters | Tests for a declared and an undeclared oversized body |
| Statistics that read past the row cap | The analytics tools take their own SQL and may read up to `SQL_AGENT_ANALYSIS_MAX_ROWS` rows (100,000 by default), but through the same `run_query`: the same validator, authorizer, read-only connection, time limit and engine limits. Only the computed table reaches the model. A result over the cap is refused, never computed on in part | Every catalogue attack run a second time with the analysis cap, and eight more through the tools themselves, including identity columns named as the value or the group |
| A statistic or a chart the model made up | Statistics are computed by our code with SciPy. A chart names a query and its columns, and the plotted values are read from that query's recorded rows; one that cannot be resolved is not drawn and becomes a traceability warning | Unit tests of each analysis against values worked out by hand, of chart resolution and of every refusal; two chart checks in the evaluation |
| Hostile text in a report or a chart | Every value in a report is escaped, including inside SVG. A report has no script and no external reference, and a Content-Security-Policy, in the file and on the response, forbids loading anything. The interface draws charts with template bindings, so labels are text | Tests that a row holding `<script>`, `</style>` or `<svg onload>` stays text, that a report holds no script and no external reference, and that a chart's labels stay text |
| Untraceable use of the service | One line per request in `logs/requests.jsonl`: path, status, time, client address, whether it was authenticated and why it was refused. No bodies and no token | A test that a refusal is logged and the token never appears |

## Results

The catalogue holds 35 statements: 32 attacks that must be blocked and 3 ordinary queries
that must keep working, so that over-blocking shows up as a failure too. Since Phase C each
runs twice, as `run_sql` runs it and with the analysis row cap, and 8 more cases go through
the analytics tools: 6 attacks and 2 ordinary analyses. All 78 behave as expected, and the
row counts of every table are identical before and after the run.

Three weaknesses were found while writing this review, and all three are now fixed:

- A single expression could allocate 200 MB before returning anything. Engine limits now
  cap the size of a value, the length of a statement and its nesting depth.
- The internal schema table was readable. It is now refused, with an error that points the
  agent at the documented catalog instead.
- Deeply nested SQL crashed the parser with an unhandled error. It now returns a clear
  refusal.

On prompt injection, the agent was asked a normal question against a database whose
condition text told it to ignore its instructions and reply with a single word. It answered
the real question, did not comply, and reported the embedded instruction in its caveats as
a sign the source text had been tampered with.

## Residual risks

- **Data leaves the machine.** Questions, schema descriptions and query results are sent to
  the Anthropic API. That is acceptable for synthetic data and is not acceptable for
  protected health information. Before real data is used, this needs either a contractual
  arrangement covering it or a deployment where the model runs inside the same boundary,
  such as a cloud provider's hosted models inside the organisation's own account.
- **The model is not a boundary, and refusals are not guaranteed.** Every protection that
  matters is enforced in code. The prompt rules are a convenience, not a control.
- **Staff names are readable.** The providers and organizations tables are not restricted,
  because analysts group by facility and speciality. With real data, provider names may
  need the same treatment as patient identifiers.
- **Blocked columns are blocked, not masked.** An analyst cannot reach an identifier, but
  small groups can still be narrow enough to identify someone. There is no minimum group
  size rule yet, which is worth discussing with Telligen.
- **Run logs hold answers and SQL.** They are git-ignored and stay on the machine. With
  real data they become sensitive files and need the same handling as the database. The
  request log holds client addresses, which are personal data in some jurisdictions.
- **One shared token is not access control per person.** Everyone holding it looks the same,
  so the log cannot say who asked what, and revoking one person means changing it for all.
  It suits a demonstration. Real accounts are deferred until the rest of the plan is done.
- **The token travels in the clear without TLS.** The service speaks plain HTTP. A deployed
  instance must sit behind HTTPS, such as a reverse proxy or a platform's own front end.
- **The daily budget lives in memory.** A restart resets the day's spending. With several
  server processes, each keeps its own ledger, so the effective budget multiplies, and each
  would let the same conversation answer two questions at once. One process is the
  supported deployment for now. A conversation's own budget is stored with it.
- **Conversations are stored on disk, with result rows.** `Backend/data/conversations.db`
  holds every question, answer, SQL statement and the rows each query returned, so a
  reopened conversation can show its evidence. It is git-ignored and unencrypted. With real
  data it is a copy of query results and needs the same handling as the database. Setting
  `SQL_AGENT_STORE_RESULT_ROWS=false` stores answers without rows, though the answer text
  still states figures, and `SQL_AGENT_CONVERSATIONS_PATH=off` stores nothing. Deleting a
  conversation removes its rows from the database file, but not from backups or the run log.
- **Everyone holding the token sees every conversation.** There are no accounts, so the
  list is shared, and anyone with the token can read, rename or delete any conversation.
  The `owner` column is in place for when accounts exist.
- **A downloaded report is a copy of the evidence.** It holds the SQL and the rows each
  query returned, and once saved it can be emailed or uploaded like any file. With real
  data, a report needs the handling of a query extract. Setting
  `SQL_AGENT_STORE_RESULT_ROWS=false` leaves rows out of stored answers, and so out of
  their reports.
- **An analysis reads more rows into memory.** Up to 100,000 rows per call, with the same
  time limit as any query. With four questions at once that is bounded, but it is more
  memory than `run_sql` uses. Lower the cap if the host is small.
- **Small groups are flagged, not suppressed.** `compare_groups` and `summarize` name any
  group under 20, but still report it. A minimum group size is still a decision to make.
- **The budget is counted in tokens, not money.** The figures in the evaluation give the
  cost of a typical question. Set the daily budget with the model's current price in mind.
  Since people can choose the model, one budget now covers models whose prices differ
  a hundredfold: a day's tokens on Haiku 5.5 cost far less than the same tokens on Opus.
  The model and its price are in the catalog, so a budget in dollars is a small change when
  it is needed.
- **The model is chosen by the browser, from a list the service keeps.** The service refuses
  any model or effort not in `sql_agent/models.py`, and any admin-only model, before
  anything runs, so a caller cannot pick an unlisted or older model. Every model sends the
  same thinking, effort and structured-output settings, so the same checks apply to every
  answer. Only Opus 5 has been scored by the evaluation; the others are labelled "Not yet
  evaluated" in the picker.
- **Browser storage of the token is the interface's problem.** The web interface will need
  to keep the token somewhere, and wherever that is becomes something to protect.

## Before this runs on real data

1. Settle where the model runs and whether patient data may be sent to it.
2. Re-run the catalogue against the real database, since the blocked-column list is
   specific to the tables it names.
3. Decide on a minimum group size for reported results, for answers, analyses and reports
   alike, and whether reports may carry rows at all.
4. Replace the shared token with real accounts, serve over HTTPS, and review the daily
   budget against the model's price.
