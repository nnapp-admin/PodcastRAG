"""Provider abstraction: factory selection and error mapping at the HTTP boundary.

Only the transport is faked (httpx), so the real request/response translation in
each provider is exercised.
"""

from __future__ import annotations

import httpx
import pytest

from app.errors import (
    ProviderError,
    ProviderModelMissingError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.providers import get_embedding_provider, get_provider
from app.providers.anthropic import AnthropicProvider
from app.providers.ollama import OllamaProvider
from app.providers.openai_provider import OpenAIProvider


def make_ollama() -> OllamaProvider:
    return OllamaProvider(
        base_url="http://localhost:11434",
        model="llama3.1",
        embedding_model="nomic-embed-text",
        timeout=5.0,
        max_output_tokens=256,
        temperature=0.0,
    )


# --- factory --------------------------------------------------------------


def test_default_provider_is_ollama(monkeypatch):
    from app.config import get_settings

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    get_settings.cache_clear()
    get_provider.cache_clear()
    get_embedding_provider.cache_clear()
    provider = get_provider()
    assert isinstance(provider, OllamaProvider)
    get_settings.cache_clear()
    get_provider.cache_clear()
    get_embedding_provider.cache_clear()


def test_provider_is_selected_by_configuration(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()
    get_provider.cache_clear()
    get_embedding_provider.cache_clear()
    assert isinstance(get_provider(), AnthropicProvider)

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    get_provider.cache_clear()
    get_embedding_provider.cache_clear()
    assert isinstance(get_provider(), OpenAIProvider)

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    get_settings.cache_clear()
    get_provider.cache_clear()
    get_embedding_provider.cache_clear()


def test_missing_cloud_api_key_is_a_clear_error(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    get_provider.cache_clear()
    get_embedding_provider.cache_clear()
    with pytest.raises(ProviderError) as exc:
        get_provider()
    assert "ANTHROPIC_API_KEY" in str(exc.value.message)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    get_settings.cache_clear()
    get_provider.cache_clear()
    get_embedding_provider.cache_clear()


def test_every_provider_implements_the_interface():
    for cls in (OllamaProvider, AnthropicProvider, OpenAIProvider):
        for method in ("complete", "embed", "healthcheck"):
            assert callable(getattr(cls, method))


# --- ollama transport -----------------------------------------------------


def test_ollama_completion_parses_text_and_tool_calls(monkeypatch):
    payload = {
        "message": {
            "content": "Grounded answer.",
            "tool_calls": [
                {"function": {"name": "search_transcripts", "arguments": {"query": "retention"}}}
            ],
        },
        "eval_count": 42,
    }
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=payload))
    result = make_ollama().complete(system="s", messages=[{"role": "user", "content": "q"}])
    assert result.text == "Grounded answer."
    assert result.tool_calls[0].name == "search_transcripts"
    assert result.tool_calls[0].arguments == {"query": "retention"}
    assert result.provider == "ollama"
    assert result.latency_ms >= 0


def test_ollama_tool_arguments_as_json_string_are_parsed(monkeypatch):
    payload = {
        "message": {
            "content": "",
            "tool_calls": [{"function": {"name": "search_transcripts", "arguments": '{"query": "pmf"}'}}],
        }
    }
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=payload))
    result = make_ollama().complete(system="s", messages=[])
    assert result.tool_calls[0].arguments == {"query": "pmf"}


def test_ollama_embeddings_are_returned_as_floats(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: httpx.Response(200, json={"embeddings": [[1, 2, 3]]})
    )
    assert make_ollama().embed(["text"]) == [[1.0, 2.0, 3.0]]


def test_ollama_empty_embed_input_skips_the_network():
    assert make_ollama().embed([]) == []


def test_connection_failure_maps_to_provider_unavailable(monkeypatch):
    def raise_connect(*_a, **_k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", raise_connect)
    with pytest.raises(ProviderUnavailableError) as exc:
        make_ollama().complete(system="s", messages=[])
    assert "ollama serve" in exc.value.message.lower()


def test_timeout_maps_to_provider_timeout(monkeypatch):
    def raise_timeout(*_a, **_k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", raise_timeout)
    with pytest.raises(ProviderTimeoutError):
        make_ollama().complete(system="s", messages=[])


def test_missing_model_maps_to_model_missing(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(404, text="not found"))
    with pytest.raises(ProviderModelMissingError) as exc:
        make_ollama().complete(system="s", messages=[])
    assert "ollama pull" in exc.value.message.lower()


def test_server_error_maps_to_provider_error(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(500, text="boom"))
    with pytest.raises(ProviderError):
        make_ollama().complete(system="s", messages=[])


# --- health ---------------------------------------------------------------


def test_health_ok_when_models_installed(monkeypatch):
    body = {"models": [{"model": "llama3.1:8b"}, {"model": "nomic-embed-text:latest"}]}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json=body, request=httpx.Request("GET", "http://localhost:11434/api/tags")))
    assert make_ollama().healthcheck()["status"] == "ok"


def test_health_degraded_lists_the_pull_command(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"models": []}, request=httpx.Request("GET", "http://localhost:11434/api/tags")))
    health = make_ollama().healthcheck()
    assert health["status"] == "degraded"
    assert "ollama pull" in health["detail"]


def test_health_error_when_unreachable(monkeypatch):
    def raise_connect(*_a, **_k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", raise_connect)
    health = make_ollama().healthcheck()
    assert health["status"] == "error"
    assert "ollama serve" in health["detail"].lower()
