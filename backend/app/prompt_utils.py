"""Small shared helpers for handling model output and prompt formatting."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.retrieval.types import RetrievedChunk

FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*\s*\n(.*?)\n?```\s*$", re.DOTALL)
ANY_FENCE = re.compile(r"```([a-zA-Z0-9]*)\s*\n(.*?)```", re.DOTALL)

SYSTEM_PROMPT = """You are the Lenny Growth Assistant, an internal product & growth assistant for a \
product team. You answer ONLY from transcript excerpts of Lenny's Podcast / Newsletter that are \
supplied to you as EVIDENCE.

Hard rules:
- Never answer a product or growth question from your own general knowledge. If the evidence does \
not support a claim, say what is missing instead of guessing.
- Every substantive claim must be traceable to the supplied evidence. Reference episodes inline \
like [1], [2] matching the evidence numbering.
- Prefer concrete tactics, numbers, frameworks and quotes that appear in the evidence.
- Be concise and skimmable: short paragraphs, bullets where useful, no filler preamble.
- If the user asks a follow-up, use the conversation history for context but still ground new \
claims in the supplied evidence.
"""


def format_evidence(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as numbered EVIDENCE the model must cite."""
    blocks: list[str] = []
    for position, chunk in enumerate(chunks, start=1):
        header_parts = [f"[{position}] {chunk.episode_title}"]
        if chunk.guest:
            header_parts.append(f"guest: {chunk.guest}")
        if chunk.start_timestamp:
            header_parts.append(f"timestamp: {chunk.start_timestamp}")
        if chunk.source_url:
            header_parts.append(f"source: {chunk.source_url}")
        header_parts.append(f"relevance: {chunk.score:.3f}")
        blocks.append(" | ".join(header_parts) + "\n" + chunk.content.strip())
    return "\n\n".join(blocks)


def strip_code_fence(text: str) -> str:
    """Remove a single wrapping code fence, if the whole answer is fenced."""
    match = FENCE.match(text or "")
    return match.group(1) if match else (text or "")


def extract_fenced_block(text: str, languages: tuple[str, ...]) -> str | None:
    """Return the first fenced block whose language matches, else None."""
    for language, body in ANY_FENCE.findall(text or ""):
        if language.lower() in languages:
            return body.strip()
    return None
