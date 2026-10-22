# Backend

Python backend for the SQL agent. It answers natural-language questions about the synthetic Synthea
database by planning, running read-only SQL, and explaining the result. Design decisions are recorded
in [Documents/decisions](../Documents/decisions).

## Setup

Run these commands from the `Backend` folder. Python 3.10 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # or requirements.lock for the exact tested versions
cp .env.example .env                        # skip if .env already exists
```

Open `Backend/.env` and paste your Anthropic API key after `ANTHROPIC_API_KEY=`. The file is
git-ignored. Then check the setup:

```bash
.venv/bin/python -m sql_agent.check_setup               # includes one small Claude call
.venv/bin/python -m sql_agent.check_setup --all-models  # one small call to every model offered
.venv/bin/python -m sql_agent.check_setup --offline     # no Anthropic API calls at all
```

## Building the database

`synthea.db` is generated, so it is not in git. Rebuild it from the CSV files in
`data/synthea` at any time, from the `Backend` folder. The loader is the only component
that writes to the database.

```bash
.venv/bin/python -m sql_agent.load_data
```

It takes a few seconds, checks every table's row count against its CSV file, and creates the
indexes the agent's joins rely on. The database is written to a temporary file and moved into
place only after those checks pass, so a failed run never leaves a half-built database. The
indexes roughly double the file size, to about 100 MB.

## Asking a question

```bash
.venv/bin/python main.py "How many diabetic patients had an ER visit?"
.venv/bin/python main.py --verbose "Compare ER visits for diabetic and other patients over the last year"
.venv/bin/python main.py --no-sql "Which age band has the most hospital visits?"
.venv/bin/python main.py --report visits.html "Show hospital visits by month"
```

The agent plans, runs read-only SQL, checks what it gets back, and explains the answer.

Answers are structured rather than free prose. Each finding cites the numbered queries
behind it, the definitions are printed from the semantic layer along with whether they are
confirmed, and the dates of a time window are computed here rather than written by the
model. Anything the answer claims that the run does not support, such as a cited query that
never ran or a window no query filtered on, is printed under "Traceability warnings".

The SQL shown is recorded as each query runs, so it is what actually executed rather than
what the model says it ran. Add `--verbose` to watch each step as it happens, `--json` to
get the whole run as JSON, `--no-sql` to hide the queries, and `--report FILE` to also
write the answer as a self-contained HTML report.

### Statistics and charts

For statistics the agent has three tools beside `run_sql`. Each runs its own read-only
SELECT through the same guardrails, may read up to 100,000 rows, and returns only the table
it computed, which is numbered and cited like any query:

| Tool | Computes |
|---|---|
| `summarize` | Count, mean, standard deviation, quartiles, median and range of a value, overall or per group |
| `trend` | A count, sum or mean per month, quarter or year, and its direction by a Mann-Kendall test. Periods the data only partly covers, such as the month holding the as-of date, are shown but left out of the verdict |
| `compare_groups` | Each group's rate with a 95% Wilson interval, or its mean; two groups are tested with Fisher's exact test or a permutation test |

An answer may ask for up to three bar or line charts. Each names a query and its columns,
and the values are read from that query's recorded rows, so a chart can only show numbers
that came out of SQL that ran. The design is in
[Documents/analytics-and-reports.md](../Documents/analytics-and-reports.md).

Every run is appended to `logs/runs.jsonl`, which is git-ignored. The log holds the
question, the answer, every query and what the run cost, and it is the raw material for the
evaluation harness. Set `SQL_AGENT_LOG_PATH=off` or pass `--no-log` to switch it off.

## Running the service

The web interface calls an HTTP service that wraps the same `SqlAgent.answer` method the
command line uses, so the two cannot drift apart.

```bash
.venv/bin/python -m sql_agent.users create you@example.org --admin --claim-unowned   # once
.venv/bin/python -m sql_agent.serve                  # http://127.0.0.1:8000, docs at /docs
curl -s localhost:8000/api/health
```

Every endpoint except health and signing in needs an account's session, so the easiest way
to ask is the web interface. From the command line, sign in first and keep the cookie:

```bash
curl -s -c jar -X POST localhost:8000/api/auth/login -H 'X-Requested-With: sql-agent' \
     -H 'Content-Type: application/json' -d '{"email": "you@example.org", "password": "..."}'
curl -s -b jar -X POST localhost:8000/api/ask -H 'X-Requested-With: sql-agent' \
     -H 'Content-Type: application/json' -d '{"question": "How many patients have diabetes?"}'
```

With the default `SQL_AGENT_SECURE_COOKIES=true`, curl keeps the cookie only over HTTPS or
for `localhost`; set it to `false` for plain HTTP on this machine.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | Whether the database is readable, the model and the as-of date. No model call. No session needed. |
| GET | `/api/auth/config` | Whether registration is open and Google sign-in is on. No session needed. |
| POST | `/api/auth/register` | `{email, password, name}`: make an account and sign in. 403 when registration is closed, 409 when the email is taken. |
| POST | `/api/auth/login` | `{email, password}`: sign in. A wrong password and an unknown email get the same 401. Throttled. |
| POST | `/api/auth/logout` | End this session. |
| GET | `/api/auth/me` | The signed-in person: email, name, role, sign-in methods, default model. |
| GET | `/api/auth/google/start`, `/callback` | Sign in with Google, or `?link=true` to connect it to the signed-in account. See ADR 0007. |
| PATCH | `/api/account` | Change your name, or default model and effort. |
| POST | `/api/account/password` | `{current, new}`: change your password. |
| GET, DELETE, POST | `/api/account/sessions`, `/{id}`, `/revoke-others` | List your sessions and sign them out. |
| POST | `/api/account/google/disconnect` | Disconnect Google; refused for an account with no password. |
| GET | `/api/account/usage` | Your tokens today against your daily budget, and this month's questions, tokens and estimated cost by model. |
| GET | `/api/schema` | The documented tables and columns. Identity columns never appear. |
| GET | `/api/definitions` | Every shared definition with its confirmation status. |
| GET | `/api/usage` | Questions running now and tokens spent today against the daily budget. |
| POST | `/api/ask` | The answer, its findings, the SQL with its rows, and any traceability warnings. Optional `model` and `effort` choose what answers this question; anything not in `/api/models` is a 422. |
| POST | `/api/ask/stream` | The same answer, preceded by each step as it happens and by the answer text as it is written, as server-sent events. |
| GET | `/api/conversations` | Stored conversations with at least one answer, most recently used first. With `?q=text`, only those whose title or any question contains it, at most 50. |
| GET | `/api/conversations/{id}` | One conversation: every question with its answer and steps as first sent, and whether it is still answering. |
| GET | `/api/models` | The models a question may run on, in the picker's order, with prices, effort levels and evaluation status, and the default model and effort. |
| PATCH | `/api/conversations/{id}` | Rename it with `{"title": "..."}` (1 to 100 characters), pin or unpin it with `{"pinned": true}`, or both. Neither counts as use. |
| POST | `/api/conversations/{id}/stop` | Stop the question the conversation is answering. It ends at its next step, nothing is saved, and the question gets a 409 `stopped`. |
| DELETE | `/api/conversations/{id}` | Delete it and its answers. A conversation still answering gets a 409. |
| GET | `/api/conversations/{id}/turns/{turn}/report` | One stored answer as a self-contained HTML report, as a download. |

The answer carries the same parts the command line prints, filled in from our own records:
each definition's status comes from the semantic layer, and the window dates are computed
here. Each query comes with the rows it returned, capped at the row limit, so the interface
can show the evidence; an analysis comes with the table it computed and what it found.
Charts come with their values, read from the query each one cites. The rows are not
written to the run log.

Every answer belongs to a conversation. Send the `conversation_id` from one answer with the
next question, and a follow-up such as "what about heart disease?" is understood. The agent
sees the last six questions with their answers and SQL as context. Query numbers start
again at 1 for each question, and a figure from an earlier answer must be queried again
before it is stated, so every citation still points at SQL that ran for this question.
One question at a time may be answered in a conversation. A second one asked meanwhile
gets a 409.

Conversations are stored in their own SQLite file, `data/conversations.db`, never in the
patient database, so they survive a restart and can be listed, reopened and continued. Each
answer is stored as it was sent, rows included, and titled after its conversation's first
question. Set `SQL_AGENT_STORE_RESULT_ROWS=false` to store answers without their rows, or
`SQL_AGENT_CONVERSATIONS_PATH=off` to keep conversations in memory only. At most 1,000
conversations are kept, and the least recently used unpinned one is removed first; pinned
ones go only after every unpinned one. See `Documents/chat-history-and-streaming.md` for the
design.

The file carries a schema version (`PRAGMA user_version`). Opening a file from an earlier
version upgrades it in place, one recorded step at a time, so nothing stored is lost. A file
from a newer version is refused untouched, and the service will not start on it.

```bash
curl -sN -X POST localhost:8000/api/ask/stream -H 'Content-Type: application/json' \
     -d '{"question": "What about heart disease?", "conversation_id": "<id from the last answer>"}'
```

The stream sends a `conversation` event first, then a `step` event for each query, table
lookup and definition lookup, then `answer_delta` events while the model writes the answer,
then either `answer`, with the same body `/api/ask` returns, or `error`. Each
`answer_delta` carries the headline and findings written so far. It is a draft: unchecked,
and without citations, definitions or dates, which come only with `answer`. It is a POST, so a browser reads it with `fetch` rather than `EventSource`.
A question keeps running if the reader disconnects, so its answer still reaches the log and
the conversation.

Errors come back as `{"error": kind, "message": text}`. A question the agent could not
answer is a 422, and a failure at the Anthropic API is a 502 or 503. An unknown or expired
deleted conversation is a 404. The agent runs in a worker thread, so a slow question does not
block other requests.

### The admin console's routes

Every route under `/api/admin` needs an admin's session (ADR 0008):

| Method | Path | Does |
|---|---|---|
| GET | `/api/admin/overview` | Database, application database, API key, Google and registration status, accounts, conversations, budgets, and the latest run of each check |
| GET | `/api/admin/metrics?days=14` | Per day: requests, refusals, errors and latency from the request log; questions, tokens and estimated cost from the run log, by model and by person |
| GET | `/api/admin/jobs` | The checks an admin can run, with their cost and latest run |
| POST | `/api/admin/jobs/{job}/runs` | Start one, with `{"choices": {...}}` from its fixed list. 409 while another runs |
| GET | `/api/admin/runs`, `/runs/{id}`, `/runs/{id}/stream` | History, one run with its output, and its output live as server-sent events |
| POST | `/api/admin/runs/{id}/cancel` | Stop a running check |
| GET, PATCH, POST | `/api/admin/users`, `/users/{id}`, `/users/{id}/reset-password` | List accounts; change a role or disable; set a temporary password |
| GET, PATCH | `/api/admin/settings` | Whether anyone may sign up |

The checks are fixed commands in `sql_agent/jobs.py`: the unit tests, the security
catalogue, the semantic layer, the dry-run evaluation, the setup check with one tiny model
call, a ping of every model, and the live evaluation. The live evaluation is off unless
`SQL_AGENT_ADMIN_LIVE_EVAL=1`.

### Accounts, access and limits

People sign in with an account (ADR 0006), by email and password or with Google (ADR 0007).
Each sees only their own conversations; another person's is a 404. There are two roles,
`user` and `admin`. Accounts are managed from the command line on the machine that runs the
service:

```bash
.venv/bin/python -m sql_agent.users create you@example.org --admin --claim-unowned
.venv/bin/python -m sql_agent.users list
.venv/bin/python -m sql_agent.users set-role someone@example.org admin
.venv/bin/python -m sql_agent.users disable someone@example.org
.venv/bin/python -m sql_agent.users reset-password someone@example.org
.venv/bin/python -m sql_agent.users registration closed
```

Passwords are typed at a hidden prompt. `--claim-unowned` gives the conversations from before
accounts to that account; until then nobody sees them. An account made here counts as having
a verified email, so its owner may later sign in with Google on the same address.

The session is an HttpOnly cookie. A request that changes something must also send
`X-Requested-With: sql-agent`, or it is refused as cross-site. With
`SQL_AGENT_SECURE_COOKIES=false`, `serve` refuses a `--host` other than this machine.

To switch on Google sign-in, create an OAuth client of type Web application in Google Cloud
Console with the redirect URI `<SQL_AGENT_PUBLIC_URL>/api/auth/google/callback`, which is
`http://localhost:4200/api/auth/google/callback` in development, and set
`SQL_AGENT_GOOGLE_CLIENT_ID` and `SQL_AGENT_GOOGLE_CLIENT_SECRET` in `Backend/.env`.

A question is refused with a 429, before the model is called, when:
- too many are already running (`too_many_runs`, with a `Retry-After` header);
- the day's token budget is spent (`daily_budget`), reset at midnight UTC;
- your own daily budget is spent (`user_budget`);
- the conversation's token budget is spent (`conversation_budget`), so start a new one.

A question still running counts against both budgets with a 60,000 token reservation until
it finishes. Request bodies over 16 KB get a 413. Every request, including a refused one, is
appended to `logs/requests.jsonl` with the user's id, and without its body or cookies. Only the origins in
`SQL_AGENT_CORS_ORIGINS` may call the service from a browser. The daily budget and the
record of which conversations are answering live in memory, so run one server process. A
conversation's own spending is stored with it. See `Documents/security.md` for what remains a risk.

## The semantic layer

Shared definitions such as which codes count as diabetes live in
`sql_agent/semantic/`, described in [Documents/semantic-layer.md](../Documents/semantic-layer.md).
Check them against the data, and see the text the agent will be given:

```bash
.venv/bin/python -m sql_agent.check_semantics
.venv/bin/python -m sql_agent.check_semantics --show-prompt
```

## Running SQL by hand

To try the guardrails or explore the data, run a statement through the same path the agent
uses. Anything rejected here is rejected for the agent too.

```bash
.venv/bin/python -m sql_agent.run_sql "SELECT encounterclass, COUNT(*) FROM encounters GROUP BY 1"
.venv/bin/python -m sql_agent.run_sql "DROP TABLE patients"
```

## Security

Three independent layers keep model-written SQL safe, described under "How queries are kept
safe" below. The attack catalogue proves it, and runs without a model:

```bash
.venv/bin/python -m sql_agent.check_security
```

The threat model, the results and the remaining risks are in
[Documents/security.md](../Documents/security.md).

## Evaluation

The agent is scored against questions whose answers were verified by hand, in
`evals/questions.yaml`. Each question carries the SQL that produces the right answer, so a
change in the data is caught before the agent is asked anything.

```bash
.venv/bin/python -m sql_agent.evaluate --dry-run          # check the golden SQL only, free
.venv/bin/python -m sql_agent.evaluate                    # score the agent, costs money
.venv/bin/python -m sql_agent.evaluate --category safety  # just the safety questions
.venv/bin/python -m sql_agent.evaluate --model claude-haiku-5-5 --effort low  # another model
```

Results and known limitations are in [Documents/evaluation.md](../Documents/evaluation.md).

## Tests

```bash
.venv/bin/python -m pytest
```

The tests make no network calls. An end to end test that does call the model is skipped by
default:

```bash
RUN_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_agent_live.py -q
```

## How queries are kept safe

The agent never talks to the database directly. Every statement it writes passes through
three independent layers, so no single mistake or clever prompt is enough to change data.

1. **The connection is read-only.** The file is opened in read-only mode, so the process
   cannot write to it even if everything else fails.
2. **A SQLite authorizer runs inside the engine.** It rejects every action except reading,
   and it refuses the identity columns listed below. Schema introspection runs on a
   separate trusted connection with this agent's own fixed SQL.
3. **Statements are validated before the database is opened.** Anything that is not a
   single SELECT is rejected, including multiple statements hidden behind a comment.

Two further limits protect against accidents rather than attacks. Results are capped, and
the caller is told when rows were left out. Queries that run past the time limit are
stopped, which catches accidental cartesian joins.

Blocked columns are the direct identifiers in `patients`: social security number, driver's
licence, passport, name parts, street address, birth place and exact coordinates. City,
state, county, postal code, birth date, gender, race and ethnicity stay available, because
analysts group by them and they do not identify a person on their own. The data is
synthetic, so this is about proving the pattern rather than protecting real people.

## Configuration

All settings are optional environment variables, read from the shell or from `Backend/.env`.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Required for Claude calls. Never commit it. |
| `SQL_AGENT_MODEL` | `claude-opus-5` | The default model, used when a question names none. Must be one in `sql_agent/models.py`. |
| `SQL_AGENT_EFFORT` | `high` | The default model's effort: `low`, `medium`, `high`, `xhigh` or `max`. |
| `SQL_AGENT_MAX_TOKENS` | `16000` | Output token limit per model call. |
| `SQL_AGENT_DB_PATH` | `synthea.db` | Database path. Relative paths resolve against `Backend`. |
| `SQL_AGENT_CSV_DIR` | `data/synthea` | Source CSV folder read by the loader. |
| `SQL_AGENT_MAX_ROWS` | `200` | Largest number of rows one agent query may return. |
| `SQL_AGENT_ANALYSIS_MAX_ROWS` | `100000` | Rows an analytics tool may read. Only its computed table reaches the model. |
| `SQL_AGENT_QUERY_TIMEOUT` | `15` | Seconds before a query is stopped. |
| `SQL_AGENT_LOG_PATH` | `logs/runs.jsonl` | Where runs are logged. `off` disables logging. |
| `SQL_AGENT_AS_OF_DATE` | `latest` | Anchor for "last N months": `latest`, `today` or `YYYY-MM-DD`. |
| `SQL_AGENT_REFUSAL_FALLBACK` | `true` | Retry a declined request on a fallback model in the same call. |
| `SQL_AGENT_CORS_ORIGINS` | `http://localhost:4200` | Comma-separated browser origins allowed to call the service. |
| `SQL_AGENT_SECURE_COOKIES` | `true` | Send the session cookie over HTTPS only. `false` is for plain HTTP on this machine. |
| `SQL_AGENT_REGISTRATION` | `open` | Whether anyone may sign up, until an admin changes it. |
| `SQL_AGENT_USER_DAILY_TOKEN_BUDGET` | `1000000` | Model tokens one person may spend per UTC day. |
| `SQL_AGENT_PUBLIC_URL` | `http://localhost:4200` | The address people open. Google returns them here. |
| `SQL_AGENT_GOOGLE_CLIENT_ID`, `_SECRET` | none | Google sign-in, off unless both are set. The secret is never logged; never commit it. |
| `SQL_AGENT_MAX_CONCURRENT_RUNS` | `4` | Questions the service answers at once. More are refused. |
| `SQL_AGENT_DAILY_TOKEN_BUDGET` | `5000000` | Model tokens the service may spend per UTC day. |
| `SQL_AGENT_CONVERSATION_TOKEN_BUDGET` | `1000000` | Model tokens one conversation may spend. |
| `SQL_AGENT_REQUEST_LOG_PATH` | `logs/requests.jsonl` | Where each HTTP request is logged. `off` disables it. |
| `SQL_AGENT_CONVERSATIONS_PATH` | `data/conversations.db` | Where conversations are stored. `off` keeps them in memory. |
| `SQL_AGENT_STORE_RESULT_ROWS` | `true` | Whether a stored answer keeps the rows its queries returned. |

## Layout

| Path | Purpose |
|---|---|
| `sql_agent/config.py` | Loads and validates settings. |
| `sql_agent/models.py` | The models people may choose, with prices and effort levels. Edited by hand; see ADR 0005. |
| `sql_agent/llm.py` | Builds the Claude chat model for one question's model and effort. |
| `sql_agent/check_setup.py` | Setup check script. |
| `main.py` | Command line entry point for asking a question. |
| `sql_agent/service.py` | The HTTP service, a thin layer over the agent. |
| `sql_agent/serve.py` | Runs the service. |
| `sql_agent/appdb.py` | The application database and its schema migrations. |
| `sql_agent/accounts.py`, `passwords.py` | Accounts, sessions and pending Google sign-ins; scrypt password hashing. |
| `sql_agent/auth.py`, `account_routes.py` | The session cookie, the cross-site check, the sign-in throttle, and the account routes. |
| `sql_agent/google_login.py` | Google sign-in and the rules for linking an account (ADR 0007). |
| `sql_agent/users.py` | Manage accounts from the command line. |
| `sql_agent/admin_routes.py`, `jobs.py`, `metrics.py` | The admin console's routes, its fixed checks and their runner, and figures read from the logs. |
| `sql_agent/conversations.py` | Stores conversations in SQLite: every answer for the interface, and the recent turns a follow-up is shown. |
| `sql_agent/limits.py` | Concurrency and token budgets for the service. |
| `sql_agent/requestlog.py` | Logs each HTTP request. |
| `sql_agent/agent.py` | The agent loop, and the reusable core a web service will call. |
| `sql_agent/answer.py` | The shape of an answer, its rendering and its self-checks. |
| `sql_agent/analytics.py` | The statistics behind the analytics tools, with no database or model code. |
| `sql_agent/charts.py` | Resolves an answer's charts from the run, and draws them as SVG for reports. |
| `sql_agent/payload.py` | The answer as the service sends, stores and reports it. |
| `sql_agent/report.py` | One answer as a self-contained HTML report. |
| `sql_agent/runlog.py` | Appends each run to the log. |
| `sql_agent/evaluate.py` | Scores the agent against known answers. |
| `sql_agent/check_security.py` | The attack catalogue and its runner. |
| `evals/questions.yaml` | The evaluation set, with hand-verified answers. |
| `sql_agent/tools.py` | The tools the agent can call, and the record of what they did. |
| `sql_agent/prompts.py` | The agent's instructions. |
| `sql_agent/semantic/` | Schema catalog and shared definitions, as YAML. |
| `sql_agent/semantic.py` | Loads, renders and validates the semantic layer. |
| `sql_agent/check_semantics.py` | Checks the definitions against the data. |
| `sql_agent/run_sql.py` | Runs one statement through the guardrails. |
| `sql_agent/sql_guard.py` | Static validation of model-written SQL. |
| `sql_agent/db.py` | Read-only database access with the authorizer and limits. |
| `sql_agent/load_data.py` | Builds `synthea.db` from the CSV files. |
| `data/synthea/` | Synthea source CSV files, committed so results stay reproducible. |
| `tests/` | Unit tests. |
