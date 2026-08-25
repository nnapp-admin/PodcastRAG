"""Anthropic Claude provider (cloud, optional).

Called over the documented Messages API with httpx so the container needs no
extra SDK at runtime; the Claude *Agent SDK* runtime (app/agent/claude_sdk_runtime.py)
is a separate, agent-level integration.
Anthropic does not offer an embedding endpoint, so embeddings always come from
the configured embedding provider (Ollama) — see `supports_embeddings`.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.logging_config import get_logger
from app.providers.base import CompletionResult, LLMProvider, ToolCall, ToolSpec

logger = get_logger(__name__)

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout: float,
        max_output_tokens: int,
        temperature: float,
    ) -> None:
        super().__init__(
            model=model,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _require_key(self) -> str:
        if not self.api_key:
            raise ProviderAuthError(
                "ANTHROPIC_API_KEY is not set. Set it in .env or switch LLM_PROVIDER=ollama.",
                details={"provider": self.name, "missing_env": "ANTHROPIC_API_KEY"},
            )
        return self.api_key

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec] | None = None,
        max_output_tokens: int | None = None,
    ) -> CompletionResult:
        api_key = self._require_key()
        payload: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "max_tokens": max_output_tokens or self.max_output_tokens,
            "temperature": self.temperature,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]

        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                timeout=self.timeout,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(details={"provider": self.name}) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "Cannot reach the Anthropic API.", details={"provider": self.name}
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        if response.status_code in (401, 403):
            raise ProviderAuthError(
                "Anthropic rejected the API key.", details={"provider": self.name}
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Anthropic returned HTTP {response.status_code}.",
                details={"provider": self.name, "status": response.status_code, "body": response.text[:500]},
            )

        data = response.json()
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.get("id", ""), name=block.get("name", ""), arguments=block.get("input") or {})
                )

        logger.info(
            "provider_completion",
            extra={
                "provider": self.name,
                "model": self.model,
                "latency_ms": round(latency_ms, 1),
                "tool_calls": len(tool_calls),
            },
        )
        return CompletionResult(
            text="".join(text_parts),
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            provider=self.name,
            model=self.model,
            usage=data.get("usage") or {},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError(
            "Anthropic does not provide an embeddings endpoint; embeddings use EMBEDDING_PROVIDER (Ollama).",
            details={"provider": self.name},
        )

    def supports_embeddings(self) -> bool:
        return False

    def healthcheck(self) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "error", "detail": "ANTHROPIC_API_KEY is not set."}
        try:
            response = httpx.get(
                f"{self.base_url}/v1/models",
                timeout=5.0,
                headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
            )
        except httpx.HTTPError:
            return {"status": "error", "detail": "Anthropic API unreachable."}
        if response.status_code in (401, 403):
            return {"status": "error", "detail": "Anthropic rejected the API key."}
        if response.status_code >= 400:
            return {"status": "degraded", "detail": f"Anthropic returned HTTP {response.status_code}."}
        return {"status": "ok", "detail": None}
