"""The models people may choose for the agent, and how hard each may think.

The list is kept by hand, not read from the API at run time, so a model appears only after
someone has decided it belongs here. Every entry was checked against the live Models API on
21 October 2026: each accepts adaptive thinking and all five effort levels. `check_setup`
repeats that check against whatever the API says today.

Prices are USD per million tokens, from the Anthropic pricing page on the same day, at the
base rate (no caching, no batch). They are used only to estimate cost for people to read.
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    description: str
    input_price: float
    """USD per million input tokens."""
    output_price: float
    """USD per million output tokens."""
    efforts: tuple[str, ...] = VALID_EFFORTS
    default_effort: str = "high"
    admin_only: bool = False
    """Offered only to admins, for cost. Before accounts exist nobody is an admin."""
    evaluated: str | None = None
    """The evaluation result on this model, as people should read it, or None if not run."""
    refusal_fallback: bool = True
    """Whether the API accepts the server-side refusal fallback for this model."""

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimated USD for this many tokens at the base price."""
        return (input_tokens * self.input_price + output_tokens * self.output_price) / 1_000_000


CATALOG: tuple[ModelOption, ...] = (
    ModelOption(
        id="claude-opus-5",
        label="Opus 5",
        description="The default. Careful and thorough; the model the evaluation was run on.",
        input_price=5.0,
        output_price=25.0,
        evaluated="23 of 23 at high effort, 20 October 2026",
    ),
    ModelOption(
        id="claude-opus-5-5",
        label="Opus 5.5",
        description="The newest Opus, a little cheaper than Opus 5.",
        input_price=4.0,
        output_price=20.0,
    ),
    ModelOption(
        id="claude-sonnet-5-5",
        label="Sonnet 5.5",
        description="Faster and less than half the price of Opus.",
        input_price=2.0,
        output_price=10.0,
    ),
    ModelOption(
        id="claude-sonnet-5",
        label="Sonnet 5",
        description="The previous Sonnet, at the same price as Sonnet 5.5.",
        input_price=2.0,
        output_price=10.0,
    ),
    ModelOption(
        id="claude-haiku-5-5",
        label="Haiku 5.5",
        description="The fastest and cheapest. Best for simple counts and lookups.",
        input_price=0.10,
        output_price=0.50,
    ),
    ModelOption(
        id="claude-fable-5-1",
        label="Fable 5.1",
        description="The most capable, and the slowest and most expensive. Admins only.",
        input_price=10.0,
        output_price=50.0,
        admin_only=True,
    ),
)

_BY_ID = {option.id: option for option in CATALOG}


class ModelChoiceError(ValueError):
    """The model or effort asked for is not one this person may use."""


def find_model(model_id: str) -> ModelOption | None:
    return _BY_ID.get(model_id)


def available_models(*, admin: bool) -> tuple[ModelOption, ...]:
    """The models this person may pick, in the order the picker shows them."""
    return tuple(option for option in CATALOG if admin or not option.admin_only)


def resolve_choice(
    model: str | None,
    effort: str | None,
    *,
    default_model: str,
    default_effort: str,
    admin: bool,
) -> tuple[ModelOption, str]:
    """The model and effort a question will run with, or ModelChoiceError.

    A missing model means the default. A missing effort means the default effort when the
    default model is used, and otherwise that model's own default.
    """
    option = find_model(model or default_model)
    if option is None:
        raise ModelChoiceError(f"{model} is not one of the models offered here.")
    if option.admin_only and not admin:
        raise ModelChoiceError(f"{option.label} is offered to admins only.")
    if effort is None:
        effort = default_effort if option.id == default_model else option.default_effort
    if effort not in option.efforts:
        raise ModelChoiceError(f"{option.label} does not offer {effort} effort.")
    return option, effort


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated USD, or None for a model not in the catalog."""
    option = find_model(model_id)
    return None if option is None else option.cost(input_tokens, output_tokens)
