"""Offline tests for the LLM provider layer.

These use a mock transport so they never touch the network, never consume
Groq rate limit, and stay deterministic.
"""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core import llm as llm_module
from app.core.llm import GroqProvider, SimulatorProvider, get_llm_provider


class SampleSchema(BaseModel):
    name: str
    count: int


REAL_CLIENT = httpx.Client


def mock_groq(handler):
    """Patch httpx.Client so GroqProvider talks to `handler` instead of the network."""
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        kwargs.pop("transport", None)
        return REAL_CLIENT(transport=transport, **kwargs)

    return factory


def completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_generate_returns_message_content(monkeypatch):
    monkeypatch.setattr(httpx, "Client", mock_groq(lambda req: completion("hello")))
    assert GroqProvider(api_key="k").generate("hi") == "hello"


def test_generate_strips_reasoning_blocks(monkeypatch):
    """Qwen3 emits <think> blocks; exposing them would leak chain-of-thought."""
    raw = "<think>internal deliberation\nmore thinking</think>\n\nFinal answer"
    monkeypatch.setattr(httpx, "Client", mock_groq(lambda req: completion(raw)))
    assert GroqProvider(api_key="k").generate("hi") == "Final answer"


def test_system_prompt_is_sent_as_system_message(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return completion("ok")

    monkeypatch.setattr(httpx, "Client", mock_groq(handler))
    GroqProvider(api_key="k").generate("user text", "system text")

    assert seen["messages"][0] == {"role": "system", "content": "system text"}
    assert seen["messages"][1] == {"role": "user", "content": "user text"}
    assert seen["reasoning_format"] == "hidden"


def test_json_mode_enabled_only_for_structured_calls(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return completion('{"name": "x", "count": 1}')

    monkeypatch.setattr(httpx, "Client", mock_groq(handler))
    provider = GroqProvider(api_key="k")

    provider.generate("just chat")
    assert "response_format" not in seen

    provider.generate_structured("extract", SampleSchema)
    assert seen["response_format"] == {"type": "json_object"}


def test_generate_structured_returns_validated_model(monkeypatch):
    monkeypatch.setattr(
        httpx, "Client", mock_groq(lambda req: completion('{"name": "devforge", "count": 7}'))
    )
    result = GroqProvider(api_key="k").generate_structured("extract", SampleSchema)

    assert isinstance(result, SampleSchema)
    assert result.name == "devforge"
    assert result.count == 7


def test_generate_structured_unwraps_markdown_fences(monkeypatch):
    fenced = '```json\n{"name": "devforge", "count": 2}\n```'
    monkeypatch.setattr(httpx, "Client", mock_groq(lambda req: completion(fenced)))
    assert GroqProvider(api_key="k").generate_structured("x", SampleSchema).count == 2


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429, text="Please try again in 0.01s", json={"error": {"code": "rate_limit"}}
            )
        return completion("recovered")

    monkeypatch.setattr(httpx, "Client", mock_groq(handler))
    assert GroqProvider(api_key="k").generate("hi") == "recovered"
    assert calls["n"] == 2


def test_rate_limit_gives_up_after_max_retries(monkeypatch):
    """Persistent 429s must surface the API's own error, not retry forever."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "0"}, text="quota exhausted")

    monkeypatch.setattr(httpx, "Client", mock_groq(handler))
    monkeypatch.setattr(GroqProvider, "MAX_RETRIES", 3)

    with pytest.raises(RuntimeError, match="429"):
        GroqProvider(api_key="k").generate("hi")
    assert calls["n"] == 3


def test_retry_delay_prefers_retry_after_header():
    response = httpx.Response(429, headers={"retry-after": "3"})
    assert GroqProvider._retry_delay(response, attempt=0) == 3.0


def test_http_error_surfaces_status_and_body(monkeypatch):
    monkeypatch.setattr(
        httpx, "Client", mock_groq(lambda req: httpx.Response(404, text="model_not_found"))
    )
    with pytest.raises(RuntimeError, match="404"):
        GroqProvider(api_key="k").generate("hi")


# --- factory -------------------------------------------------------------


def test_factory_raises_when_groq_key_missing(monkeypatch):
    """A missing key must fail loudly, never silently serve canned fixtures."""
    settings = llm_module.get_settings()
    monkeypatch.setattr(settings, "groq_api_key", None, raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        get_llm_provider("groq")


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_llm_provider("gemini")


def test_factory_returns_simulator_only_when_asked():
    assert isinstance(get_llm_provider("simulator"), SimulatorProvider)
