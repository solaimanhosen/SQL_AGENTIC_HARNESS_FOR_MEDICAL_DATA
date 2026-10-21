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
| Who can use it | Anyone with the one shared token | Registered users, with user and admin roles |
| Whose conversations | Everyone's, in one list | Your own only |
| Theme | Follows the operating system | System, light or dark, chosen in the header |
| Conversation address | `/#<id>` | `/c/<id>`. Old links still work |
| Column width | 52rem | 60rem, with prose held to a readable line length |
| Checks and monitoring | Command line only | Also an admin console in the browser |

## Facts checked before designing

The model list was read from the live Models API on 21 October 2026, not from memory. It
lists 14 models. These six are offered, and every one accepts adaptive thinking and all five
effort levels (`low`, `medium`, `high`, `xhigh`, `max`):

| Model | ID | Note |
|---|---|---|
| Opus 5 | `claude-opus-5` | The default, and the model the evaluation scores were measured on |
| Opus 5.5 | `claude-opus-5-5` | Thinking cannot be turned off. Its own default effort is `medium`, so we always send one |
| Sonnet 5.5 | `claude-sonnet-5-5` | |
| Sonnet 5 | `claude-sonnet-5` | |
| Haiku 5.5 | `claude-haiku-5-5` | |
| Fable 5.1 | `claude-fable-5-1` | The most capable, at twice Opus 5's price. Proposed for admins only |

The older models are left out. Opus 4.5 lacks `xhigh` and `max`, and Haiku 4.5 and Sonnet
4.5 have no effort setting at all.

## Traps found

- **LangChain does not know two of the models.** langchain-anthropic 1.7.4 has no profile
  for Sonnet 5.5 or Haiku 5.5.
  - Without one, the agent quietly switches from native structured output to a tool-based
    one.
  - That breaks the streamed draft of the answer, and may force a tool choice, which newer
    models reject.
  - Step 18 asks for native structured output explicitly.
- **A CSS class name was used twice.** The new menus use a global `.menu` class, and the
  header's sidebar button was also called `.menu`. At phone width the button stretched into
  a wide floating box. Browser checks at phone width caught it, and the button is now
  `.menu-toggle`.
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

Planned:
- A narrow rail that never moves, holding the sidebar button, New chat, Search and the
  profile.
- Search across titles and questions.
- Three collapsible sections:
  - **Pinned**: the chats the user pinned.
  - **Recents**: the five most recently used chats that are not pinned.
  - **All chats**: the rest, grouped by month.
- The sections are worked out from the list each time it changes, so each chat appears once
  and unpinning one moves it back on its own.
- Row actions move into a "⋯" menu.

### Model and effort (Step 18)

Planned:
- A catalog in `sql_agent/models.py`, edited by hand.
- `GET /api/models`.
- `model` and `effort` on each question, validated against the catalog.
- Both recorded on the answer and in the run log.
- `evaluate --model --effort`, so models can be compared later. The 23-question
  evaluation is **not** run live in this phase.

### Accounts (Steps 19 and 20)

Planned:
- **Passwords:** hashed with scrypt from the standard library, so there is no new
  dependency.
- **Sessions:** an HttpOnly, SameSite=Strict cookie, with only the token's hash stored.
- **Protection:** CSRF checks and rate-limited sign-in.
- **Isolation:** every conversation query is filtered by its owner, and another user's
  conversation answers "not found".
- **Registration:** open, and an admin can switch it off.
- **The first admin:** created from the command line.
- **Budgets:** each user gets their own daily token budget.
- The shared token is retired.
- **Profile menu:** at the top right of the header, with Account settings, Admin console
  (admins only) and Sign out.

### Admin console (Steps 21 and 22)

Planned:
- **Fixed jobs only.** The browser picks a job by name and sends no arguments, one job runs
  at a time, and output streams live and is kept as history.
- **Jobs:** connections, unit tests, semantic checks, the security catalogue and the
  dry-run evaluation.
- **Paid jobs:** the live evaluation is built but switched off by default.
- **Monitoring:** read from the request and run logs.
- **Users:** user management.

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
- The admin console can start the test suite from a browser. It runs one fixed command, and
  only for an admin session.

## Status

Work is on the branch `sql_agent/platform/dev`, cut from `main` at `004d106`.

| Step | What | Status | Commit |
|---|---|---|---|
| 16 | Design system, themes, router, icons, wider column | Done | this step's commit |
| 17 | Sidebar: rail, search, Pinned, Recents and All chats | Planned | |
| 18 | Model and effort selection | Planned | |
| 19 | Accounts: backend | Planned | |
| 20 | Accounts: interface and profile menu | Planned | |
| 21 | Admin console: backend jobs and monitoring | Planned | |
| 22 | Admin console: interface | Planned | |
| 23 | Polish, browser checks, records, merge and v4.0.0 | Planned | |

## Results

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

## Demo notes

To be written at Step 23. Things worth showing so far:
- Switching between light and dark from the header.
- Copying a conversation's address into a new tab, where it opens.
