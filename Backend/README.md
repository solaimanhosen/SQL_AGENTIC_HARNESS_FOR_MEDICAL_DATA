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

## Tests

```bash
.venv/bin/python -m pytest
```

The tests make no network calls.

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
| `SQL_AGENT_AS_OF_DATE` | `latest` | Anchor for "last N months": `latest`, `today` or `YYYY-MM-DD`. |
| `SQL_AGENT_REFUSAL_FALLBACK` | `true` | Retry a declined request on a fallback model in the same call. |

## Layout

| Path | Purpose |
|---|---|
| `sql_agent/config.py` | Loads and validates settings. |
| `sql_agent/llm.py` | Builds the Claude chat model. |
| `sql_agent/check_setup.py` | Setup check script. |
| `sql_agent/semantic/` | Schema catalog and shared definitions, as YAML. |
| `sql_agent/semantic.py` | Loads, renders and validates the semantic layer. |
| `sql_agent/check_semantics.py` | Checks the definitions against the data. |
| `sql_agent/run_sql.py` | Runs one statement through the guardrails. |
| `sql_agent/sql_guard.py` | Static validation of model-written SQL. |
| `sql_agent/db.py` | Read-only database access with the authorizer and limits. |
| `sql_agent/load_data.py` | Builds `synthea.db` from the CSV files. |
| `data/synthea/` | Synthea source CSV files, committed so results stay reproducible. |
| `tests/` | Unit tests. |
