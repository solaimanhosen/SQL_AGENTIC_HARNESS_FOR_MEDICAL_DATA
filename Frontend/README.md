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
| `src/app/chat/chat-store.ts` | The conversation on screen: each question, its live steps and its answer. Carries the conversation id so follow-ups work. |
| `src/app/chat/exchange-view.*` | One question and its answer: headline, findings with their query citations, caveats. |
| `src/app/chat/composer.ts` | The question box. Enter sends, Shift+Enter adds a line. |
| `src/app/chat/token-prompt.ts` | Asks for the access token when the service requires one. |
| `src/app/app.*` | The page: service status, example questions, the thread and the question box. |

## Rules worth keeping

- **Text from the service is text.** Answers can quote database content, and database
  content can carry injected instructions or markup. Everything is rendered through Angular
  interpolation, never `innerHTML`, and a test proves an injected tag is shown, not run.
- **The service decides.** The page renders what the service sends and computes nothing
  that must be exact, such as definition statuses or window dates. Those come from the
  service's own records.
- **Tests never call the network.** The API client takes an injected `fetch`, and the
  components take a fake client.
