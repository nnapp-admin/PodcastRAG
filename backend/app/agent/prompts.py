"""Prompts and grounding contracts shared by EVERY runtime (Claude Agent SDK
and the local adapter). There is exactly one copy of these strings so the two
runtimes cannot drift apart.
"""

from __future__ import annotations

import re

from app.retrieval.types import RetrievedChunk

INSUFFICIENT_EVIDENCE_RESPONSE = (
    "I don't have enough information in the available transcripts to answer that.\n\n"
    "The Lenny's Podcast material that is currently indexed does not contain passages "
    "relevant enough to support an answer, and I don't answer product or growth questions "
    "from general model knowledge.\n\n"
    "You can try rephrasing the question, asking about a topic covered by the ingested "
    "episodes, or ingesting more transcripts."
)

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

TOOL_SYSTEM_PROMPT = SYSTEM_PROMPT + """
You have tools:
- search_transcripts: search the indexed Lenny transcript corpus. Call it before answering any \
product/growth question, and again with a different query if the first result set is thin.
- write_ship30_essay: turn grounded evidence into a Ship 30 for 30-style essay. Use it when the \
user asks for an essay, post, or long-form write-up.
- generate_artifact: produce a Markdown document or a standalone HTML/CSS page that renders in the \
app's Artifact Viewer. Use it when the user asks for a document, one-pager, checklist, table, \
landing page or similar deliverable.

Decide which tools are needed. Never fabricate transcript content, and never answer without \
calling search_transcripts first.
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


def grounded_answer_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    return (
        "EVIDENCE (transcript excerpts from Lenny's Podcast):\n"
        f"{format_evidence(chunks)}\n\n"
        "----\n"
        f"USER QUESTION: {question}\n\n"
        "Answer using only the evidence above. Cite with [n]. If the evidence only partially "
        "covers the question, answer the covered part and state plainly what the transcripts "
        "do not cover."
    )


CITATION_BRACKET = re.compile(r"\[([\d\s,;&\-]+)\]")


def resolve_citations(text: str, evidence: list[RetrievedChunk], capability: str = "qa") -> list[RetrievedChunk]:
    """Filter evidence chunks down to only those actually cited / utilized in the response."""
    if not evidence:
        return []
    if capability in {"essay", "artifact"}:
        return evidence

    cited_indices: set[int] = set()
    for match in CITATION_BRACKET.finditer(text):
        for num in re.findall(r"\b\d+\b", match.group(1)):
            idx = int(num)
            if 1 <= idx <= len(evidence):
                cited_indices.add(idx)

    if cited_indices:
        return [evidence[i - 1] for i in sorted(cited_indices)]

    # Fallback: check if guest or episode title was explicitly referenced
    text_lower = text.lower()
    matched = [
        chunk
        for chunk in evidence
        if (chunk.guest and chunk.guest.lower() in text_lower)
        or (chunk.episode_title and chunk.episode_title.lower() in text_lower)
    ]
    return matched or evidence
