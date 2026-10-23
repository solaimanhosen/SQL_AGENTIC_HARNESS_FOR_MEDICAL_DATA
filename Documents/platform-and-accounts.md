# Models, accounts, an admin console and a new interface (Phase D)

This document records what Phase D adds, why it is built the way it is, and how far it has
got. It is updated as each step lands, and it is the source for the slides on this work.

Phase D is Steps 16 to 23:
- the interface's design system (16) and its sidebar (17);
- picking the model and effort (18);
- user accounts (19 and 20);
- an admin console (21 and 22);
- a final polish and release (23).

PostgreSQL and deployment move to Phase E, Steps 24 and 25.

## What changes, in short

- **People choose the model and how hard it thinks.** A picker in the question box offers
  six current Claude models and five effort levels. The choice can change within a
  conversation, and every answer records which model and effort produced it.
- **People have accounts.** Users register and sign in, and each sees only their own
  conversations. Admins see aggregate usage, never other people's questions.
- **Admins get a console.** It runs the test suite, the security catalogue, the semantic
  checks and connection checks from a browser, and shows requests, errors, latency, tokens
  and estimated cost.
- **The interface looks like a product.**
  - One design system with light and dark themes.
  - A sidebar with search and Pinned, Recents and All chats.
  - A wider column.
  - Proper addresses for conversations.
- **Nothing about trust changes.** The three safety layers are untouched, and every exact
  thing in an answer still comes from our own records.

## Before and after

| | v3.0.0 | Phase D |
|---|---|---|
| Model | Opus 5 at high effort, fixed in `.env` | Six models and five effort levels, chosen per question |
| Who can use it | Anyone with the one shared token | Registered users, by password or Google, with user and admin roles |
| Whose conversations | Everyone's, in one list | Your own only |
| Theme | Follows the operating system | System, light or dark, chosen in the header |
| Conversation address | `/#<id>` | `/c/<id>`. Old links still work |
| Column width | 52rem | 60rem, with prose held to a readable line length |
| Checks and monitoring | Command line only | Also an admin console in the browser |

## Facts checked before designing

The model list was read from the live Models API on 21 October 2026, not from memory. It
lists 14 models. These six are offered, and every one accepts adaptive thinking and all five
effort levels (`low`, `medium`, `high`, `xhigh`, `max`):

| Model | ID | $ per million tokens, in / out | Note |
|---|---|---|---|
| Opus 5 | `claude-opus-5` | 5 / 25 | The default, and the model the evaluation scores were measured on |
| Opus 5.5 | `claude-opus-5-5` | 4 / 20 | Thinking cannot be turned off. Its own default effort is `medium`, so we always send one |
| Sonnet 5.5 | `claude-sonnet-5-5` | 2 / 10 | |
| Sonnet 5 | `claude-sonnet-5` | 2 / 10 | |
| Haiku 5.5 | `claude-haiku-5-5` | 0.10 / 0.50 | For prompts up to 100,000 tokens; ours are about 17,000 |
| Fable 5.1 | `claude-fable-5-1` | 10 / 50 | The most capable. For admins only, because of cost |

Prices are from Anthropic's pricing page on the same day.

The older models are left out. Opus 4.5 lacks `xhigh` and `max`, and Haiku 4.5 and Sonnet
4.5 have no effort setting at all.

## Traps found

- **LangChain does not know two of the models.** langchain-anthropic 1.7.4 has no profile
  for Sonnet 5.5 or Haiku 5.5. Two things followed from that:
  - The agent would quietly switch from native structured output to a tool-based one. That
    breaks the streamed draft of the answer, and may force a tool choice, which newer
    models reject.
  - Inspecting the exact request showed a second gap: LangChain also left thinking unset
    for those two models, while Opus 5 got adaptive thinking.

  Step 18 sends both explicitly for every model, and a test checks the request for each
  model in the catalog.
- **A CSS class name was used twice.** The new menus use a global `.menu` class, and the
  header's sidebar button was also called `.menu`. At phone width the button stretched into
  a wide floating box. Browser checks at phone width caught it, and the button is now
  `.menu-toggle`.
- **The same clash, a second time.** In the row menu, the Delete item was given `.danger`,
  which is also the global red-button style. The item turned into a solid red bar with its
  text invisible. It is `.destructive` now, and the rule against reusing global class names
  is written down in CLAUDE.md and the frontend README.
- **A drawer that is still sliding in cannot take focus.** The phone drawer's `visibility`
  was transitioned, so on the first frame it was still hidden and the browser ignored
  `focus()`. It now turns visible at once when opening and hides only after sliding out.
- **The `lucide-angular` package stops at Angular 21.** Installing it here would mean
  forcing peer dependencies. The icons come from `@lucide/angular`, Lucide's newer
  standalone package, which supports Angular 17 and later.

## Design

### The design system (Step 16)

Every component now draws from one set of tokens in `Frontend/src/styles.css`. The review of
v3.0.0 found 15 different spacing values, 8 font sizes and 6 corner radii, which is the main
reason it looked hand-made.

| Tokens | Scale |
|---|---|
| Spacing | A 4px grid, `--space-1` (4px) to `--space-12` (48px) |
| Type | Inter, self-hosted, with seven sizes from 12px to 28px and two weights |
| Shape and depth | Four radii and three shadow levels, darker in the dark theme |
| Colour | Neutral greys, one blue accent, and warning, danger and success pairs, each defined for both themes |
| Layout | `--content-max` 60rem for the column, `--measure` 85ch for prose |

Supporting pieces:
- **Themes.** "System" follows the operating system. "Light" and "Dark" set `data-theme` on
  the page. A small script in `index.html` applies the saved choice before Angular starts,
  so the page never flashes the wrong theme. The choice is kept in this browser only.
- **Menus and dialogs.** Angular CDK provides keyboard handling, focus and positioning, and
  our styles provide the look. The theme menu is the first one.
- **Icons.** Lucide, as standalone SVG components. Only the icons used are bundled: the
  production bundle is 101 kB transferred.
- **Addresses.**
  - The router shows a conversation at `/c/<id>` and a new chat at `/`.
  - Both addresses share one route, so a new chat that receives its id mid-answer keeps
    its page.
  - Back and forward move between conversations, except while an answer is being written,
    when the page stays with it.
  - An unknown id returns to `/`.
- **Error messages for users.** The header no longer tells users to run a Python command
  when the service is down.

### Sidebar (Step 17)

**One toggle, one place.**
- The sidebar has three modes:
  - **full**, on a wide screen;
  - **rail**, a 56px strip with the toggle, New chat and Search;
  - **drawer**, over the page on a phone.
- The toggle is the first control in every mode, measured at exactly 10px from the left and
  top in all of them, including the phone header's button that opens the drawer.
- Collapsing no longer hides the sidebar completely, so the way back is always where it was.

**Sections** are worked out in the browser by one function, `partition`, each time the list
changes:

| Section | What it holds | Order |
|---|---|---|
| Pinned | Every pinned chat | Most recently pinned first |
| Recents | The five most recently used chats that are not pinned | Most recent first |
| All chats | Everything else | By month of last use, newest first |

- Each chat appears exactly once.
- Unpinning a chat, or using an old one, moves it to the right section with nothing else to
  keep track of. Duplicates would have needed exactly that bookkeeping.
- Each section collapses, and the choice is remembered in the browser.

**Search.**
- It runs on the service, so it finds words in any question of a conversation, not only in
  its title.
- `GET /api/conversations?q=` matches the text literally: `%` and `_` are not wildcards, and
  the search is a parameterised query.
- The box waits 250 ms after typing stops. Results from an older search never replace a
  newer one's.
- Escape clears it. Ctrl or ⌘K opens it from anywhere, expanding the rail or opening the
  drawer first.

**Row actions** sit behind a "⋯" button that fades in on hover or focus. Rows have a fixed
height, so nothing moves.
- The menu offers Pin or Unpin, Rename (inline, where Escape cancels) and Delete.
- Delete asks in a dialog that traps focus, puts it on Cancel, and quotes the title as plain
  text.

**Pinning on the service.**
- `PATCH /api/conversations/{id}` takes `{"pinned": true|false}`, a title, or both.
- Pinning keeps its first time if repeated, and does not count as use.
- When the store is full, unpinned conversations are removed before any pinned one.

**Schema versions.**
- `data/conversations.db` now records its version.
- A file written by v3.0.0 is upgraded in place when the service opens it. Each step is its
  own transaction, and nothing stored is lost.
- A file from a newer version is refused untouched, and the service will not start on it.
- Checked on a copy of the real conversations file, which came up at version 2 with every
  conversation intact.

### Model and effort (Step 18)

The design is ADR 0005.

**The catalog.**
- `sql_agent/models.py` is a short list kept by hand. Each entry has its price, effort
  levels, default effort, whether only admins may pick it, and its evaluation result.
- The default model in `.env` must be on the list, or the settings refuse to load.
- `GET /api/models` returns the list in the picker's order.

**Choosing.**
- `model` and `effort` are optional on each question. The service checks them against the
  catalog and refuses anything else with a 422 before anything runs.
- The model may change between questions. The conversation remembers its latest answer's
  choice, and a reopened conversation continues with it.
- Picking a new model keeps the effort if that model offers it.
- Fable 5.1 is admin only. Until accounts exist nobody is an admin, so it is not offered.

**Running.**
- Every model gets the same request: adaptive thinking with summaries, an explicit effort,
  the refusal fallback, and the API's native structured output.

**Recording.**
- The model and effort are kept on the stored answer, in the run log and in the evaluation
  report.
- Every answer shows them, for example "claude-haiku-5-5 at low effort".

**In the interface.**
- Two small menus sit in the question box, one for the model and one for the effort.
- The model menu gives each model's description, price per million tokens, and either its
  evaluation result or "Not yet evaluated".
- The effort menu describes each level.
- The header no longer shows a model, since it can now change between questions.

**Checks.**
- `check_setup` compares the catalog with the live Models API, at no cost.
- `--all-models` makes a two-token call to each model.
- `evaluate --model X --effort Y` scores any model and estimates the cost of the run.
- The 23-question evaluation was **not** run on the new models, as agreed.

### Accounts (Step 19)

The design is ADR 0006, and Google sign-in is ADR 0007.

**Where they live.**
- Users, sessions, pending Google sign-ins and settings live in `data/conversations.db`,
  beside the conversations, at schema version 4.
- `appdb.py` now owns that file's connection and migrations, and the conversation store
  and the account store both use it.

**Two ways in.**
- Email and password:
  - passwords are hashed with scrypt from the standard library, 12 to 128 characters;
  - a wrong password and an unknown email get the same answer;
  - failed sign-ins are throttled.
- Google, by OpenID Connect with PKCE, using `httpx`, which was already installed. Nothing
  new was added.
- Google is off until a client ID and secret are in `.env`. When it is off, the button does
  not appear.

**Sessions.**
- A 32-byte random token in an HttpOnly, SameSite=Strict cookie, sent only to `/api`, and
  over HTTPS only by default. Chrome keeps such a cookie on `http://localhost`, so local
  development needs no change.
- Only the token's hash is stored.
- A session ends after 30 idle days, after 90 days in all, on sign-out, or when the account
  is disabled.
- Page scripts cannot read it, which the browser check confirmed.

**Cross-site requests.** Anything that changes state must carry
`X-Requested-With: sql-agent`, which another site's page cannot send. Any `Origin` it names
must be ours.

**Isolation.**
- Every conversation query takes its owner.
- Another person's conversation is answered exactly like one that does not exist, for every
  route, follow-up questions included.
- The 1,000-conversation cap applies per person, so nobody's use evicts anyone else's.

**Roles.**
- `user` and `admin`. Only admins may pick Fable 5.1.
- A new chat starts on the person's own default model when they have set one.

**Budgets.** Each person has a daily token budget, 1,000,000 by default, beside the
service's own.

**The Google linking rule.**
- A Google sign-in links to an existing account only if that account's email was verified,
  by Google or by an admin.
- A self-registered password account is never linked by email. Otherwise someone could
  register a victim's address first and take the account later.

**The command line.** `python -m sql_agent.users` creates accounts and admins, lists them,
changes roles, disables, resets passwords, and opens or closes registration.
- Passwords are typed at a hidden prompt.
- `--claim-unowned` gives the conversations from before accounts to the first admin. Until
  then nobody can see them.

**In the interface.**
- Sign-in and sign-up pages built on the design system, with "Continue with Google" when it
  is on.
- A guard that sends a signed-out person to sign in and back to the conversation they
  opened.
- An avatar in the header with the person's name, email, role and Sign out.
- The token prompt is gone.

### Account page (Step 20)

The page is `/account`, opened from **Account settings** in the avatar menu. It loads only
when opened, so it adds nothing to the chat's first load (7 kB). Each section has its own
address, `?tab=`.

| Section | What it does |
|---|---|
| Profile | Change your name. Your email and role are shown; only an admin changes them |
| Security | Change your password with the current one, or set a first one on a Google-only account. Connect or disconnect Google (refused while Google is the only way in). See every signed-in browser and device by name, such as "Chrome on macOS · This device", and sign one or all of the others out |
| Preferences | The default model and effort new chats start on, kept with the account so it follows you; and the theme, kept in this browser |
| Usage | Today's tokens against your daily budget, and this month's questions, tokens and estimated cost by model |

**Smaller changes.**
- A new chat starts on your default model. Before, it kept the last one picked.
- Connecting Google from the account page comes back to the Security section, with any
  error shown as text.
- A person's daily budget is rebuilt from the stored answers. Found in the browser check:
  after a restart, Usage showed 0 tokens for a day that had spent 88,713, and the budget had
  reset too. Both now read the stored figure until the ledger has its own.
- Costs under a cent show four decimal places, so Haiku's $0.0018 does not read as $0.00.

The **Admin console** item joins the avatar menu in Step 22, with its page.

### Admin console, the service (Step 21)

The design is ADR 0008. Every route is under `/api/admin`, and needs an admin's session.

**Checks are fixed commands.** Each one is a list of arguments written in `jobs.py`, run as a
subprocess in `Backend/` without a shell. The browser names a job. The only thing it can add
is a choice from a fixed list (the live evaluation's model and effort), checked before it
becomes an argument.

| Job | What it runs | Cost |
|---|---|---|
| Unit tests | pytest, read back from its JUnit report into counts and failing test names | Free |
| Security catalogue | All 78 attack cases, and the row-count check | Free |
| Semantic layer | The catalog against the schema, and every definition's check | Free |
| Evaluation, dry run | The golden SQL of all 23 questions | Free |
| Setup and connections | `check_setup`, with one two-token call to the default model | A fraction of a cent |
| Ping every model | One two-token call to each model in the picker | About a tenth of a cent |
| Evaluation, live | The 23 questions on a chosen model and effort | Dollars; off unless `SQL_AGENT_ADMIN_LIVE_EVAL=1` |

**How a run behaves.**
- Only one runs at a time, and each has a time limit; an admin can cancel it.
- Output streams to the console line by line, and is kept with the run: up to 200,000
  characters, keeping the end.
- History lives in the application database, at schema version 5.
- A run cut short by a restart is marked interrupted.

**Monitoring.** Read from the logs the service already writes, with nothing new recorded:
- per day: requests, refusals by reason, errors, and median and 95th-percentile latency;
- questions, tokens and estimated cost by day, by model and by person.

People appear by id in the logs, and only the admin view turns ids into emails.

**People.**
- List every account with its conversations and questions this month.
- Make someone an admin or a user.
- Disable an account, which signs the person out at once.
- Give someone a temporary password, shown once, which ends all their sessions.
- An admin cannot demote or disable themselves, or remove the last enabled admin.

**Settings.** Open or close registration.

**Never shown.** An admin sees totals and accounts, never the text of anyone's
conversations.

### Admin console, the interface (Step 22)

The page is `/admin`, reached from **Admin console** in the avatar menu. Only admins see the
item, and a guard sends anyone else back to the chat. The service checks the role again on
every request. The page loads only when opened (10 kB), and each section has its own
address, `?tab=`.

| Section | What an admin sees and does |
|---|---|
| Overview | Six tiles: patient database, API key, sign-in, service uptime, people, conversations. Today's budget as a meter, and the latest run of each check |
| Checks | A card per check, with its description and cost. A free check starts at once; a paid one asks first and names the cost. The output streams in as it is written, then the verdict, the failing test names, and a cancel button while it runs. History, with each past run's kept output |
| Monitoring | Totals for 7, 14 or 30 days. Four daily charts: requests (all, refused, errors), response time (median and 95th percentile), questions, and estimated cost. Tables by model, by person and by refusal reason |
| People | Every account, with how they sign in, conversations, questions this month and when last seen. A "⋯" menu: make admin or user, disable or enable (each confirmed), set a temporary password shown once with a Copy button. Your own row cannot be changed |
| Settings | The registration switch, and what is set only in `.env`: Google sign-in and the live evaluation |

**Smaller changes.**
- The charts reuse the answer charts' component. A chart that comes from the logs rather
  than a query shows no "Query N" button.
- The account page and the console share one frame, `ui/page-shell.ts`.
- Output, test names and log values are shown as text, never as HTML.

## Decisions

- **Accounts now, not a second shared token.** The admin page needs to know who is an admin,
  and per-user conversations need users. A second token would have been thrown away.
- **Our own design system on Angular CDK, not Angular Material or Tailwind.** CDK gives
  accessible menus, dialogs and focus handling with no look of its own, so the interface
  keeps its identity and its small bundle, and the existing components stay.
- **The model may change mid-conversation.** It works as on claude.ai, and it makes
  comparing models easy. Each answer records what produced it.
- **No live evaluation runs in this phase.** A 23-question run on Opus 5 costs about $4 to
  $5. Models will be compared later, starting with the cheaper ones.

## Risks to state plainly

- Five of the six models have not been scored by the evaluation. Until they are, only Opus
  5 at high effort is known to answer all 23 questions correctly.
- Accounts bring passwords. They are hashed and never logged, but resetting one needs an
  admin, because there is no email service.
- Registration is open by default, with no email check or CAPTCHA, so one person can make
  many accounts. Each has its own budget and the service's budget caps the total, but a
  deployed instance should close registration or add verification.
- Nobody verifies a self-registered email. That is why Google never links to such an
  account.
- The admin console can start the test suite from a browser. It runs one fixed command, and
  only for an admin session.

## Status

Work is on the branch `sql_agent/platform/dev`, cut from `main` at `004d106`.

| Step | What | Status | Commit |
|---|---|---|---|
| 16 | Design system, themes, router, icons, wider column | Done | `f01a0fa` |
| 17 | Sidebar: rail, search, Pinned, Recents and All chats | Done | `93d0716`, `c0d3535` |
| 18 | Model and effort selection | Done | `9d104b8`, `7741cb6` |
| 19 | Accounts: password and Google sign-in, ownership, roles, sign-in pages | Done | `08471d3`, `0bf0cfb` |
| 20 | Account page and Account settings in the avatar menu | Done | `73fe7b6`, `a3daca8` |
| 21 | Admin console: fixed checks, monitoring, people, settings | Done | `dd2e1bd`, `da04689` |
| 22 | Admin console: the page | Done | `f5bbf01` |
| 23 | Stop, polish, browser checks, records, merge and v4.0.0 | Done | this step's commit and the merge |

Merged into `main` with `--no-ff` and tagged v4.0.0 on 21 October 2026.

## Results

### Phase D in numbers

| | v3.0.0 | v4.0.0 |
|---|---|---|
| Backend tests, no network | 375 passed, 3 skipped | 522 passed, 3 skipped |
| Interface tests, no network | 108 passed | 188 passed |
| Security catalogue | 78 of 78 | 78 of 78 |
| Evaluation | 23 of 23 on Opus 5 | Unchanged; other models not yet scored |
| Models people can choose | 1 | 5, plus Fable 5.1 for admins |
| Who can use it | Anyone with the shared token | Accounts, by password or Google, each seeing only their own |
| First load, transferred | about 100 kB | 125 kB; the account page (5 kB) and the console (10 kB) load when opened |
| New dependencies | | Angular CDK, Lucide icons, the Inter font; `httpx` listed (already installed) |
| Decision records | 0001 to 0004 | 0005 model catalog, 0006 accounts, 0007 Google sign-in, 0008 admin console |
| Live model spend during the phase | | About $0.45 (Step 18) and a fifth of a cent (Step 23) |

### Step 16

| Check | v3.0.0 | After Step 16 |
|---|---|---|
| Interface tests, no network | 108 passed | 118 passed |
| Production bundle, transferred | | 101 kB (415 kB raw) |
| Backend | Unchanged | Unchanged |

New tests cover:
- the theme service and the theme menu;
- the route matcher, which refuses anything that is not a conversation id;
- addresses: opening, reloading, an old `#` link, an unknown id, and a new chat receiving
  its id.

Checked in headless Chrome against a running service:
- light and dark themes at 1280px and 1440px;
- an opened conversation, with its chart, definitions and badges;
- a phone at 390px, with no sideways scroll at any width.

### Step 17

| Check | After Step 16 | After Step 17 |
|---|---|---|
| Backend tests, no network | 375 passed, 3 skipped | 384 passed, 3 skipped |
| Interface tests, no network | 118 passed | 130 passed |
| Security catalogue | 78 of 78 | 78 of 78 |
| Production bundle, transferred | 101 kB | 111 kB (CDK dialog and menus) |

**New backend tests:**
- a v3 file upgraded in place;
- a newer file refused untouched;
- pinning, and the order pinned and unpinned chats are evicted in;
- search in titles and questions, with `%`, `_`, quotes and backslashes matched literally;
- the PATCH and `?q=` routes, including their 422s.

**New interface tests:**
- the partition into sections;
- pin and unpin through the menu;
- renaming, and cancelling a rename with Escape;
- deleting only after the dialog;
- section collapse;
- search, including stale answers;
- Ctrl+K from the rail;
- the rail's layout.

**Checked in headless Chrome** against a copy of the real conversations file with seven
older conversations added:
- The toggle measured at (10, 10) open, as a rail, and on a phone both in the header and
  in the drawer.
- Ctrl+K from the rail expanded the sidebar with the cursor in the search box. "diabetes"
  found the two matching chats.
- The delete dialog opened with Cancel focused, and Escape closed it.
- On a phone, the drawer took focus when it opened, and Escape closed it and returned focus
  to the header button.
- No sideways scroll at 390px. Light and dark themes both checked.

### Step 18

| Check | After Step 17 | After Step 18 |
|---|---|---|
| Backend tests, no network | 384 passed, 3 skipped | 407 passed, 3 skipped |
| Interface tests, no network | 130 passed | 140 passed |
| Security catalogue | 78 of 78 | 78 of 78 |
| Models API against the catalog | | All 6 offered with every effort |

**Live check on all six models** (21 October 2026).
- One question, "How many patients are in the database?", at high effort, through the full
  agent: tools, streamed draft, checked structured answer.
- All six answered 108, with a structured answer, a streamed draft and no traceability
  warnings.
- Spent about $0.45 of the $3 approved.

| Model | Time | Tokens in / out | Cost | Note |
|---|---|---|---|---|
| Opus 5 | 6.4 s | 16,870 / 348 | $0.093 | |
| Opus 5.5 | 5.5 s | 16,864 / 330 | $0.074 | Also noted 9 deceased patients |
| Sonnet 5.5 | 4.0 s | 16,865 / 320 | $0.037 | |
| Sonnet 5 | 6.0 s | 25,590 / 364 | $0.055 | Ran two queries |
| Haiku 5.5 | 4.6 s | 16,902 / 320 | $0.002 | |
| Fable 5.1 | 4.4 s | 16,816 / 233 | $0.180 | |

This shows each model works with the agent. It does not show they are equally accurate on
harder questions: that needs `evaluate --model`.

**Checked in headless Chrome** against a running service:
- The picker started on Opus 5 at high effort.
- Choosing Haiku 5.5 and low effort, then asking, sent both. The answer read "claude-haiku-5-5
  at low effort", and the run log recorded the same.
- Opening that conversation's address restored Haiku 5.5 and low effort in the picker.
- At 390 px the two menus fit beside the send button, with no sideways scroll.

### Step 19

| Check | After Step 18 | After Step 19 |
|---|---|---|
| Backend tests, no network | 407 passed, 3 skipped | 490 passed, 3 skipped |
| Interface tests, no network | 140 passed | 152 passed |
| Security catalogue | 78 of 78 | 78 of 78 |
| New dependencies | | None (`httpx` was already installed, and is now listed) |

**New backend tests:**
- password hashing and rules;
- sessions: expiry at 30 idle and 90 days, sign-out, disabling, revoking;
- registration, sign-in, throttling, and identical answers for a wrong password and an
  unknown email;
- the cross-site check;
- a second user refused every route on the first user's conversation;
- per-owner eviction;
- per-person budgets;
- admin-only models;
- schema upgrades from v3;
- the `users` command;
- Google with a fake token endpoint:
  - the state: missing, mismatched, reused, expired;
  - each claim;
  - the linking rules, including refusing a self-registered account;
  - connecting from a signed-in account;
  - unsafe return paths.

**New interface tests:**
- sign-in and sign-up;
- a wrong password;
- a `next` that would leave the application;
- Google error codes;
- the guards;
- a 401 sending the person to sign in and back;
- the avatar menu and Sign out.

The tests found one real bug: a route guard called `inject()` after an `await`.

**Checked in headless Chrome**, against a copy of the real conversations file. It upgraded to
version 4, and the 11 older conversations were claimed by a scratch admin:
- Opening a conversation signed out went to `/login?next=/c/...`.
- A wrong password got the generic message.
- A new account started with an empty list of its own and could not pick Fable 5.1.
- Its cookie was HttpOnly, Secure and Strict, on `/api`, and the page could not read it.
- A request without the application header got a 403.
- Sign Out returned to the sign-in page.
- The admin saw the 11 older conversations and Fable 5.1.
- With placeholder Google credentials, the button appeared, and the start route redirected
  to Google with the redirect URI built from `SQL_AGENT_PUBLIC_URL`.
- No sideways scroll at 390 px, in both themes.

A live Google sign-in waits for real credentials.

### Step 20

| Check | After Step 19 | After Step 20 |
|---|---|---|
| Backend tests, no network | 490 passed, 3 skipped | 493 passed, 3 skipped |
| Interface tests, no network | 152 passed | 166 passed |
| Production bundle, first load | 120 kB transferred | 124 kB, with the account page loaded separately |

**New tests:**
- the usage route: totals, per-model costs, and nothing seen by another person;
- a restart that must not reset a person's budget;
- the return to Security after a failed Google connection;
- every section of the account page:
  - saving a name;
  - a password change refused without the current password or with mismatched new ones;
  - a Google-only account setting its first password;
  - the Google link, and its absence;
  - error codes;
  - devices and signing one out;
  - saving a default model and effort;
  - the theme;
  - usage figures;
- the device names;
- cost formatting;
- a new chat starting on the default.

**Checked in headless Chrome** against the scratch service:
- the avatar menu, and every section;
- saving Haiku 5.5 at low effort as the default, after which a new chat started on it;
- Usage after a restart, showing today's 88,713 tokens;
- sign-in returning to `/account?tab=usage`;
- no sideways scroll at 390 px.

### Step 21

| Check | After Step 20 | After Step 21 |
|---|---|---|
| Backend tests, no network | 493 passed, 3 skipped | 519 passed, 3 skipped |
| Security catalogue | 78 of 78 | 78 of 78 |

**New tests:**
- **The runner, with stand-in jobs:** output and verdicts, failures, a time limit, one at a
  time, cancelling, the fixed choices (an injected `green; rm -rf /` is refused), history,
  runs interrupted by a restart, and long output keeping its end without skipping a line
  as it streams.
- **The pytest summary.**
- **Every real job:** a fixed command, and the live evaluation off by default.
- **Metrics from sample logs.**
- **The routes:**
  - users get 403 and signed-out requests get 401 everywhere;
  - the overview;
  - metrics naming people only for admins;
  - a run started, streamed and kept;
  - a second run refused while one runs;
  - unknown jobs and runs;
  - the application header;
  - managing people, including the temporary password;
  - an admin unable to lock themselves out;
  - closing registration.

**The real checks**, run through a live service by an admin over its API:

| Job | Result | Time |
|---|---|---|
| Semantic layer | 17 of 17 checks passed | 0.3 s |
| Evaluation, dry run | Golden answers verified for 23 questions | 2.3 s |
| Security catalogue | 78 of 78, row counts unchanged | 61.8 s |
| Unit tests | 519 passed, 0 failed, 3 skipped | 19.8 s |

The two paid connection checks run the same `check_setup` commands verified live in Step 18,
and were not run again.

### Step 22

| Check | After Step 21 | After Step 22 |
|---|---|---|
| Interface tests, no network | 166 passed | 180 passed |
| Production bundle, first load | 124 kB transferred | 123 kB; the console loads separately (10 kB) |

**New tests:**
- the guard, and the menu item shown only to admins;
- the sections;
- the overview's tiles, meter and checks;
- a check run with output containing `<img onerror>` shown as text, then its verdict and
  failing tests;
- a paid check started only after confirming;
- a past run's output;
- the four charts built from the right figures, citing no query;
- the period switch;
- people:
  - finding someone;
  - your own row protected;
  - making an admin;
  - a temporary password shown once;
- closing registration;
- formatting.

**Checked in headless Chrome** against the scratch service:
- The scratch admin signed in at `/login?next=/admin` and reached the console.
- A plain user sent to `/admin` landed back in the chat.
- The semantic check ran from its card. Its 25 lines streamed in, ending in "17 of 17 checks
  passed."
- The paid "Setup and connections" check asked first, naming its cost, and was cancelled.

**Fixed after the browser check:**
- **Phone width.** The People page scrolled sideways by 545px and Checks by 165px:
  - a visually hidden column heading escaped its scroll box;
  - a long cost label did not wrap.

  Both now fit at 390px, as do Overview and Monitoring.
- **People table at desktop width.** It was wider than its column, which hid each row's
  menu. Sign-in methods moved under the email, and "last seen" shows the date only, with
  the time on hover.

### Step 23

**Stop.**
- While an answer is written, the send button becomes Stop.
- The service checks at every step of the agent and every piece of streamed text. Once Stop
  is pressed, it ends the run, which closes the model's stream, so nothing more is generated
  or paid for, and nothing is saved for that question.
- Pressed before the conversation has an id, the page simply stops following the stream.
- Tested live on Haiku 5.5: pressed after the first step, the question ended 5.4 seconds
  later, with nothing in the run log.

**Polish.**
- The question box grows with its text up to 192 px.
- Loading placeholders replace "no conversations" while the list loads, and the thread
  while a conversation opens.
- Failures that happen out of sight show as toasts: a rename, a pin, a delete or an opening
  that failed.
- Each question is a heading, so the answer's sections sit under it.
- A finished or stopped answer is announced to screen readers.
- The SQL panel keeps its keyboard focus ring.

**The final browser pass:**
- Six pages (new chat, a stored answer, Security, Checks, People, Monitoring) at 360, 768,
  1280 and 1920 px, in light and dark.
- One sideways scroll was found and fixed: Monitoring at 360 px, where a chart column's
  minimum was wider than the screen.
- Sign-in and sign-up were checked at phone width.
- 37 screenshots for the slides are in `presentation-local/phase-d-screenshots/`, which git
  ignores.

| Check | After Step 22 | After Step 23 |
|---|---|---|
| Backend tests, no network | 519 passed, 3 skipped | 522 passed, 3 skipped |
| Interface tests, no network | 180 passed | 188 passed |

## After v4.0.0: password reset by email

Built on 22 October 2026 on `sql_agent/email/dev`, to close the second open item. The design
is ADR 0009.

- **Forgot password.** "Forgot password?" on the sign-in page asks for an email and always
  answers the same way. If an account uses it, a link arrives that works once, for 30
  minutes. Choosing a new password there signs out every browser on the account.
- **Confirming an email.** Signing up sends a confirmation link. Until it is opened, the
  account page shows a reminder with a button to send another. Confirming is optional; it
  lets Google sign-in reach the account by its email.
- **Any provider.** Mail goes over plain SMTP from five settings in `Backend/.env`, so Gmail
  with an app password works today (free, no domain), and Brevo, Resend or Amazon SES on a
  domain later, with no code change. With the settings empty, email is off and the link is
  not shown.
- **Checks.** `python -m sql_agent.mailer ADDRESS` sends a test message. `check_setup` signs
  in to the mail server, and the console's overview and the startup line say whether email
  is on.

| Check | v4.0.0 | With email links |
|---|---|---|
| Backend tests, no network | 522 passed, 3 skipped | 558 passed, 3 skipped |
| Interface tests, no network | 188 passed | 202 passed |
| Security catalogue | 78 of 78 | 78 of 78 |
| Application database schema | 5 | 6, with `email_tokens` |
| First load, transferred | 125 kB | 128 kB; the three new pages (3 kB) load when opened |

In headless Chrome, against a scratch service whose mailer wrote to a file instead of
sending:
- Signing up sent a confirmation link, and the account page showed the reminder.
- Opening the link confirmed the email, removed the token from the address, and the
  reminder went away.
- A reset link changed the password, signed out a second browser, and refused a second use.
- No page scrolled sideways at 360 or 1280 pixels, in either theme.

## Open items

- **Google sign-in has not been tried with a real Google account.**
  - The whole flow is tested against a fake Google, and the redirect to Google was checked
    in a browser.
  - A live sign-in waits for an OAuth client in Google Cloud Console.
- **Email has not been sent through a real mail server yet.**
  - Everything is tested with a stand-in mailer, and the flow was checked in a browser.
  - A live check waits for a mailbox and its app password in `Backend/.env`. Until then a
    forgotten password is reset by an admin, from the command line or the console.

## Demo notes

A suggested order, about seven minutes. Before the demo, have the following ready:
- the admin signed in, in the main window;
- one stored conversation with a chart;
- a private window for a second person.

1. **The interface.**
   - Open the app in light mode, then switch to dark from the header.
   - Collapse the sidebar to the rail and back: the toggle does not move.
   - Press Ctrl+K and search for a word from a follow-up question. Pin the result, and it
     moves to Pinned.
2. **Choose the model.**
   - Ask "How many patients have diabetes?" on Haiku 5.5 at low effort, then again on
     Opus 5 at high effort.
   - Compare the two meta lines: time, tokens and model.
   - Open the model menu and point at the prices and "Not yet evaluated": the picker says
     plainly which models have been scored.
3. **Stop.** Ask a long question and press Stop after the first step. The answer ends, and
   nothing is saved or spent after that point.
4. **Accounts.**
   - In the private window, sign up as a new person: an empty sidebar, and no Fable 5.1 in
     the picker.
   - Paste the admin's conversation address there: "not found".
   - Open Account settings: devices, default model, usage this month with its estimated
     cost.
5. **The admin console.**
   - Overview: everything up, today's budget, the latest checks.
   - Run "Semantic layer" and watch its output arrive.
   - Start "Setup and connections" to show that a paid check asks first, then cancel.
   - Monitoring: the demo's own requests, refusals and the cost of the questions just
     asked.
   - People: a role, and a temporary password shown once.

Lines worth having ready:
- "Every model gets the same request, and the service refuses any model or effort it does
  not list."
- "Each person sees only their own conversations; someone else's answers 'not found', as if
  it did not exist."
- "The admin console runs fixed checks only. Nothing typed in the browser becomes a
  command."
- "Admins see totals and accounts, never anyone's questions."

Limits to state if asked:
- Only Opus 5 has been scored on the evaluation.
- Google sign-in has not been tried with a real Google account yet.
- Password resets go through an admin until there is an email service.
- Registration is open by default and should be closed before the service is reachable
  from the internet.
