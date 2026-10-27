# SQL agent for healthcare data

Ask a question about patient data in plain language and get an explained answer, with the
SQL and the evidence behind every figure.

> How many diabetic patients had an emergency visit in the last 12 months?
>
> **3 of the 8 diabetic patients had an emergency department visit in the last 12 months.**
> Each finding names the query that produced it, the definitions it relied on and whether
> they are confirmed, and the exact dates of the window.

An Iowa State University Creative Component project (fall 2026), built for Telligen. It
runs on a synthetic [Synthea](https://synthetichealth.github.io/synthea/) database of 108
patients, so no real patient data is involved.

## How it works

1. **Plan.** The agent, Claude through LangChain (Opus 5 by default, or another model
   chosen for the question), works out what the question means.
   It uses shared definitions, such as which diagnosis codes make a patient diabetic,
   rather than inventing one for each question.
2. **Query.** It writes one read-only SELECT at a time. Three independent layers make sure
   nothing else can run: a validator, a SQLite authorizer that also blocks patient
   identifiers, and a read-only connection with row and time limits.
3. **Check.** It reads each result and re-checks any figure that looks surprising.
4. **Explain.** It returns a structured answer in which every figure cites its query. The
   system compares the answer with what actually ran and flags anything it cannot trace.

For statistics the agent calls a fixed set of analytics tools: summaries such as a median
over thousands of rows, trends judged by a Mann-Kendall test, and group comparisons with
Fisher's exact test or a permutation test. The model chooses the tool and writes its SQL;
the numbers are computed in code. An answer can carry bar and line charts, drawn from the
rows of the query each one cites, and any answer downloads as a self-contained HTML report
that opens with no network.

Follow-up questions build on the conversation, each step appears live while the agent
works, and the answer appears as a draft while it is written. Conversations are stored, so
an earlier one can be reopened from the sidebar, searched, pinned and continued. A question
can be stopped while it is being answered.

People sign in with an account, by password or with Google, and see only their own
conversations. A forgotten password is reset through a link sent by email. In the question box they choose the model (Opus 5, Opus 5.5, Sonnet 5.5,
Sonnet 5 or Haiku 5.5) and how hard it thinks. Admins also get a console that runs the
project's checks from the browser, shows usage and cost, and manages accounts.

## Repository layout

| Path | What is there |
|---|---|
| [`Backend/`](Backend/README.md) | The agent, its safety layers, the semantic layer, the HTTP service, the evaluation and the tests. Python 3.10+. |
| [`Frontend/`](Frontend/README.md) | The chat interface. Angular 22 and TypeScript. |
| [`Documents/`](Documents/) | The semantic layer, the evaluation, the security review, the decision records, and sample questions from Telligen. |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each release. |

## Quick start

You need Python 3.10 or later, Node 22.22 or 24.15 or later, and an Anthropic API key.

```bash
# The backend: install, add the key, build the database, start the service
cd Backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                          # then paste ANTHROPIC_API_KEY into .env
.venv/bin/python -m sql_agent.load_data
.venv/bin/python -m sql_agent.users create you@example.org --admin --claim-unowned
.venv/bin/python -m sql_agent.serve           # http://127.0.0.1:8000, API docs at /docs

# The interface, in a second terminal
cd Frontend
npm install
npm start                                     # open http://localhost:4200 and sign in
```

Prefer the terminal? From `Backend/`:

```bash
.venv/bin/python main.py "How many patients have diabetes?"
```

## Checking it works

| Check | Command, run from `Backend/` unless noted | Current result |
|---|---|---|
| Backend tests, no network | `.venv/bin/python -m pytest -q` | 522 passed, 3 skipped |
| Attack catalogue | `.venv/bin/python -m sql_agent.check_security` | 78 of 78 as expected |
| Evaluation against hand-verified answers | `.venv/bin/python -m sql_agent.evaluate` | 23 of 23 on Opus 5; other models not yet scored |
| Interface tests, from `Frontend/` | `npm test -- --watch=false` | 188 passed |

The evaluation calls the model and costs money. Add `--dry-run` to check only the known
answers against the data, for free.

## Status

| Release | What it delivered |
|---|---|
| v1.0.0 | The backend: agent, safety layers, semantic layer, traceable answers, evaluation, security review |
| v1.1.0 | The HTTP service: follow-up questions, live steps, access token, spending limits |
| v2.0.0 | The web interface: chat, live steps, transparency panels, result tables, CSV and JSON downloads |
| v2.1.0 | Stored conversations with a sidebar to reopen, rename and delete them, and answers streamed as they are written |
| v3.0.0 | Analytics tools, charts drawn from the run, and self-contained HTML reports |
| v4.0.0 | A redesigned interface with themes, a model and effort picker, accounts with Google sign-in, and an admin console |

Still to come: scoring the other models on the evaluation, a PostgreSQL design, and
deployment.

## Before using real data

This project is proven on synthetic data only. Questions, schema descriptions and query
results are sent to the Anthropic API. That is fine for synthetic data, and it is not fine
for protected health information without a deployment decision first. Read the residual
risks in [`Documents/security.md`](Documents/security.md) before pointing it at anything real.

## Further reading

- [Backend guide](Backend/README.md): every command, setting and safety layer
- [Semantic layer](Documents/semantic-layer.md): the schema catalog and shared definitions
- [Evaluation](Documents/evaluation.md): how answers are scored, and the latest results
- [Security review](Documents/security.md): threats, controls, evidence and residual risks
- [Analytics, charts and reports](Documents/analytics-and-reports.md): the design and results of v3.0.0
- [Decision records](Documents/decisions/): why LangChain and Claude, how time windows are anchored, where conversations are stored, how analytics are computed, the model catalog, accounts, Google sign-in, the admin console, and links sent by email

## License

No license has been chosen yet, so all rights are reserved for now. One will be added once
the terms with the project sponsor are confirmed.
