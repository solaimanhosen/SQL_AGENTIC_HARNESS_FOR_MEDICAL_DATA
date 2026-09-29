# Backend

Python backend for the SQL agent. It answers natural-language questions about the synthetic Synthea
database by planning, running read-only SQL, and explaining the result. Design decisions are recorded
in [docs/decisions](../docs/decisions).

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
.venv/bin/python -m sql_agent.check_setup            # includes one small Claude call
.venv/bin/python -m sql_agent.check_setup --offline  # everything except the Claude call
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
```

The agent plans, runs read-only SQL, checks what it gets back, and explains the answer.

Answers are structured rather than free prose. Each finding cites the numbered queries
behind it, the definitions are printed from the semantic layer along with whether they are
confirmed, and the dates of a time window are computed here rather than written by the
model. Anything the answer claims that the run does not support, such as a cited query that
never ran or a window no query filtered on, is printed under "Traceability warnings".

The SQL shown is recorded as each query runs, so it is what actually executed rather than
what the model says it ran. Add `--verbose` to watch each step as it happens, `--json` to
get the whole run as JSON, and `--no-sql` to hide the queries.

Every run is appended to `logs/runs.jsonl`, which is git-ignored. The log holds the
question, the answer, every query and what the run cost, and it is the raw material for the
evaluation harness. Set `SQL_AGENT_LOG_PATH=off` or pass `--no-log` to switch it off.

## Running the service

The web interface calls an HTTP service that wraps the same `SqlAgent.answer` method the
command line uses, so the two cannot drift apart.

```bash
.venv/bin/python -m sql_agent.serve                  # http://127.0.0.1:8000, docs at /docs
curl -s localhost:8000/api/health
curl -s -X POST localhost:8000/api/ask -H 'Content-Type: application/json' \
     -d '{"question": "How many patients have diabetes?"}'
```

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | Whether the database is readable, the model and the as-of date. No model call. |
| GET | `/api/schema` | The documented tables and columns. Identity columns never appear. |
| GET | `/api/definitions` | Every shared definition with its confirmation status. |
| GET | `/api/usage` | Questions running now and tokens spent today against the daily budget. |
| POST | `/api/ask` | The answer, its findings, the SQL with its rows, and any traceability warnings. |
| POST | `/api/ask/stream` | The same answer, preceded by each step as it happens, as server-sent events. |

The answer carries the same parts the command line prints, filled in from our own records:
each definition's status comes from the semantic layer, and the window dates are computed
here. Each query comes with the rows it returned, capped at the row limit, so the interface
can show the evidence. The rows are not written to the run log.

Every answer belongs to a conversation. Send the `conversation_id` from one answer with the
next question, and a follow-up such as "what about heart disease?" is understood. The agent
sees the last six questions with their answers and SQL as context. Query numbers start
again at 1 for each question, and a figure from an earlier answer must be queried again
before it is stated, so every citation still points at SQL that ran for this question.
Conversations are held in memory and a restart forgets them. One question at a time may be
answered in a conversation. A second one asked meanwhile gets a 409.

```bash
curl -sN -X POST localhost:8000/api/ask/stream -H 'Content-Type: application/json' \
     -d '{"question": "What about heart disease?", "conversation_id": "<id from the last answer>"}'
```

The stream sends a `conversation` event first, then a `step` event for each query, table
lookup and definition lookup, then either `answer`, with the same body `/api/ask` returns,
or `error`. It is a POST, so a browser reads it with `fetch` rather than `EventSource`.
A question keeps running if the reader disconnects, so its answer still reaches the log and
the conversation.

Errors come back as `{"error": kind, "message": text}`. A question the agent could not
answer is a 422, and a failure at the Anthropic API is a 502 or 503. An unknown or expired
conversation is a 404. The agent runs in a worker thread, so a slow question does not
block other requests.

### Access and limits

Set `SQL_AGENT_API_TOKEN` in `Backend/.env` to require a shared token on every endpoint
except health. Clients send `Authorization: Bearer <token>`. Without a token the service is
open, so `serve` refuses a `--host` other than this machine. Generate a token with:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"
```

A question is refused with a 429, before the model is called, when:
- too many are already running (`too_many_runs`, with a `Retry-After` header);
- the day's token budget is spent (`daily_budget`), reset at midnight UTC;
- the conversation's token budget is spent (`conversation_budget`), so start a new one.

A question still running counts against both budgets with a 60,000 token reservation until
it finishes. Request bodies over 16 KB get a 413. Every request, including a refused one, is
appended to `logs/requests.jsonl` without its body or token. Only the origins in
`SQL_AGENT_CORS_ORIGINS` may call the service from a browser. The limits and conversations
live in memory, so run one server process. See `docs/security.md` for what remains a risk.

## The semantic layer

Shared definitions such as which codes count as diabetes live in
`sql_agent/semantic/`, described in [docs/semantic-layer.md](../docs/semantic-layer.md).
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
[docs/security.md](../docs/security.md).

## Evaluation

The agent is scored against questions whose answers were verified by hand, in
`evals/questions.yaml`. Each question carries the SQL that produces the right answer, so a
change in the data is caught before the agent is asked anything.

```bash
.venv/bin/python -m sql_agent.evaluate --dry-run          # check the golden SQL only, free
.venv/bin/python -m sql_agent.evaluate                    # score the agent, costs money
.venv/bin/python -m sql_agent.evaluate --category safety  # just the safety questions
```

Results and known limitations are in [docs/evaluation.md](../docs/evaluation.md).

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
| `SQL_AGENT_MODEL` | `claude-opus-5` | Claude model ID. |
| `SQL_AGENT_EFFORT` | `high` | Reasoning effort: `low`, `medium`, `high`, `xhigh` or `max`. |
| `SQL_AGENT_MAX_TOKENS` | `16000` | Output token limit per model call. |
| `SQL_AGENT_DB_PATH` | `synthea.db` | Database path. Relative paths resolve against `Backend`. |
| `SQL_AGENT_CSV_DIR` | `data/synthea` | Source CSV folder read by the loader. |
| `SQL_AGENT_MAX_ROWS` | `200` | Largest number of rows one agent query may return. |
| `SQL_AGENT_QUERY_TIMEOUT` | `15` | Seconds before a query is stopped. |
| `SQL_AGENT_LOG_PATH` | `logs/runs.jsonl` | Where runs are logged. `off` disables logging. |
| `SQL_AGENT_AS_OF_DATE` | `latest` | Anchor for "last N months": `latest`, `today` or `YYYY-MM-DD`. |
| `SQL_AGENT_REFUSAL_FALLBACK` | `true` | Retry a declined request on a fallback model in the same call. |
| `SQL_AGENT_CORS_ORIGINS` | `http://localhost:4200` | Comma-separated browser origins allowed to call the service. |
| `SQL_AGENT_API_TOKEN` | none | Shared bearer token for the service, at least 32 characters. Never commit it. |
| `SQL_AGENT_MAX_CONCURRENT_RUNS` | `4` | Questions the service answers at once. More are refused. |
| `SQL_AGENT_DAILY_TOKEN_BUDGET` | `5000000` | Model tokens the service may spend per UTC day. |
| `SQL_AGENT_CONVERSATION_TOKEN_BUDGET` | `1000000` | Model tokens one conversation may spend. |
| `SQL_AGENT_REQUEST_LOG_PATH` | `logs/requests.jsonl` | Where each HTTP request is logged. `off` disables it. |

## Layout

| Path | Purpose |
|---|---|
| `sql_agent/config.py` | Loads and validates settings. |
| `sql_agent/llm.py` | Builds the Claude chat model. |
| `sql_agent/check_setup.py` | Setup check script. |
| `main.py` | Command line entry point for asking a question. |
| `sql_agent/service.py` | The HTTP service, a thin layer over the agent. |
| `sql_agent/serve.py` | Runs the service. |
| `sql_agent/conversations.py` | Holds each conversation's recent turns for follow-up questions. |
| `sql_agent/limits.py` | Concurrency and token budgets for the service. |
| `sql_agent/requestlog.py` | Logs each HTTP request. |
| `sql_agent/agent.py` | The agent loop, and the reusable core a web service will call. |
| `sql_agent/answer.py` | The shape of an answer, its rendering and its self-checks. |
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
