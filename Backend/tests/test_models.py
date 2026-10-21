import pytest

from sql_agent.config import DEFAULT_EFFORT, DEFAULT_MODEL
from sql_agent.models import (
    CATALOG,
    VALID_EFFORTS,
    ModelChoiceError,
    available_models,
    estimate_cost,
    find_model,
    resolve_choice,
)


def _resolve(model=None, effort=None, *, admin=False):
    return resolve_choice(model, effort, default_model=DEFAULT_MODEL, default_effort=DEFAULT_EFFORT, admin=admin)


def test_the_catalog_is_well_formed():
    ids = [option.id for option in CATALOG]
    assert len(ids) == len(set(ids))
    assert CATALOG[0].id == DEFAULT_MODEL, "the default comes first in the picker"
    for option in CATALOG:
        assert option.efforts and set(option.efforts) <= set(VALID_EFFORTS)
        assert option.default_effort in option.efforts
        assert option.input_price > 0 and option.output_price > option.input_price
        assert option.id.startswith("claude-") and not option.id[-8:].isdigit(), "no dated snapshot ids"


def test_nothing_chosen_means_the_default_model_at_the_configured_effort():
    option, effort = _resolve()
    assert (option.id, effort) == (DEFAULT_MODEL, DEFAULT_EFFORT)


def test_a_choice_is_kept_and_a_missing_effort_takes_the_model_s_own_default():
    assert _resolve("claude-haiku-5-5", "low")[1] == "low"
    option, effort = _resolve("claude-sonnet-5-5")
    assert option.id == "claude-sonnet-5-5" and effort == option.default_effort


@pytest.mark.parametrize("model,effort", [("claude-2", None), ("", "high"), ("claude-opus-5", "extreme")])
def test_anything_not_offered_is_refused(model, effort):
    with pytest.raises(ModelChoiceError):
        _resolve(model or "nope", effort)


def test_admin_only_models_are_hidden_and_refused_for_everyone_else():
    fable = find_model("claude-fable-5-1")
    assert fable is not None and fable.admin_only
    assert fable not in available_models(admin=False)
    assert fable in available_models(admin=True)
    with pytest.raises(ModelChoiceError, match="admins only"):
        _resolve("claude-fable-5-1")
    assert _resolve("claude-fable-5-1", admin=True)[0] is fable


def test_cost_is_estimated_at_the_base_price():
    assert estimate_cost("claude-opus-5", 1_000_000, 100_000) == pytest.approx(5.0 + 2.5)
    assert estimate_cost("claude-haiku-5-5", 30_000, 1_000) == pytest.approx(0.0035)
    assert estimate_cost("claude-2", 1, 1) is None
