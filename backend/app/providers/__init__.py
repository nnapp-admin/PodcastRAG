"""Provider factory: configuration is the only switch between providers."""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.anthropic import AnthropicProvider
from app.errors import ProviderAuthError
from app.providers.base import CompletionResult, LLMProvider, ToolCall, ToolSpec
from app.providers.ollama import OllamaProvider
from app.providers.openai_provider import OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "CompletionResult",
    "LLMProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "ToolCall",
    "ToolSpec",
    "build_provider",
    "get_embedding_provider",
    "get_provider",
]


def build_provider(settings: Settings, name: str | None = None, model: str | None = None) -> LLMProvider:
    provider_name = name or settings.llm_provider
    resolved_model = model or settings.llm_model

    if provider_name == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=resolved_model,
            embedding_model=settings.ollama_embedding_model,
            timeout=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
            temperature=settings.llm_temperature,
        )
    if provider_name == "anthropic":
        # Fail at wiring time, not mid-conversation, when a cloud key is missing.
        if not settings.anthropic_api_key:
            raise ProviderAuthError(
                "ANTHROPIC_API_KEY is not set. Set it in .env or switch LLM_PROVIDER=ollama.",
                details={"provider": "anthropic", "missing_env": "ANTHROPIC_API_KEY"},
            )
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
            model=resolved_model,
            timeout=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
            temperature=settings.llm_temperature,
        )
    if provider_name == "openai":
        if not settings.openai_api_key:
            raise ProviderAuthError(
                "OPENAI_API_KEY is not set. Set it in .env or switch LLM_PROVIDER=ollama.",
                details={"provider": "openai", "missing_env": "OPENAI_API_KEY"},
            )
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=resolved_model,
            timeout=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
            temperature=settings.llm_temperature,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider_name!r} (expected ollama|anthropic|openai)")


@lru_cache
def get_provider() -> LLMProvider:
    return build_provider(get_settings())


@lru_cache
def get_embedding_provider() -> LLMProvider:
    """Embeddings always come from EMBEDDING_PROVIDER (Ollama) so the local
    demo needs no cloud key, and so vectors stay comparable across chat
    provider switches."""
    settings = get_settings()
    return build_provider(settings, name=settings.embedding_provider, model=settings.llm_model)
