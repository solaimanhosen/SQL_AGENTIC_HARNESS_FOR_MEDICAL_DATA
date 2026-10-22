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
web server. If the service is not running, the header says so.

You sign in with an account; make the first one with
`python -m sql_agent.users create you@example.org --admin --claim-unowned` from `Backend/`,
or create one on the sign-up page. The session is an HttpOnly cookie the page cannot read.
When it ends, the page sends you to sign in and back to where you were.

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
| `src/app/api/agent-api.ts` | Calls the service. Reads `/api/ask/stream` with `fetch`, because the browser's `EventSource` cannot send a POST. Sends `X-Requested-With: sql-agent` on every request, and reports a 401 so the page can send the person to sign in. |
| `src/app/api/sse.ts` | Parses server-sent events from text chunks that can split anywhere. |
| `src/app/chat/chat-store.ts` | The conversation on screen and the list of stored ones: each question, its live steps, its draft and its answer. Opens, renames and deletes stored conversations, and fetches an answer from the service if only the stream was lost. |
| `src/app/chat/sidebar.*` | The conversation list, in three modes: full, a rail of icons when collapsed, and a drawer at phone width. Its toggle stays at the same top-left spot in all of them. New chat, search (Ctrl or ⌘K), the Pinned, Recents and All chats sections, and a "⋯" menu per row to pin, rename or delete. |
| `src/app/chat/sections.ts` | Splits the list into Pinned, the five most recent other chats, and the rest by month. Each chat lands in exactly one section. |
| `src/app/ui/confirm-dialog.ts` | The confirmation dialog, on the CDK dialog: focus trapped, Escape cancels, Cancel focused first. |
| `src/app/sidebar-layout.ts` | The sidebar's width limits, and remembering its width and collapsed state in local storage. |
| `src/app/chat/exchange-view.*` | One question and what became of it: the live steps, the answer as a draft while it is written, then the checked answer or the failure. |
| `src/app/chat/answer-view.*` | The answer and everything behind it: findings with clickable query citations, time window, definitions with their status, assumptions, caveats, traceability warnings, and what the run cost. |
| `src/app/chat/query-list.*` | The SQL that ran, numbered as the findings cite it, with failed attempts kept apart. An analysis is labelled with what was computed and what it found. |
| `src/app/chat/chart-view.*` | One chart as SVG: bars or lines, a legend for several series, and a readout from the pointer or the arrow keys. Its "Query N" button opens the query it was drawn from. |
| `src/app/chat/chart-scale.ts` | A chart's geometry: value range, round ticks, bar and line positions, label thinning. The report's charts in the backend follow the same rules. |
| `src/app/chat/result-table.ts` | The rows one query returned. |
| `src/app/chat/export.ts` | CSV and JSON building, file names, and the download and clipboard helpers. |
| `src/app/chat/step-log.ts` | Every step the agent took, with the SQL of each query, live and afterwards. |
| `src/app/chat/composer.ts` | The question box. Enter sends, Shift+Enter adds a line. |
| `src/app/chat/model-picker.ts` | Two menus in the question box: the model, with its price and evaluation status, and the effort. The choice applies to the next question; a reopened conversation continues on its latest answer's model. |
| `src/app/auth/auth.ts` | Who is signed in, the guards for the chat and the sign-in pages, and the messages for Google sign-in codes. |
| `src/app/auth/auth-page.ts` | Sign in and create an account: email and password, and "Continue with Google" when the service offers it. |
| `src/app/ui/profile-menu.ts` | The avatar in the header: who is signed in, Account settings, and Sign out. |
| `src/app/admin/` | The admin console at `/admin?tab=`, for admins only and loaded only when opened: Overview (status tiles, today's budget, latest checks), Checks (run each fixed check, follow its output live, history), Monitoring (four daily charts from the logs, by model, by person, refusals), People (roles, disabling, temporary passwords), Settings (registration). Output and log text are shown as text, never HTML. |
| `src/app/ui/page-shell.ts` | The frame shared by the account page and the admin console: back to the chat, a list of sections, the content. |
| `src/app/account/` | The account page, loaded only when opened, at `/account?tab=`: Profile (name), Security (password, Google, signed-in devices), Preferences (default model and effort, theme), Usage (today against the budget, this month by model). |
| `src/app/app.ts`, `app.routes.ts`, `app.config.ts` | The root, which is only a router outlet, and the routes: `/` is a new chat and `/c/<id>` a stored one, matched by one route so the page is kept when a new chat gets its id. Old `/#<id>` links are moved to the new address. |
| `src/app/chat/chat-page.*` | The chat screen: sidebar with its draggable edge, the header with service status and the theme menu, example questions, the thread and the question box. Keeps the address and the conversation on screen in step. |
| `src/app/ui/theme.ts`, `theme-toggle.ts` | System, light or dark. The choice is kept in this browser; `index.html` applies it before the app starts. |
| `src/styles.css` | The design tokens (spacing, type, radii, shadows, colours for both themes) and the shared controls: buttons, fields, cards, chips and menus. |

## What an answer shows

Everything the command line prints is on the page, and nothing more exact than the service
sent:

- the headline and findings, where each "Query N" opens the SQL panel at that query;
- any charts, with values the service read from the query each one cites;
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
- **Download report (HTML).** The answer as one self-contained file, with its charts,
  definitions, SQL and rows, which opens with no network. The service makes it from the
  stored answer.

Files are named after the conversation and the question, such as
`5d6b7095-turn1-query1.csv`. The CSV and JSON files are built in the browser, so nothing
extra is sent anywhere; the report is fetched from the service.

## Rules worth keeping

- **Use the tokens.** Spacing, font sizes, radii, shadows and colours come from the variables
  in `src/styles.css`, never raw values, so the whole interface stays on one scale and both
  themes work. A new colour needs a value for each theme.
- **Global class names are shared.** `.menu`, `.menu-item`, `.chip`, `.card`, `.field` and the
  button classes (`.secondary`, `.ghost`, `.icon`, `.tool`, `.danger`) are defined once in
  `styles.css`. Do not reuse those names for something else in a component.

- **Text from the service is text.** Answers can quote database content, and database
  content can carry injected instructions or markup. Everything is rendered through Angular
  interpolation, never `innerHTML`, and a test proves an injected tag is shown, not run.
- **The service decides.** The page renders what the service sends and computes nothing
  that must be exact, such as definition statuses or window dates. Those come from the
  service's own records.
- **Tests never call the network.** The API client takes an injected `fetch`, and the
  components take a fake client.
