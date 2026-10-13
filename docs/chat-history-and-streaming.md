# Conversation history and streamed answers (v2.1.0)

This document records what this piece of work adds, why it is built the way it is, and how
far it has got. It is kept up to date as each step lands, and it is the source for the
Demo 2 slides on this work.

## What changes, in short

- **Conversations are kept.** Every question and answer is stored on disk, a sidebar lists
  earlier conversations, and opening one shows it in full and lets you carry on asking.
- **Answers appear as they are written.** The headline and findings are shown as a draft
  while the model writes them, then replaced by the checked answer.
- **Nothing about trust changes.** The safety layers are untouched, and the citations,
  definition statuses and window dates still come from our own records, only once the
  answer is complete.

## Before and after

| | v2.0.0 | v2.1.0 |
|---|---|---|
| Where conversations live | Server memory, at most 1,000 | A SQLite file, `Backend/data/conversations.db` |
| After a server restart | Every conversation is gone | Every conversation is still there |
| After a page reload | The screen is empty | The same conversation reopens |
| Finding an earlier conversation | Not possible | Sidebar list, newest first |
| Managing conversations | Start a new one | New chat, rename, delete |
| What streams while the agent works | Each step (SQL, results, lookups) | Each step, then the answer text as a draft |
| When the answer text is first seen | When the whole answer is finished | As soon as the model starts writing it |
| Per-conversation token budget | Reset by a restart | Stored with the conversation |

## Design

### Storage

Conversations go in their own SQLite file, written with Python's standard `sqlite3` module.
They do not go in `synthea.db`: that database is opened read-only by the agent and is
replaced whenever the loader runs.

The stored unit is a **turn**, one question with its answer. An answer here is not a block
of text. It is a structured answer with its queries, result rows and steps, so a `turns`
table fits better than a `messages` table with a role column.

Each turn stores two things for two different readers:

- **For the screen:** the full answer exactly as the service returned it, and the steps the
  agent took. Reopening a conversation shows what the user saw at the time, including each
  definition's status on that day.
- **For the model:** the answer text with citations removed, and the SQL that succeeded.
  This is what a follow-up question is shown.

### What the model sees in a long conversation

The whole conversation is kept on disk and shown on screen, but the model is shown only the
**last 6 turns**, each as question, answer and SQL, without result rows. This is the same
rule as v2.0.0. It bounds the cost of a follow-up no matter how long the conversation grows.
A follow-up re-runs any query whose figure it states, so nothing is quoted from memory.

### Who sees which conversations

The service has one shared access token and no user accounts, by the decision of
28 September 2026. So there is one shared list: everyone holding the token sees every
conversation. The `conversations` table has an `owner` column that stays empty until
accounts exist.

### Titles

A conversation's title is its first question, cut to 60 characters. It costs no model call
and is the same every time. It can be renamed.

### Streaming

The transport is the one already in place: server-sent events over a `fetch` POST to
`/api/ask/stream`. The stream is one-way, so WebSockets would add nothing.

The agent now runs with LangChain's `agent.stream` instead of `agent.invoke`. The model's
answer is a structured document, not prose, so it arrives as JSON in pieces. The service
reads the headline and finding statements out of the partial JSON and sends them as
`answer_delta` events. Each event carries the whole draft so far, so the interface simply
shows the latest one.

A live check on 13 October 2026 confirmed how the answer arrives: LangChain uses the
model's native structured output, so the answer is JSON text from the model, not a tool
call. For "How many patients have diabetes?" the run took 10.1 seconds, the first draft
text arrived at 6.6 seconds, and 26 drafts followed over the next 1.7 seconds. The steps
fill the time before that, as they did in v2.0.0.

The draft is labelled as a draft. Citations, definition statuses, window dates and the
traceability checks need the complete answer, so they appear only when the final `answer`
event replaces the draft.

| Event | When | Carries |
|---|---|---|
| `conversation` | First | The conversation id and turn number |
| `step` | Each tool call | The kind of step and its detail |
| `answer_delta` | While the answer is written | The draft headline and findings so far |
| `answer` | Last, on success | The complete, checked answer |
| `error` | Last, on failure | What went wrong |

### When something fails midway

| What happens | What the user sees | What is stored |
|---|---|---|
| The model or the agent fails | The draft is removed, with an error and "Try again" | Nothing for that turn |
| The browser loses the connection | The conversation is reloaded from the service | The run finishes on the server and its turn is stored |
| The page is closed | Nothing | The same: the run finishes and is stored |
| The server stops mid-run | An error on the next request | Nothing for that turn; earlier turns are safe |

A turn is written once, after its answer has passed the checks. Partial text is never stored.

## Schema

`conversations`

| Column | Meaning |
|---|---|
| `id` | 32 hexadecimal characters, random |
| `owner` | Empty until accounts exist |
| `title` | First question, or the name the user gave |
| `created_at`, `updated_at` | UTC timestamps |
| `turn_count` | Questions answered |
| `tokens_spent` | Model tokens this conversation has used |

`turns`, with primary key `(conversation_id, turn)`, deleted with their conversation

| Column | Meaning |
|---|---|
| `conversation_id`, `turn` | Which conversation, and the position in it from 1 |
| `question` | The question as asked |
| `answer_json` | The answer as the service returned it |
| `steps_json` | The steps the agent took |
| `context_answer`, `context_sql_json` | What a follow-up is shown |
| `created_at` | UTC timestamp |
| `input_tokens`, `output_tokens` | What the turn cost |

## API

| Endpoint | Change |
|---|---|
| `GET /api/conversations` | New. The list, newest first |
| `GET /api/conversations/{id}` | New. One conversation with every turn |
| `PATCH /api/conversations/{id}` | New. Rename |
| `DELETE /api/conversations/{id}` | New. Delete, refused while a question is running |
| `POST /api/ask/stream` | Gains the `answer_delta` event |
| `POST /api/ask` | Unchanged |

Every new endpoint requires the access token when one is configured.

## Decisions

| Decision | Why | Turned down |
|---|---|---|
| A separate SQLite file | The patient database is read-only and rebuilt by the loader | Tables inside `synthea.db` |
| `turns`, not `messages` | An answer is structured, with queries and rows | One row per message with a role |
| Last 6 turns to the model | Bounded cost, already proven in v2.0.0 | Sending everything; summarising old turns |
| Title from the first question | Free, instant, repeatable | A model call per conversation |
| One shared list | There are no accounts yet | A per-browser id, which separates lists without securing them |
| Keep SSE | Already in place, one-way is enough | WebSockets |
| Draft, then checked answer | Exact parts must come from our records | Showing citations and statuses before the checks run |
| Store result rows, with a switch | A reopened conversation should show its tables | Never storing rows, which leaves reopened answers without evidence |
| Rename and delete now | Stored answers must be removable | Search, pinning and archiving, which can wait |
| No new dependencies | SQLite and the streaming support are already installed | An ORM or a migration tool |

## Risks to state plainly

- Answers and result rows are now on disk. That is fine for synthetic data. Before real
  patient data, set `SQL_AGENT_STORE_RESULT_ROWS=false` or make a deployment decision; see
  `docs/security.md`.
- Everyone with the token sees every conversation.
- The service must still run as one process. The busy flag and the daily budget are in
  memory.

## Status

| Step | What | Status | Commit |
|---|---|---|---|
| 1 | Branch `sql_agent/chat/dev`, this document, live check of how the answer streams | Done | `fbe26d4` |
| 2 | Backend: streamed answer draft | Done | |
| 3 | Backend: conversations stored in SQLite | Pending | |
| 4 | Backend: list, open, rename and delete endpoints | Pending | |
| 5 | Interface: draft answer while the agent works | Pending | |
| 6 | Interface: conversation sidebar | Pending | |
| 7 | Security catalogue, evaluation re-run, documentation | Pending | |

## Results

Filled in when the work is finished: test counts, the evaluation score, the security
catalogue, and how soon the first answer text appears.

## Demo notes

Filled in when the work is finished: what to show live, in what order, and what to say
about the limits.
