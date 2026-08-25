"""Provider abstraction.

    LLMProvider
    ├── OllamaProvider      (local, primary path, also serves embeddings)
    ├── AnthropicProvider   (cloud)
    └── OpenAIProvider      (cloud)

Selection happens through configuration only (LLM_PROVIDER / LLM_MODEL); no
application code branches on provider identity.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolSpec:
    """Provider-independent tool definition shared by every runtime."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class CompletionResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    latency_ms: float = 0.0
    provider: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Every provider implements the same three capabilities."""

    name: str

    def __init__(self, *, model: str, timeout: float, max_output_tokens: int, temperature: float) -> None:
        self.model = model
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature

    @abc.abstractmethod
    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec] | None = None,
        max_output_tokens: int | None = None,
    ) -> CompletionResult:
        """Single completion. `messages` items are {"role": "user"|"assistant", "content": str}."""

    @abc.abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""

    @abc.abstractmethod
    def healthcheck(self) -> dict[str, Any]:
        """Never raises: returns {"status": "ok"|"degraded"|"error", "detail": str|None}."""

    def supports_embeddings(self) -> bool:
        return True
