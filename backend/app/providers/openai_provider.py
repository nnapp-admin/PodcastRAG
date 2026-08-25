"""OpenAI provider (cloud, optional). Chat Completions + embeddings."""

from __future__ import annotations

import json
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


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout: float,
        max_output_tokens: int,
        temperature: float,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        super().__init__(
            model=model,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderAuthError(
                "OPENAI_API_KEY is not set. Set it in .env or switch LLM_PROVIDER=ollama.",
                details={"provider": self.name, "missing_env": "OPENAI_API_KEY"},
            )
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers()
        try:
            response = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(details={"provider": self.name}) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "Cannot reach the OpenAI API.", details={"provider": self.name}
            ) from exc
        if response.status_code in (401, 403):
            raise ProviderAuthError("OpenAI rejected the API key.", details={"provider": self.name})
        if response.status_code >= 400:
            raise ProviderError(
                f"OpenAI returned HTTP {response.status_code}.",
                details={"provider": self.name, "status": response.status_code, "body": response.text[:500]},
            )
        return response.json()

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec] | None = None,
        max_output_tokens: int | None = None,
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_completion_tokens": max_output_tokens or self.max_output_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]

        started = time.perf_counter()
        data = self._post("/chat/completions", payload)
        latency_ms = (time.perf_counter() - started) * 1000

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(id=raw.get("id", ""), name=function.get("name", ""), arguments=arguments)
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
            text=message.get("content") or "",
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            provider=self.name,
            model=self.model,
            usage=data.get("usage") or {},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = self._post("/embeddings", {"model": self.embedding_model, "input": texts})
        return [list(map(float, item["embedding"])) for item in data.get("data", [])]

    def healthcheck(self) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "error", "detail": "OPENAI_API_KEY is not set."}
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                timeout=5.0,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError:
            return {"status": "error", "detail": "OpenAI API unreachable."}
        if response.status_code in (401, 403):
            return {"status": "error", "detail": "OpenAI rejected the API key."}
        if response.status_code >= 400:
            return {"status": "degraded", "detail": f"OpenAI returned HTTP {response.status_code}."}
        return {"status": "ok", "detail": None}
