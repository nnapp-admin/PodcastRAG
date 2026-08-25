"""Contracts shared by both agent runtimes.

Both the Claude Agent SDK runtime and the local adapter consume `AgentRequest`
and return `AgentResult`, so the API layer is runtime-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.artifacts.generator import GeneratedArtifact
from app.retrieval.types import RetrievedChunk

Capability = Literal["qa", "essay", "artifact"]


@dataclass(slots=True)
class AgentRequest:
    question: str
    history: list[dict[str, str]] = field(default_factory=list)
    requested_capability: Capability | None = None
    top_k: int | None = None
    score_threshold: float | None = None


@dataclass(slots=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]
    latency_ms: float
    summary: str
    ok: bool = True


@dataclass(slots=True)
class AgentResult:
    text: str
    capability: Capability
    grounded: bool
    citations: list[RetrievedChunk] = field(default_factory=list)
    artifact: GeneratedArtifact | None = None
    tool_invocations: list[ToolInvocation] = field(default_factory=list)
    runtime: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    word_count: int | None = None
    notes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentRuntime(Protocol):
    name: str

    def run(self, request: AgentRequest) -> AgentResult: ...
