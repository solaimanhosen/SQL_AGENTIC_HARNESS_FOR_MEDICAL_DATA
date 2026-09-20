"""The agent: a question in plain language becomes an explained answer.

This module is the reusable core. The command line in main.py is a thin wrapper around it,
and a web service can call the same `answer` method later without changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

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


@dataclass(frozen=True)
class AgentResult:
    question: str
    answer: str
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
        agent = create_agent(build_chat_model(self.settings), toolbox.tools(), system_prompt=self.system_prompt)

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
        answer_text = _final_text(messages)
        if not answer_text:
            raise AgentError("The model finished without writing an answer.")

        input_tokens, output_tokens = _token_totals(messages)
        return AgentResult(
            question=question,
            answer=answer_text,
            queries=tuple(toolbox.queries),
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
