# ADR 0003: Where conversations are stored

- **Status:** Accepted on 2026-10-13.
- **Decision:** Conversations are stored in their own SQLite file, one row per answered question, and the model is shown only the most recent turns.

## Context

Through v2.0.0 the service kept conversations in memory. A restart forgot them, a page
reload emptied the screen, and there was no way to find an earlier conversation. The
interface needed a list of conversations that can be reopened and continued.

Three things constrain the design:

- The patient database is opened read-only by the agent, and the loader replaces the whole
  file when it rebuilds. Nothing else may write to it.
- An answer is not a block of text. It is a structured answer with the SQL that ran, the
  rows returned, the steps taken and the result of the traceability checks.
- There are no user accounts, only one shared token (settled on 2026-09-28).

## Decision

1. Conversations live in `Backend/data/conversations.db`, written with Python's `sqlite3`.
   No new dependency, no ORM, no migration tool.
2. The stored unit is a turn: one question with its answer. Each turn keeps the answer as
   the interface was sent it, so a reopened conversation shows what the user saw, and
   separately the short form a follow-up question is shown.
3. The model sees the last 6 turns as question, answer and SQL, without rows. This is the
   v2.0.0 rule, unchanged. The full history is for people, not for the model.
4. A title is the first question cut to 60 characters. No model call.
5. The list is shared by everyone holding the token. An `owner` column is left empty.
6. Result rows are stored by default and can be switched off.
7. At most 1,000 conversations are kept; the least recently used goes first.
8. Which conversations are answering stays in memory, since a run does not survive a
   restart either.

## Alternatives turned down

| Alternative | Why not |
|---|---|
| Tables inside `synthea.db` | It is read-only to the agent and replaced by the loader |
| A `messages` table with a role column | An assistant "message" here is a structured answer with queries and rows |
| Sending the whole conversation to the model | Cost grows with every question; 6 turns already resolve follow-ups in the evaluation |
| Summarising older turns with the model | Another model call and another thing to verify, for no measured need |
| Titles written by the model | A cost per conversation, and not repeatable in tests |
| A per-browser id to separate lists | It separates without securing: anyone with the token could still read everything |
| Never storing rows | A reopened answer would cite queries whose evidence cannot be shown |

## Consequences

- Answers and result rows are on disk. With real patient data that file needs the same
  handling as the database; see `Documents/security.md`.
- A stored answer is a snapshot. If a definition is confirmed later, an old answer still
  shows the status it had when it was given.
- The service must still run as one process.
- When accounts arrive, `owner` is filled in and the list is filtered by it.
