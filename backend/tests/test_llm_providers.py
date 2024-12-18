"""Regression tests for the optional live LLM providers.

These tests never touch the network. They pin down the response mapping
for OpenAI-compatible and Anthropic payloads, and the health-check
contract (reachability can be tested before the live-call master switch
is enabled).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import settings
from app.llm.providers import LLMClient, LLMResult


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_openai_compatible_maps_usage_and_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [{"message": {"content": "OK"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    monkeypatch.setattr("app.llm.providers.httpx.post", lambda *a, **k: FakeResponse(payload))
    client = LLMClient(
        None,  # type: ignore[arg-type]
        {"provider": "ollama", "base_url": "http://example.invalid/v1", "model": "gemma3:1b"},
    )

    result = client._request("http://example.invalid/v1/chat/completions", {}, {}, "gemma3:1b")

    assert result.text == "OK"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3
    assert result.estimated_cost_usd == 0
    assert result.offline is False


def test_anthropic_maps_content_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "content": [{"text": "OK"}],
        "usage": {"input_tokens": 9, "output_tokens": 2},
    }
    monkeypatch.setattr("app.llm.providers.httpx.post", lambda *a, **k: FakeResponse(payload))
    client = LLMClient(
        None,  # type: ignore[arg-type]
        {"provider": "anthropic", "api_key": "fake", "model": "claude-3-5-haiku-20241022"},
    )

    result = client._request(
        "http://example.invalid/v1/messages", {}, {}, "claude-3-5-haiku-20241022", anthropic=True
    )

    assert result.text == "OK"
    assert result.prompt_tokens == 9
    assert result.completion_tokens == 2
    assert result.provider == "anthropic"


def test_health_check_reachable_before_live_calls_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LLMClient(
        None,  # type: ignore[arg-type]
        {"provider": "ollama", "base_url": "http://example.invalid/v1", "model": "gemma3:1b"},
    )
    calls: list[str] = []

    def fake_dispatch(prompt: str, max_tokens: int, system: str | None) -> LLMResult:
        calls.append(prompt)
        return LLMResult(text="OK", provider="ollama", model="gemma3:1b", completion_tokens=1)

    monkeypatch.setattr(settings, "llm_enabled", False)
    monkeypatch.setattr(client, "_dispatch", fake_dispatch)

    result = client.test_connection()

    assert result["ok"] is True
    assert result["model"] == "gemma3:1b"
    assert calls == ["Reply with OK."]
