"""The agent: a question in plain language becomes an explained answer.

This module is the reusable core. The command line in main.py is a thin wrapper around it,
and a web service can call the same `answer` method later without changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

import anthropic
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from .answer import AnswerIssues, StructuredAnswer, check_answer, render_answer
from .config import Settings, load_settings
from .db import ReadOnlyDatabase
from .llm import build_chat_model
from .prompts import build_system_prompt
from .semantic import SemanticLayer, load_semantic_layer, resolve_as_of_date
from .tools import QueryRecord, ToolBox

# How many model and tool turns one question may take before it is stopped.
DEFAULT_MAX_STEPS = 30


class AgentError(RuntimeError):
    """The agent could not produce an answer."""


def describe_failure(exc: BaseException) -> tuple[str, str] | None:
    """A kind and a message for a failure worth explaining, or None for anything else.

    The command line and the HTTP service both use this, so a failure reads the same in
    each. The kinds are agent, auth, api and connection.
    """
    if isinstance(exc, AgentError):
        return "agent", str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "auth", "The API key was rejected. Check ANTHROPIC_API_KEY in Backend/.env."
    if isinstance(exc, anthropic.APIStatusError):
        return "api", f"The Anthropic API returned an error: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection", "Could not reach the Anthropic API. Check the network connection."
    return None


@dataclass(frozen=True)
class AgentResult:
    question: str
    answer: str
    """The rendered answer. The exact parts come from our own records, not from prose."""
    structured: StructuredAnswer | None
    issues: AnswerIssues
    queries: tuple[QueryRecord, ...]
    as_of: date
    model: str
    elapsed_s: float
    input_tokens: int
    output_tokens: int

    @property
    def successful_queries(self) -> tuple[QueryRecord, ...]:
        return tuple(record for record in self.queries if record.ok)


class SqlAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        db: ReadOnlyDatabase | None = None,
        layer: SemanticLayer | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self.settings = settings or load_settings()
        self.db = db or ReadOnlyDatabase.from_settings(self.settings)
        self.layer = layer or load_semantic_layer()
        self.as_of = resolve_as_of_date(self.settings, self.db)
        self.max_steps = max_steps
        self.system_prompt = build_system_prompt(self.layer, self.as_of, max_rows=self.db.max_rows)

    def answer(self, question: str, *, on_event: Callable[[str, str], None] | None = None) -> AgentResult:
        """Answer one question, recording every query that ran along the way."""
        question = (question or "").strip()
        if not question:
            raise AgentError("Ask a question.")

        toolbox = ToolBox(db=self.db, layer=self.layer, as_of=self.as_of, on_event=on_event)
        agent = create_agent(
            build_chat_model(self.settings),
            toolbox.tools(),
            system_prompt=self.system_prompt,
            response_format=StructuredAnswer,
        )

        started = time.perf_counter()
        try:
            state = agent.invoke(
                {"messages": [{"role": "user", "content": question}]},
                config={"recursion_limit": self.max_steps},
            )
        except GraphRecursionError:
            raise AgentError(
                f"The agent was still working after {self.max_steps} steps and was stopped. "
                "Try asking a narrower question."
            ) from None

        messages = state.get("messages", [])
        queries = tuple(toolbox.queries)
        structured = state.get("structured_response")
        if isinstance(structured, StructuredAnswer):
            issues = check_answer(structured, queries, self.layer, as_of=self.as_of)
            answer_text = render_answer(structured, queries, self.layer, as_of=self.as_of)
        else:
            # The model answered in prose instead of filling in the schema. Rare, but the
            # answer is still worth returning rather than failing the whole run.
            structured, issues = None, AnswerIssues()
            answer_text = _final_text(messages)
        if not answer_text:
            raise AgentError("The model finished without writing an answer.")

        input_tokens, output_tokens = _token_totals(messages)
        return AgentResult(
            question=question,
            answer=answer_text,
            structured=structured,
            issues=issues,
            queries=queries,
            as_of=self.as_of,
            model=self.settings.model,
            elapsed_s=time.perf_counter() - started,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _final_text(messages: list) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai":
            text = (getattr(message, "text", "") or "").strip()
            if text:
                return text
    return ""


def _token_totals(messages: list) -> tuple[int, int]:
    input_tokens = output_tokens = 0
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if usage:
            input_tokens += usage.get("input_tokens", 0)
            output_tokens += usage.get("output_tokens", 0)
    return input_tokens, output_tokens
