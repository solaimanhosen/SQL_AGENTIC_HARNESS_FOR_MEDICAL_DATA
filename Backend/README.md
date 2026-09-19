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

To rebuild the database from the CSV files in `data/synthea`:

```bash
.venv/bin/python load_csv_to_sqlite.py
```

## Tests

```bash
.venv/bin/python -m pytest
```

The tests make no network calls.

## Configuration

All settings are optional environment variables, read from the shell or from `Backend/.env`.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Required for Claude calls. Never commit it. |
| `SQL_AGENT_MODEL` | `claude-opus-5` | Claude model ID. |
| `SQL_AGENT_EFFORT` | `high` | Reasoning effort: `low`, `medium`, `high`, `xhigh` or `max`. |
| `SQL_AGENT_MAX_TOKENS` | `16000` | Output token limit per model call. |
| `SQL_AGENT_DB_PATH` | `synthea.db` | Database path. Relative paths resolve against `Backend`. |
| `SQL_AGENT_AS_OF_DATE` | `latest` | Anchor for "last N months": `latest`, `today` or `YYYY-MM-DD`. |
| `SQL_AGENT_REFUSAL_FALLBACK` | `true` | Retry a declined request on a fallback model in the same call. |

## Layout

| Path | Purpose |
|---|---|
| `sql_agent/config.py` | Loads and validates settings. |
| `sql_agent/llm.py` | Builds the Claude chat model. |
| `sql_agent/check_setup.py` | Setup check script. |
| `tests/` | Unit tests. |
| `load_csv_to_sqlite.py` | Builds `synthea.db` from the CSV files. |
