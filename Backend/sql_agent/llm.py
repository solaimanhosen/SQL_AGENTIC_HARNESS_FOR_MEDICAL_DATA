"""Factory for the Claude chat model used by the agent (see Documents/decisions/0001)."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from .config import Settings
from .models import find_model

# If Claude's safety classifiers decline a request, the API re-runs it on a fallback
# model inside the same call instead of returning an empty refusal. "default" lets
# Anthropic pick the fallback by refusal category, so no model list needs maintaining.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"


# Sent to every model, so they all think the same way. langchain-anthropic sets this itself
# only for models it has a profile for, and in 1.7.4 Sonnet 5.5 and Haiku 5.5 have none.
ADAPTIVE_THINKING = {"type": "adaptive", "display": "summarized"}


def build_chat_model(settings: Settings, *, model: str | None = None, effort: str | None = None) -> ChatAnthropic:
    """Return a ChatAnthropic client for one run.

    `model` and `effort` are the choice for this question; either left out falls back to
    the settings, which hold the defaults. They should already have been checked against the
    catalog (models.resolve_choice).

    max_tokens is always explicit. Left unset, langchain-anthropic would request the
    model's full 128K output cap, which is too large for non-streaming calls.
    """
    model = model or settings.model
    option = find_model(model)
    kwargs: dict = {}
    if settings.refusal_fallback and (option is None or option.refusal_fallback):
        kwargs["betas"] = [REFUSAL_FALLBACK_BETA]
        kwargs["model_kwargs"] = {"fallbacks": "default"}

    return ChatAnthropic(
        model=model,
        max_tokens=settings.max_tokens,
        reasoning_effort=effort or settings.effort,
        thinking=ADAPTIVE_THINKING,
        **kwargs,
    )
