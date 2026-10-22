# ADR 0008: An admin console that runs fixed checks only

- **Status:** Accepted on 2026-10-22.
- **Decision:** Admins get a console in the browser for the project's checks, monitoring and
  accounts. A check is one of a fixed set of commands chosen in `sql_agent/jobs.py`. The
  browser picks one by name; nothing it sends becomes part of a command except a choice from
  a fixed list.

## Context

The user asked for a page where an admin or system manager can run the tests, check the
connections and monitor the service. Until now every check was run from a terminal on the
machine that runs the service.

A page that runs commands on a server is a classic place for command injection. It must also
not become a back door around the agent's safety layers, for instance by offering a SQL box.

## Decision

1. **Seven jobs**, each a fixed list of arguments run without a shell, in `Backend/`:

   | Job | Command | Cost |
   |---|---|---|
   | Unit tests | `pytest -q --junitxml=<scratch>` | Free |
   | Security catalogue | `sql_agent.check_security` | Free |
   | Semantic layer | `sql_agent.check_semantics` | Free |
   | Evaluation, dry run | `sql_agent.evaluate --dry-run` | Free |
   | Setup and connections | `sql_agent.check_setup` | One two-token model call |
   | Ping every model | `sql_agent.check_setup --all-models` | Six two-token calls |
   | Evaluation, live | `sql_agent.evaluate --model M --effort E` | Several dollars; off unless `SQL_AGENT_ADMIN_LIVE_EVAL=1` |

2. **Choices.** The only thing the browser adds is a choice from a fixed list: the live
   evaluation's model, from the catalog, and its effort. Each is checked against its list
   before it becomes a separate argument.
3. **One job at a time,** each with a time limit (10 minutes for the tests, an hour for the
   live evaluation). It can be cancelled.
4. **Output.** It is read line by line and streamed to the console as server-sent events.
   Each run is kept, with its output capped at 200,000 characters (the end is kept) and a
   summary, in the application database (schema version 5, `check_runs`). A run cut short by
   a restart is marked interrupted.
5. **Monitoring** reads the logs the service already writes: requests, refusals, errors and
   latency per day from `logs/requests.jsonl`, and questions, tokens and estimated cost by
   day, model and person from `logs/runs.jsonl`. Nothing new is recorded for it.
6. **People.**
   - An admin lists accounts, changes a role, and disables or enables an account.
     Disabling signs the person out at once.
   - An admin can give someone a temporary password, shown once to the admin, which ends
     all their sessions.
   - An admin cannot demote or disable themselves, or remove the last enabled admin.
7. **Settings.** An admin opens or closes registration.
8. **Access.** Every route is under `/api/admin`, and needs an admin's session and, for
   changes, the application header. An admin sees totals and accounts, never the text of
   anyone's conversations.

## Alternatives turned down

| Alternative | Why not |
|---|---|
| Running the checks in the service's own process | A crash or hang in a check would take the service with it, and pytest cannot be run twice in one process |
| A shell command line in the browser | Remote code execution by design |
| A SQL box for admins | It would bypass the agent's guardrails and invite treating the console as a data tool; admins ask questions like anyone else |
| A separate monitoring stack, such as Prometheus and Grafana | Two more services to run for a single-process demo; the logs already hold what is needed |
| Admins reading anyone's conversations | Not needed to run the service, and it would change what users can expect |

## Consequences

- An admin can make the service spend a little: the connection checks make tiny model calls,
  and the console asks before starting them. The live evaluation stays off unless switched on
  in `.env`.
- Running the test suite or the security catalogue uses the server's CPU for up to a minute
  or so. That is acceptable for one process; a busy deployment would schedule checks
  elsewhere.
- Monitoring reads the whole log files on each request. That is fine at this size; a large
  deployment would rotate logs or keep counters.
