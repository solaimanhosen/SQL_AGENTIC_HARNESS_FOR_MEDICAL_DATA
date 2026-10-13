# Frontend

The chat interface for the SQL agent, in Angular 22 and TypeScript. It calls the backend
service in `Backend/`, which does all the work: this folder only asks questions and shows
the answers.

## Running it

You need Node 22.22 or later, or 24.15 or later. The Angular CLI comes with the project,
so nothing is installed globally.

```bash
npm install                                   # once, from this folder
npm start                                     # http://localhost:4200
```

The interface needs the backend service running beside it. In another terminal:

```bash
cd ../Backend
.venv/bin/python -m sql_agent.serve           # http://127.0.0.1:8000
```

The development server forwards every `/api` request to the service
(`proxy.conf.json`), so the browser sees one origin, just as it would behind a production
web server. If the service is not running, the header says so and explains how to start it.

If the service was started with `SQL_AGENT_API_TOKEN`, the page asks for the token after
the first refusal. It keeps the token in memory until the page is closed or reloaded, and
never writes it to browser storage.

## Commands

```bash
npm start                                     # development server with live reload
npm test -- --watch=false                     # unit tests (Vitest), no browser or network
npm run build                                 # production build into dist/
npx prettier --write "src/**/*.{ts,html,css}" # format
```

## How it fits together

| Path | What it does |
|---|---|
| `src/app/api/types.ts` | The shapes the service returns. The service's `/docs` page is the reference. |
| `src/app/api/agent-api.ts` | Calls the service. Reads `/api/ask/stream` with `fetch`, because the browser's `EventSource` cannot send a POST or a token. |
| `src/app/api/sse.ts` | Parses server-sent events from text chunks that can split anywhere. |
| `src/app/chat/chat-store.ts` | The conversation on screen and the list of stored ones: each question, its live steps, its draft and its answer. Opens, renames and deletes stored conversations, and fetches an answer from the service if only the stream was lost. |
| `src/app/chat/sidebar.*` | The conversation list: new chat, reopen, rename, delete. A drawer at phone width. |
| `src/app/chat/exchange-view.*` | One question and what became of it: the live steps, the answer as a draft while it is written, then the checked answer or the failure. |
| `src/app/chat/answer-view.*` | The answer and everything behind it: findings with clickable query citations, time window, definitions with their status, assumptions, caveats, traceability warnings, and what the run cost. |
| `src/app/chat/query-list.*` | The SQL that ran, numbered as the findings cite it, with failed attempts kept apart. |
| `src/app/chat/result-table.ts` | The rows one query returned. |
| `src/app/chat/export.ts` | CSV and JSON building, file names, and the download and clipboard helpers. |
| `src/app/chat/step-log.ts` | Every step the agent took, with the SQL of each query, live and afterwards. |
| `src/app/chat/composer.ts` | The question box. Enter sends, Shift+Enter adds a line. |
| `src/app/chat/token-prompt.ts` | Asks for the access token when the service requires one. |
| `src/app/app.*` | The page: sidebar, service status, example questions, the thread and the question box. Keeps the open conversation's id in the address, so a reload returns to it. |

## What an answer shows

Everything the command line prints is on the page, and nothing more exact than the service
sent:

- the headline and findings, where each "Query N" opens the SQL panel at that query;
- the time window with its dates, and the as-of date;
- each definition with its status: confirmed, assumed, or not a shared definition;
- assumptions and caveats;
- traceability warnings, spelled out one by one;
- the SQL that produced the answer, and any failed attempts with their errors;
- the steps the agent took, and the queries, time and tokens the run used.

## Taking the evidence away

- **Result tables.** Each query shows the rows it returned, the first ten at once and the
  rest on request. The service keeps at most its row limit, and says when more matched.
- **Copy SQL.** One click per query, to rerun it elsewhere.
- **Download rows (CSV).** One file per query, readable by a spreadsheet. Text that a
  spreadsheet would run as a formula is defused with a leading apostrophe, since stored
  text is untrusted.
- **Download answer (JSON).** The whole answer as the service sent it: findings,
  definitions, warnings, SQL and rows.

Files are named after the conversation and the question, such as
`5d6b7095-turn1-query1.csv`. They are built in the browser, so nothing extra is sent
anywhere.

## Rules worth keeping

- **Text from the service is text.** Answers can quote database content, and database
  content can carry injected instructions or markup. Everything is rendered through Angular
  interpolation, never `innerHTML`, and a test proves an injected tag is shown, not run.
- **The service decides.** The page renders what the service sends and computes nothing
  that must be exact, such as definition statuses or window dates. Those come from the
  service's own records.
- **Tests never call the network.** The API client takes an injected `fetch`, and the
  components take a fake client.
