"""The agent's tools — one definition, shared by both runtimes.

Tools carry real behaviour (pgvector retrieval, the Ship 30 skill, artifact
generation + validation). `ToolContext` accumulates the evidence a run has
seen so grounding can be enforced after the fact, regardless of which runtime
drove the loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.artifacts.generator import GeneratedArtifact, generate_artifact
from app.config import Settings, get_settings
from app.errors import AppError
from app.logging_config import get_logger
from app.providers.base import LLMProvider, ToolSpec
from app.retrieval.types import Retriever, RetrievedChunk
from app.skills import ship30

logger = get_logger(__name__)


@dataclass(slots=True)
class ToolContext:
    retriever: Retriever
    provider: LLMProvider
    settings: Settings = field(default_factory=get_settings)
    evidence: list[RetrievedChunk] = field(default_factory=list)
    artifact: GeneratedArtifact | None = None
    essay: ship30.Ship30Essay | None = None
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    searches: list[str] = field(default_factory=list)

    def add_evidence(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        known = {chunk.chunk_id for chunk in self.evidence}
        for chunk in chunks:
            if chunk.chunk_id not in known:
                self.evidence.append(chunk)
                known.add(chunk.chunk_id)
        self.evidence.sort(key=lambda chunk: chunk.score, reverse=True)
        return self.evidence

    def top_evidence(self, limit: int | None = None) -> list[RetrievedChunk]:
        return self.evidence[: limit or self.settings.retrieval_top_k]

    @property
    def has_sufficient_evidence(self) -> bool:
        return len(self.evidence) >= self.settings.retrieval_min_chunks_for_answer


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_transcripts",
        description=(
            "Semantic search over the indexed Lenny's Podcast transcript corpus. "
            "Call this before answering any product or growth question. Returns numbered "
            "excerpts with episode, guest and timestamp metadata."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A focused search query. Prefer the user's own terminology.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "How many excerpts to return (1-12). Defaults to the configured value.",
                },
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="write_ship30_essay",
        description=(
            "Write a Ship 30 for 30-style atomic essay (~1250 words) grounded in the transcript "
            "evidence already gathered. Use for essay/post/long-form requests. Requires that "
            "search_transcripts has returned evidence first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The essay brief or topic."},
            },
            "required": ["topic"],
        },
    ),
    ToolSpec(
        name="generate_artifact",
        description=(
            "Produce a deliverable that renders in the app's Artifact Viewer: a Markdown "
            "document or a standalone HTML/CSS page (no JavaScript). Requires evidence from "
            "search_transcripts first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["markdown", "html"]},
                "instruction": {
                    "type": "string",
                    "description": "What the deliverable should contain and who it is for.",
                },
            },
            "required": ["kind", "instruction"],
        },
    ),
]


def tool_search_transcripts(context: ToolContext, arguments: dict[str, Any]) -> str:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise AppError("search_transcripts requires a non-empty 'query'.")
    requested = arguments.get("top_k")
    top_k = max(1, min(int(requested), 12)) if isinstance(requested, (int, float, str)) and str(requested).isdigit() else None

    result = context.retriever.search(query, top_k=top_k)
    context.retrieval_latency_ms += result.latency_ms
    context.searches.append(query)
    context.add_evidence(result.chunks)

    if result.is_empty:
        return (
            f"No transcript excerpts passed the relevance threshold "
            f"({result.score_threshold}) for query: {query!r}. "
            f"{result.candidates_considered} candidates were considered. "
            "Do not answer from general knowledge."
        )
    from app.agent.prompts import format_evidence  # local import avoids a cycle

    return (
        f"{len(result.chunks)} excerpt(s) for {query!r} "
        f"(top relevance {result.chunks[0].score:.3f}):\n\n{format_evidence(result.chunks)}"
    )


def tool_write_ship30_essay(context: ToolContext, arguments: dict[str, Any]) -> str:
    topic = str(
        arguments.get("topic")
        or arguments.get("prompt")
        or arguments.get("title")
        or arguments.get("instruction")
        or arguments.get("query")
        or ""
    ).strip()
    if not topic:
        topic = "Product & Growth Insights"
    if not context.has_sufficient_evidence:
        return (
            "Refused: no transcript evidence has been gathered yet. "
            "Call search_transcripts first; do not write from general knowledge."
        )
    essay = ship30.write_essay(
        context.provider,
        topic=topic,
        chunks=context.top_evidence(),
        max_output_tokens=context.settings.llm_max_output_tokens,
    )
    context.essay = essay
    context.generation_latency_ms += essay.latency_ms
    return (
        f"Essay written: {essay.word_count} words, title {essay.title!r}. "
        "It has already been delivered to the user; reply with a one-line confirmation only."
    )


def tool_generate_artifact(context: ToolContext, arguments: dict[str, Any]) -> str:
    kind = str(arguments.get("kind") or "markdown").strip().lower()
    if kind not in {"markdown", "html"}:
        kind = "markdown"
    instruction = str(
        arguments.get("instruction")
        or arguments.get("topic")
        or arguments.get("prompt")
        or arguments.get("title")
        or arguments.get("query")
        or ""
    ).strip()
    if not instruction:
        instruction = "Product & Growth Deliverable"
    if not context.has_sufficient_evidence:
        return (
            "Refused: no transcript evidence has been gathered yet. "
            "Call search_transcripts first; do not build an artifact from general knowledge."
        )
    artifact = generate_artifact(
        context.provider,
        kind=kind,
        instruction=instruction,
        chunks=context.top_evidence(),
        max_output_tokens=context.settings.llm_max_output_tokens,
    )
    context.artifact = artifact
    context.generation_latency_ms += artifact.latency_ms
    return (
        f"{kind} artifact created: {artifact.title!r} ({artifact.report.byte_size} bytes"
        f"{', sanitized' if artifact.report.sanitized else ''}). "
        "It is already rendered in the Artifact Viewer; reply with a one-line summary only."
    )


TOOL_HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], str]] = {
    "search_transcripts": tool_search_transcripts,
    "write_ship30_essay": tool_write_ship30_essay,
    "generate_artifact": tool_generate_artifact,
}


def execute_tool(context: ToolContext, name: str, arguments: dict[str, Any]) -> tuple[str, float, bool]:
    """Run a tool by name. Tool failures are returned to the model as text so a
    single bad tool call degrades the answer instead of killing the request."""
    handler = TOOL_HANDLERS.get(name)
    started = time.perf_counter()
    if handler is None:
        return (f"Unknown tool {name!r}. Available: {', '.join(TOOL_HANDLERS)}.", 0.0, False)
    try:
        output = handler(context, arguments or {})
        ok = True
    except AppError as exc:
        output = f"Tool {name} failed: {exc.message}"
        ok = False
    except Exception as exc:  # defensive: never let a tool crash the request
        output = f"Tool {name} failed unexpectedly: {type(exc).__name__}"
        ok = False
    latency_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "tool_executed",
        extra={"tool": name, "ok": ok, "latency_ms": round(latency_ms, 1), "arguments": arguments},
    )
    return output, latency_ms, ok
