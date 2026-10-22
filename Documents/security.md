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
.venv/bin/python -m pytest tests/test_accounts.py tests/test_auth_routes.py tests/test_google_login.py -q   # accounts
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
| Anyone who can reach the service using it | Every endpoint except health and signing in needs an account's session. The session is a random 32-byte token in an HttpOnly, SameSite=Strict cookie, sent only to `/api` and only over HTTPS by default. Only its SHA-256 is stored. Sessions end after 30 idle days or 90 days, on sign-out, or when the account is disabled. With plain-HTTP cookies the service refuses to listen beyond this machine | Tests that every endpoint refuses a missing or forged session, that a signed-out cookie is dead, that sessions expire, and for the refusal to bind; a browser check that page scripts cannot read the cookie |
| One person reading or changing another's conversations | Every conversation query is filtered by its owner. Another person's conversation is answered exactly like one that does not exist (404), for reading, renaming, pinning, deleting, reports and follow-up questions. The cap on stored conversations is per owner, so nobody's use evicts anyone else's | A service test in which a second user tries each of those on the first user's conversation, and store tests of ownership and per-owner eviction |
| A request forged from another site | A request that changes something must carry `X-Requested-With: sql-agent`, which a page on another site cannot send without the CORS check passing, and any `Origin` it names must be allowed. The session cookie is SameSite=Strict as well | Tests that a request without the header, or from another origin, is refused with 403 even with a valid session, and a browser check of the same |
| Guessing passwords | Passwords are hashed with scrypt (n = 2^15) and a per-user salt, and must be 12 to 128 characters. A wrong password and an unknown email get the same answer in the same time. Failed sign-ins are limited per address and per email over 10 minutes | Tests of the hash, the rules, the identical answers and the throttle |
| Taking over an account through Google sign-in | The sign-in uses a one-time state bound to the browser by a cookie, a nonce and PKCE. The ID token's issuer, audience, expiry, nonce and verified email are checked. A Google identity is linked to an existing account only if its email was verified, by Google or by an admin, never to a self-registered one (ADR 0007). Where to return is limited to paths inside the application | Tests with a fake Google for a missing, mismatched, reused and expired state, each claim, linking rules, and unsafe return paths |
| Expensive models picked by anyone | Admin-only models are refused to everyone else before anything runs | A service test that a user is refused Fable 5.1 and an admin is not |
| Running commands through the admin console | Every check is a fixed list of arguments in `jobs.py`, run without a shell. The browser names a job and may add only a choice from a fixed list (a catalog model, an effort), checked before it becomes an argument. One job at a time, each with a time limit. The paid live evaluation is off unless switched on in `.env`. Every console route needs an admin's session and, for changes, the application header (ADR 0008) | Tests that a user gets 403 and a signed-out request 401 on every console route, that an unlisted choice is refused, that every real job is a fixed command, that the live evaluation is off by default, and that a run times out and can be cancelled |
| An admin locking everyone out | An admin cannot demote or disable themselves, or remove the last enabled admin | Tests of each refusal |
| Cost as a denial of service | Before a question reaches the model: a limit on questions running at once, a token budget per UTC day for the service and another per person, and a token budget per conversation. Runs still in progress hold a reservation, so a burst cannot overspend, and a run whose reader left still counts | Unit tests of the ledger, and service tests showing each limit refuses with a 429 before the model is called |
| Oversized requests | Bodies over 16 KB are refused whether or not they declare their length, and a question is capped at 2,000 characters | Tests for a declared and an undeclared oversized body |
| Statistics that read past the row cap | The analytics tools take their own SQL and may read up to `SQL_AGENT_ANALYSIS_MAX_ROWS` rows (100,000 by default), but through the same `run_query`: the same validator, authorizer, read-only connection, time limit and engine limits. Only the computed table reaches the model. A result over the cap is refused, never computed on in part | Every catalogue attack run a second time with the analysis cap, and eight more through the tools themselves, including identity columns named as the value or the group |
| A statistic or a chart the model made up | Statistics are computed by our code with SciPy. A chart names a query and its columns, and the plotted values are read from that query's recorded rows; one that cannot be resolved is not drawn and becomes a traceability warning | Unit tests of each analysis against values worked out by hand, of chart resolution and of every refusal; two chart checks in the evaluation |
| Hostile text in a report or a chart | Every value in a report is escaped, including inside SVG. A report has no script and no external reference, and a Content-Security-Policy, in the file and on the response, forbids loading anything. The interface draws charts with template bindings, so labels are text | Tests that a row holding `<script>`, `</style>` or `<svg onload>` stays text, that a report holds no script and no external reference, and that a chart's labels stay text |
| Untraceable use of the service | One line per request in `logs/requests.jsonl`: path, status, time, client address, the user's id and why it was refused. The run log names the user by id too. No bodies, no cookies and no emails | A test that a refusal and an answer are logged with the right user id, and that neither the session token nor the email appears |

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
- **Registration is open by default.** Anyone who can reach the service can make an
  account, and there is no email check or CAPTCHA, so one person can make many. Each
  account has its own daily budget and the service's budget still caps the total, but a
  deployed instance should close registration (`python -m sql_agent.users registration
  closed`) or put the sign-up page behind something that knows its users.
- **A self-registered email is not verified.** Nothing confirms that whoever registered an
  address owns it. That is why Google sign-in never links to such an account (ADR 0007).
  An email service would be needed to verify addresses and to reset forgotten passwords;
  until then, an admin resets a password from the command line.
- **The sign-in throttle lives in memory.** A restart resets it, and several processes would
  each keep their own. It slows guessing; it is not a lockout.
- **The service speaks plain HTTP.** Session cookies are marked Secure by default, which
  browsers honour on `http://localhost` only. A deployed instance must sit behind HTTPS, such
  as a reverse proxy or a platform's own front end.
- **The service's daily budget lives in memory.** A restart resets the service's spending
  for the day. A person's daily budget and a conversation's budget are rebuilt from the
  stored answers, so they survive a restart. With several server processes, each keeps its
  own ledger, so the effective budgets multiply, and each would let the same conversation
  answer two questions at once. One process is the supported deployment for now.
- **Conversations are stored on disk, with result rows.** `Backend/data/conversations.db`
  holds every question, answer, SQL statement and the rows each query returned, so a
  reopened conversation can show its evidence. It is git-ignored and unencrypted. With real
  data it is a copy of query results and needs the same handling as the database. Setting
  `SQL_AGENT_STORE_RESULT_ROWS=false` stores answers without rows, though the answer text
  still states figures, and `SQL_AGENT_CONVERSATIONS_PATH=off` stores nothing. Deleting a
  conversation removes its rows from the database file, but not from backups or the run log.
- **Conversations from before accounts belong to nobody until claimed.** They are invisible
  to everyone until `users create --claim-unowned` gives them to the first admin, who then
  holds every question asked before accounts existed.
- **The application database now holds accounts.** `data/conversations.db` keeps emails,
  password hashes and session hashes beside the conversations. It is git-ignored; a copy of
  it does not let anyone sign in, but it does reveal who has an account.
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
- **An admin can make the service spend, and use its CPU.** The connection checks make tiny
  model calls, the live evaluation costs dollars when switched on, and the test suite and the
  security catalogue use the server's CPU for up to a minute. Only admins can start them, one
  at a time.
- **A temporary password is shown to the admin who set it.** The admin hands it over by some
  other channel, and the person should change it at once; nothing forces them to yet.
- **The Google client secret sits in `Backend/.env`.** Like the Anthropic key, it is kept out
  of the settings object and never logged, but anyone who can read that file can impersonate
  this application to Google.

## Before this runs on real data

1. Settle where the model runs and whether patient data may be sent to it.
2. Re-run the catalogue against the real database, since the blocked-column list is
   specific to the tables it names.
3. Decide on a minimum group size for reported results, for answers, analyses and reports
   alike, and whether reports may carry rows at all.
4. Serve over HTTPS, close open registration or add email verification, and review the
   daily budgets against the models' prices.
