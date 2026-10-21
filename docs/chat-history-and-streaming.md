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
| The conversation list | None | A sidebar that can be resized by dragging its edge, or collapsed |
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

At most 1,000 conversations are kept. Beyond that the least recently used one is removed,
which bounds the disk the service can fill. Setting `SQL_AGENT_CONVERSATIONS_PATH=off`
keeps conversations in memory only, as v2.0.0 did.

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

### The sidebar's size

Added on 14 October 2026, after the first review.

- **Resize:** drag the sidebar's right edge. It stays between 200 px and 480 px, and never
  takes more than half the window, so on a 900 px window it stops at 450 px. The edge also
  responds to the keyboard (arrow keys, Home, End), and a double-click resets it to 272 px.
- **Collapse:** a button at the top of the sidebar hides it, and a button in the header
  brings it back. The chat column widens to fill the space with a short animation. Nothing
  about the conversation on screen changes, and the page does not reload.
- **Remembered:** the width and the collapsed state are kept in the browser's local
  storage, so they survive a reload. This is a convenience only: if storage is blocked the
  sidebar opens at its default size. Nothing sensitive is stored, and the access token is
  still never written to browser storage.
- **Phones:** below 768 px the sidebar is a drawer over the page, as before. Resizing is
  switched off there, and the hide button closes the drawer.

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

All eight steps are done on the branch `sql_agent/chat/dev`. It is not yet merged into
`main` or tagged v2.1.0.

| Step | What | Status | Commit |
|---|---|---|---|
| 1 | Branch `sql_agent/chat/dev`, this document, live check of how the answer streams | Done | `fbe26d4` |
| 2 | Backend: streamed answer draft | Done | `f9867d9` |
| 3 | Backend: conversations stored in SQLite | Done | `ed037b1` |
| 4 | Backend: list, open, rename and delete endpoints | Done | `e78b689` |
| 5 | Interface: draft answer while the agent works | Done | `85e579d` |
| 6 | Interface: conversation sidebar | Done | `a114e12` |
| 7 | Security catalogue, evaluation re-run, documentation | Done | `5868eec` |
| 8 | Interface: resizable and collapsible sidebar | Done | the commit after `5868eec` |

## Results

Measured on 13 October 2026 with Claude Opus 5.

| Check | v2.0.0 | v2.1.0 |
|---|---|---|
| Backend tests, no network | 238 passed | 272 passed |
| Interface tests, no network | 53 passed | 78 passed |
| Security catalogue | 35 of 35 | 35 of 35 |
| Evaluation | 20 of 20 | 20 of 20 |
| Evaluation cost | 433,148 in, 24,012 out, 6.3 minutes | 417,750 in, 23,739 out, 5.4 minutes |
| New dependencies | | None |

How soon answer text appears, from four questions asked through the interface in headless
Chrome:

| Question | First draft text | Checked answer |
|---|---|---|
| How many patients have diabetes? | 6.4 s | 9.9 s |
| And how many of them are women? (follow-up) | 6.7 s | 8.8 s |
| The same follow-up again | 8.9 s | 12.7 s |
| How many patients are in the database? | 4.6 s | 7.6 s |

The draft appears 2 to 4 seconds before the checked answer. Most of the wait before it is
the agent running queries, which the live steps already show. Streaming shortens the last
part of the wait. It does not make the whole run faster.

Checked by hand in the browser, against a real service:

- A conversation was reopened after the service was restarted, with its tables and rows,
  and a follow-up ("And how many of them are women?") was answered from the earlier turn:
  "Just 1 of the 8 diabetic patients is a woman."
- Reloading the page returned to the same conversation.
- New chat, rename and delete worked, and deleting the open conversation cleared the screen.
- At phone width (390 px) the page did not scroll sideways, and the sidebar opened as a
  drawer.
- Dragging the sidebar's edge resized it and stopped at 200 px and 480 px. Collapsing and
  expanding animated over 0.2 seconds, and a reload kept both the width and the collapsed
  state.

## Demo notes

A suggested order for showing this live, about three minutes:

1. **Start with the sidebar already holding two or three conversations.** Say that in
   Demo 1 a restart or a reload lost everything.
2. **Ask "How many patients have diabetes?"** Point at the live steps, then at the draft
   text appearing, labelled as a draft, then at the citations and definition statuses
   arriving with the checked answer. This is the point to make: the text is early, the
   evidence is never early.
3. **Ask the follow-up "And how many of them are women?"** It shows the earlier turn is in
   the model's context, and that the follow-up ran its own query.
4. **Stop and start the service in the terminal, then reload the page.** The conversation
   is still there, tables included. Ask one more follow-up to show it continues.
5. **Open an older conversation from the sidebar**, rename it, and delete another.
6. **Drag the sidebar's edge wider and narrower, then collapse it** to give the chat the
   whole screen, and bring it back.
7. **Optionally narrow the window to phone width** to show the drawer.

Lines worth having ready:

- "Conversations are stored in a separate SQLite file. The patient database stays
  read-only."
- "The model sees the last six turns, not the whole history, so a long conversation does
  not cost more per question."
- "No new dependencies, and the evaluation is still 20 of 20."

Limits to state if asked:

- Everyone with the token sees every conversation. Accounts come later.
- Stored answers include result rows. That is fine for synthetic data and is a decision to
  make before real patient data; a setting turns it off.
- The draft arrives only once the model starts writing, a few seconds before the end.
- A reopened answer is a snapshot of the day it was given.

Screenshots for slides can be taken from the running interface: the draft state, an
answered conversation with the sidebar, and the phone-width drawer.
