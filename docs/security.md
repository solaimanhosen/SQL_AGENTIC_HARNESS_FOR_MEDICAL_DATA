# Security review

This document records what the agent is protected against, how each protection is proven,
and what remains a risk. It covers the backend as it stands, running locally against a
synthetic database.

```bash
cd Backend
.venv/bin/python -m sql_agent.check_security          # run the attack catalogue
.venv/bin/python -m pytest tests/test_security.py -q  # the same attacks, as tests
RUN_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_agent_live.py -q   # prompt injection
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

## Results

The catalogue holds 35 cases: 32 attacks that must be blocked and 3 ordinary queries that
must keep working, so that over-blocking shows up as a failure too. All 35 behave as
expected, and the row counts of every table are identical before and after the run.

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
  real data they become sensitive files and need the same handling as the database.
- **There is no authentication.** Anyone who can run the command can ask anything. A web
  interface will need real access control, and that is a design question for that phase.
- **Cost is a denial of service of its own.** Nothing limits how many questions may be
  asked. A budget or a rate limit belongs with the web interface.

## Before this runs on real data

1. Settle where the model runs and whether patient data may be sent to it.
2. Re-run the catalogue against the real database, since the blocked-column list is
   specific to the tables it names.
3. Decide on a minimum group size for reported results.
4. Add access control and a spending limit alongside the web interface.
