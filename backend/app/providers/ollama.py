"""Ollama provider — the primary local path.

Uses the native Ollama HTTP API:
  POST /api/chat       (with optional `tools` for models that support them)
  POST /api/embed      (batch embeddings, e.g. nomic-embed-text)
  GET  /api/tags       (health + installed models)
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx

from app.errors import (
    ProviderError,
    ProviderModelMissingError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.logging_config import get_logger
from app.providers.base import CompletionResult, LLMProvider, ToolCall, ToolSpec

logger = get_logger(__name__)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        embedding_model: str,
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
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model

    # --- internals ---------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        effective_timeout = timeout if timeout is not None else max(self.timeout, 300.0)
        try:
            response = httpx.post(url, json=payload, timeout=effective_timeout)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(details={"provider": self.name, "path": path}) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "Cannot reach Ollama. Start it with `ollama serve` and check OLLAMA_BASE_URL.",
                details={"provider": self.name, "base_url": self.base_url},
            ) from exc

        if response.status_code == 404:
            raise ProviderModelMissingError(
                f"Ollama does not have the requested model installed. Run `ollama pull {payload.get('model')}`.",
                details={"provider": self.name, "model": payload.get("model")},
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Ollama returned HTTP {response.status_code}.",
                details={"provider": self.name, "status": response.status_code, "body": response.text[:500]},
            )
        return response.json()

    # --- LLMProvider -------------------------------------------------------

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
            "stream": False,
            "messages": [{"role": "system", "content": system}, *messages],
            "options": {
                "temperature": self.temperature,
                "num_predict": max_output_tokens or self.max_output_tokens,
            },
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in tools
            ]

        started = time.perf_counter()
        data = self._post("/api/chat", payload)
        latency_ms = (time.perf_counter() - started) * 1000

        message = data.get("message") or {}
        content = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            tool_calls.append(
                ToolCall(id=str(uuid.uuid4()), name=function.get("name", ""), arguments=arguments)
            )

        # Some models emit JSON tool calls in text content instead of message.tool_calls
        if not tool_calls and content.strip().startswith("{") and ("function" in content or "name" in content):
            try:
                parsed = json.loads(content.strip())
                if isinstance(parsed, dict):
                    if "function" in parsed and isinstance(parsed["function"], dict):
                        fn = parsed["function"]
                        tool_calls.append(
                            ToolCall(
                                id=str(uuid.uuid4()),
                                name=fn.get("name", ""),
                                arguments=fn.get("parameters") or fn.get("arguments") or {},
                            )
                        )
                        content = ""
                    elif "name" in parsed and ("arguments" in parsed or "parameters" in parsed):
                        tool_calls.append(
                            ToolCall(
                                id=str(uuid.uuid4()),
                                name=parsed.get("name", ""),
                                arguments=parsed.get("parameters") or parsed.get("arguments") or {},
                            )
                        )
                        content = ""
            except Exception:
                pass

        logger.info(
            "provider_completion",
            extra={
                "provider": self.name,
                "model": self.model,
                "latency_ms": round(latency_ms, 1),
                "tool_calls": len(tool_calls),
                "output_chars": len(content),
            },
        )
        return CompletionResult(
            text=content,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            provider=self.name,
            model=self.model,
            usage={
                "prompt_eval_count": data.get("prompt_eval_count"),
                "eval_count": data.get("eval_count"),
            },
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        started = time.perf_counter()
        data = self._post("/api/embed", {"model": self.embedding_model, "input": texts})
        vectors = data.get("embeddings")
        if not vectors:
            raise ProviderError(
                "Ollama returned no embeddings.",
                details={"provider": self.name, "model": self.embedding_model},
            )
        logger.info(
            "embeddings_generated",
            extra={
                "provider": self.name,
                "model": self.embedding_model,
                "count": len(vectors),
                "dimensions": len(vectors[0]),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return [list(map(float, vector)) for vector in vectors]

    def healthcheck(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
            installed = [m.get("model", "") for m in response.json().get("models", [])]
        except httpx.HTTPError:
            return {
                "status": "error",
                "detail": f"Ollama unreachable at {self.base_url}. Run `ollama serve`.",
            }

        def installed_match(target: str) -> bool:
            return any(name == target or name.split(":")[0] == target.split(":")[0] for name in installed)

        missing = [
            name for name in (self.model, self.embedding_model) if not installed_match(name)
        ]
        if missing:
            return {
                "status": "degraded",
                "detail": "Missing models: " + ", ".join(f"`ollama pull {name}`" for name in missing),
                "extra": {"installed_models": installed},
            }
        return {"status": "ok", "detail": None, "extra": {"installed_models": installed}}
