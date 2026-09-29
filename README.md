# SQL agent for healthcare data

Ask a question about patient data in plain language and get an explained answer, with the
SQL and the evidence behind every figure.

> How many diabetic patients had an emergency visit in the last 12 months?
>
> **3 of the 8 diabetic patients had an emergency department visit in the last 12 months.**
> Each finding names the query that produced it, the definitions it relied on and whether
> they are confirmed, and the exact dates of the window.

An Iowa State University senior design project (team sb_cc_2, fall 2026), built for
Telligen. It runs on a synthetic [Synthea](https://synthetichealth.github.io/synthea/)
database of 108 patients, so no real patient data is involved.

## How it works

1. **Plan.** The agent, Claude Opus 5 through LangChain, works out what the question means.
   It uses shared definitions, such as which diagnosis codes make a patient diabetic,
   rather than inventing one for each question.
2. **Query.** It writes one read-only SELECT at a time. Three independent layers make sure
   nothing else can run: a validator, a SQLite authorizer that also blocks patient
   identifiers, and a read-only connection with row and time limits.
3. **Check.** It reads each result and re-checks any figure that looks surprising.
4. **Explain.** It returns a structured answer in which every figure cites its query. The
   system compares the answer with what actually ran and flags anything it cannot trace.

Follow-up questions build on the conversation, and each step appears live while the agent
works.

## Repository layout

| Path | What is there |
|---|---|
| [`Backend/`](Backend/README.md) | The agent, its safety layers, the semantic layer, the HTTP service, the evaluation and the tests. Python 3.10+. |
| [`Frontend/`](Frontend/README.md) | The chat interface. Angular 22 and TypeScript. |
| [`docs/`](docs/) | The semantic layer, the evaluation, the security review and the decision records. |
| `Documents/` | The project brief and sample questions from Telligen. |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each release. |

## Quick start

You need Python 3.10 or later, Node 22.22 or 24.15 or later, and an Anthropic API key.

```bash
# The backend: install, add the key, build the database, start the service
cd Backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                          # then paste ANTHROPIC_API_KEY into .env
.venv/bin/python -m sql_agent.load_data
.venv/bin/python -m sql_agent.serve           # http://127.0.0.1:8000, API docs at /docs

# The interface, in a second terminal
cd Frontend
npm install
npm start                                     # open http://localhost:4200
```

Prefer the terminal? From `Backend/`:

```bash
.venv/bin/python main.py "How many patients have diabetes?"
```

## Checking it works

| Check | Command, run from `Backend/` unless noted | Current result |
|---|---|---|
| Backend tests, no network | `.venv/bin/python -m pytest -q` | 238 passed |
| Attack catalogue | `.venv/bin/python -m sql_agent.check_security` | 35 of 35 blocked |
| Evaluation against hand-verified answers | `.venv/bin/python -m sql_agent.evaluate` | 20 of 20 |
| Interface tests, from `Frontend/` | `npm test -- --watch=false` | 22 passed |

The evaluation calls the model and costs money. Add `--dry-run` to check only the known
answers against the data, for free.

## Status

| Release | What it delivered |
|---|---|
| v1.0.0 | The backend: agent, safety layers, semantic layer, traceable answers, evaluation, security review |
| v1.1.0 | The HTTP service: follow-up questions, live steps, access token, spending limits |
| In progress | The web interface: chat and live steps done; panels for SQL, definitions and results next |

Still to come: analytics and charts over query results, self-contained HTML reports, a
PostgreSQL design, and deployment.

## Before using real data

This project is proven on synthetic data only. Questions, schema descriptions and query
results are sent to the Anthropic API. That is fine for synthetic data, and it is not fine
for protected health information without a deployment decision first. Read the residual
risks in [`docs/security.md`](docs/security.md) before pointing it at anything real.

## Further reading

- [Backend guide](Backend/README.md): every command, setting and safety layer
- [Semantic layer](docs/semantic-layer.md): the schema catalog and shared definitions
- [Evaluation](docs/evaluation.md): how answers are scored, and the latest results
- [Security review](docs/security.md): threats, controls, evidence and residual risks
- [Decision records](docs/decisions/): why LangChain and Claude, and how time windows are anchored
