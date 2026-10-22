# ADR 0005: A model catalog, chosen per question

- **Status:** Accepted on 2026-10-21.
- **Decision:** People choose the model and effort for each question from a short list kept
  in `sql_agent/models.py`. The service checks every choice against that list, runs the
  question on it, and records the model and effort with the answer.

## Context

Until v3.0.0 the model and effort were fixed in `.env`: Claude Opus 5 at high effort, the
setting the evaluation was measured on. The next step in the plan was to let people try other
models, as the picker on claude.ai does.

Checked against the live Models API on 21 October 2026:
- It lists 14 models.
- The six current ones accept adaptive thinking and all five effort levels: Opus 5,
  Opus 5.5, Sonnet 5.5, Sonnet 5, Haiku 5.5 and Fable 5.1.
- Opus 4.5 lacks the two highest effort levels, and Haiku 4.5 and Sonnet 4.5 have no effort
  setting at all.

Two things in the libraries constrain the design:
- langchain-anthropic 1.7.4 has no capability profile for Sonnet 5.5 or Haiku 5.5. Without
  one, LangChain's agent falls back from the API's native structured output to a tool that
  stands in for it. It also leaves thinking unset for those two models.
- The interface reads the answer's draft from the native structured output's JSON as it
  streams, so the fallback would break the draft.

## Decision

1. **A hand-kept catalog.** Each entry has an id, a label, a one-line description, the base
   prices, the effort levels offered, a default effort, whether only admins may pick it,
   and the evaluation result if there is one. The default model (`SQL_AGENT_MODEL`) must
   be in it, or the settings refuse to load.
2. **The choice belongs to the question, not the conversation.** `model` and `effort` are
   optional fields on the ask request. Left out, the defaults apply. The model may change
   between questions in one conversation, and the conversation remembers its latest
   answer's choice so a reopened one continues with it.
3. **The service decides what is allowed.** An unknown model, an effort the model does not
   offer, or an admin-only model asked for by anyone else gets a 422 before anything runs.
   Before accounts exist, nobody is an admin, so Fable 5.1 is listed but not offered.
4. **Every model runs the same way.** Adaptive thinking with summaries is sent explicitly,
   effort is always sent, and the structured answer always uses the API's native output
   (`ProviderStrategy`), whatever LangChain knows about the model.
5. **Every answer records its model and effort**, in the stored answer, the run log and the
   evaluation report. Older stored answers, which lack effort, still open.
6. **Checks.**
   - `check_setup` compares the catalog with the Models API without using tokens.
   - `check_setup --all-models` makes one tiny call to each model.
   - `evaluate --model --effort` scores any model, with its estimated cost.

## Alternatives turned down

| Alternative | Why not |
|---|---|
| Offer whatever `/v1/models` lists | Older models lack the effort levels, and some would fail with this agent; a model should be offered only after someone decided it belongs |
| Fix the model per conversation | Comparing models would need a new chat each time; claude.ai lets the model change between messages |
| Let the browser send any model id | The price and the behaviour of the service would be in the user's hands |
| Count the budget in dollars | A bigger change to the limits; noted as a risk instead, with prices in the catalog ready for it |
| Upgrade langchain-anthropic for profiles | Would fix the two models only until the next one; sending the strategy and thinking ourselves fixes it for all |

## Consequences

- Only Opus 5 at high effort has been scored on the evaluation. The picker says "Not yet
  evaluated" for every other model, until each is run.
- One short live question per model passed on 21 October 2026, and found 108 patients on
  all six models. That shows they work with the agent; it does not show they are as
  accurate.
- The daily and per-conversation budgets count tokens. A Fable 5.1 token costs 100 times a
  Haiku 5.5 input token, so a token budget is a loose bound on money when models mix.
- The prices in the catalog are for estimates people read. They must be updated by hand when
  Anthropic changes them.
