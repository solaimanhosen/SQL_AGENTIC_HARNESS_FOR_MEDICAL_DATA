from langchain_core.messages import HumanMessage

from sql_agent.config import load_settings
from sql_agent.llm import REFUSAL_FALLBACK_BETA, build_chat_model


def _request_payload(env):
    model = build_chat_model(load_settings(env))
    # Private helper used on purpose: it returns the exact request body sent to the API,
    # so a library upgrade that changes what we send fails here rather than at runtime.
    return model._get_request_payload([HumanMessage("hi")])


def test_default_request_payload():
    p = _request_payload({})
    assert p["model"] == "claude-opus-5"
    assert p["max_tokens"] == 16_000
    assert p["output_config"] == {"effort": "high"}
    assert p["thinking"]["type"] == "adaptive"
    assert p["betas"] == [REFUSAL_FALLBACK_BETA]
    assert p["fallbacks"] == "default"
    # Opus 5 rejects sampling parameters with a 400.
    assert not {"temperature", "top_p", "top_k"} & p.keys()


def test_refusal_fallback_can_be_disabled():
    p = _request_payload({"SQL_AGENT_REFUSAL_FALLBACK": "false"})
    assert "fallbacks" not in p
    assert not p.get("betas")
