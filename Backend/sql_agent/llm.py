"""Factory for the Claude chat model used by the agent (see docs/decisions/0001)."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from .config import Settings

# If Claude's safety classifiers decline a request, the API re-runs it on a fallback
# model inside the same call instead of returning an empty refusal. "default" lets
# Anthropic pick the fallback by refusal category, so no model list needs maintaining.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def build_chat_model(settings: Settings) -> ChatAnthropic:
    """Return a ChatAnthropic client configured from settings.

    max_tokens is always explicit. Left unset, langchain-anthropic would request the
    model's full 128K output cap, which is too large for non-streaming calls.
    Thinking is not set here: on Opus 5 the wrapper defaults to adaptive thinking
    with summarized reasoning, which the transparency features will surface later.
    """
    kwargs: dict = {}
    if settings.refusal_fallback:
        kwargs["betas"] = [REFUSAL_FALLBACK_BETA]
        kwargs["model_kwargs"] = {"fallbacks": "default"}

    return ChatAnthropic(
        model=settings.model,
        max_tokens=settings.max_tokens,
        reasoning_effort=settings.effort,
        **kwargs,
    )
