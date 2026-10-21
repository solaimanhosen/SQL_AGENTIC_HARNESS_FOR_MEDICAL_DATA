# ADR 0001: Agent framework and model

- **Status:** Accepted on 2026-09-19. To be reviewed with Telligen mentors.
- **Decision:** LangChain `create_agent` with Claude Opus 5 through `langchain-anthropic`.

## Context

The project brief asks us to extend a mature open-source agent harness rather than build agent
infrastructure from scratch. The agent answers natural-language questions over a SQLite database,
must be read-only by construction, and must show its reasoning and evidence. A web interface in
Angular will call the same backend later.

These requirements drove the choice:

1. **Multi-step tool loop.** The agent lists tables, reads schemas, runs queries, checks results and retries.
2. **We own tool execution.** Read-only enforcement must live in our code, not in the model's good behavior.
3. **Transparency.** Every query and intermediate result must be capturable and shown to the user.
4. **Web phase needs.** Streaming, conversation memory and optional human approval of queries.
5. **Portability.** A path from SQLite to PostgreSQL, and freedom to change the model later.
6. **Team fit.** Maturity, documentation, and a learning curve a student team can manage.

## Options considered

This is an initial assessment from documentation and the project's needs, not from hands-on spikes
of every option. We can run spikes if the mentors want a deeper comparison.

| Option | Strengths for this project | Main drawback for this project |
|---|---|---|
| **LangChain `create_agent`** (runs on LangGraph) | The official SQL agent tutorial matches our use case. Middleware for human approval and summarization, checkpointers for memory, event streaming. Works with many model providers. | Fast-moving API. We pin versions and test the exact request body. |
| **Claude Agent SDK** | Complete harness from Claude Code: agent loop, hooks, subagents, MCP. | Built around file, shell and web tools that we would have to disable to be read-only. Supports Claude models only. |
| **Anthropic Python SDK only** (manual loop or tool runner) | Thinnest layer and full control. | We would build memory, streaming, approval and retries ourselves, which the brief asks us to avoid. |
| **LlamaIndex** | Strong retrieval tooling and text-to-SQL query engines. | Best known for document retrieval. Less guidance for a multi-step, audited SQL agent. |
| **Vanna** | Purpose-built text-to-SQL that learns from example question and SQL pairs. | Centered on generating SQL for a question, less on multi-step analysis with Python tools and reports. We may reuse its example-retrieval idea in the semantic layer. |
| **PydanticAI** | Clean, strongly typed agent framework. | Smaller ecosystem and fewer SQL agent examples than LangChain. |

## Decision

- **Harness:** LangChain `create_agent`, following the pattern of the LangChain SQL agent tutorial.
- **Model:** Claude Opus 5 (`claude-opus-5`) through `ChatAnthropic`, set by `SQL_AGENT_MODEL`.
- **Reasoning:** effort `high` by default. Opus 5 uses adaptive thinking, and the wrapper asks for
  summarized reasoning, which the transparency features will show.
- **Output limit:** `max_tokens` is always set explicitly, 16,000 by default. Left unset, the wrapper
  would request the full 128K output cap, which is too large for non-streaming calls.
- **Refusal fallback:** on by default. If Claude's safety classifiers decline a request, the API
  re-runs it on a fallback model in the same call. Turn it off with `SQL_AGENT_REFUSAL_FALLBACK=false`.
- **Tools:** our own Python functions over a guarded, read-only SQLite connection, not LangChain's
  generic SQL toolkit. This keeps validation, blocking of identity columns, and logging in our hands.

## Consequences

- Library versions are pinned in `Backend/requirements.lock`. A unit test asserts the exact request
  body we send, so an upgrade that changes it fails in tests rather than at runtime.
- Changing the model or provider only touches `Backend/sql_agent/llm.py` and settings.
- Opus 5 costs $5 per million input tokens and $25 per million output tokens. The evaluation harness
  will measure cost per question. Lowering effort is the first cost lever before changing models.
- Revisit this decision if LangChain API churn costs more than it saves, or if we need a capability
  it cannot provide.
