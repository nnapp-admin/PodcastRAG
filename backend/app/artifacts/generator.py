"""Artifact generation: grounded content -> validated Markdown or HTML artifact."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.artifacts.validation import ValidationReport, validate_artifact
from app.errors import AppError
from app.logging_config import get_logger
from app.prompt_utils import extract_fenced_block, format_evidence, strip_code_fence, SYSTEM_PROMPT
from app.providers.base import LLMProvider
from app.retrieval.types import RetrievedChunk

logger = get_logger(__name__)

MARKDOWN_SYSTEM = (
    SYSTEM_PROMPT
    + "\nYou are producing a standalone Markdown document for a product team. Rules:\n"
    "- Output Markdown only, starting with an H1 title. No code fence around the document.\n"
    "- Use headings, short paragraphs, bullets and tables where they help.\n"
    "- Ground every claim in the supplied evidence and cite episodes as [n].\n"
    "- End with a '## Sources' section listing the episodes used."
)

HTML_SYSTEM = (
    SYSTEM_PROMPT
    + "\nYou are producing ONE standalone HTML page for a product team. Rules:\n"
    "- Output a single complete HTML document inside one ```html code fence and nothing else.\n"
    "- All styling goes in a single <style> block. No JavaScript, no <script>, no external "
    "requests, no remote fonts or images — the page renders inside a sandboxed iframe with "
    "scripts disabled, so any script would simply not run.\n"
    "- Use semantic HTML, a readable type scale, and a restrained palette.\n"
    "- Ground every claim in the supplied evidence and cite episodes inline as [n]."
)


@dataclass(slots=True)
class GeneratedArtifact:
    kind: str
    title: str
    content: str
    report: ValidationReport
    latency_ms: float


def _extract_title(kind: str, content: str, fallback: str) -> str:
    if kind == "markdown":
        for line in content.splitlines():
            if line.strip().startswith("# "):
                return line.strip()[2:].strip()[:200]
    else:
        match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
        if match and match.group(1).strip():
            return match.group(1).strip()[:200]
        match = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
        if match:
            return re.sub(r"<[^>]+>", "", match.group(1)).strip()[:200]
    return fallback.strip()[:200] or "Artifact"


def generate_artifact(
    provider: LLMProvider,
    *,
    kind: str,
    instruction: str,
    chunks: list[RetrievedChunk],
    max_output_tokens: int = 1800,
) -> GeneratedArtifact:
    if kind not in {"markdown", "html"}:
        raise AppError(f"Unsupported artifact kind '{kind}'.", details={"allowed": ["markdown", "html"]})
    if not chunks:
        raise AppError(
            "Artifact generation requires grounded transcript evidence and received none.",
            details={"kind": kind},
        )

    prompt = (
        "EVIDENCE (transcript excerpts from Lenny's Podcast — the only source of claims):\n"
        f"{format_evidence(chunks)}\n\n----\n"
        f"DELIVERABLE BRIEF: {instruction}\n\n"
        "Produce the deliverable now."
    )
    result = provider.complete(
        system=MARKDOWN_SYSTEM if kind == "markdown" else HTML_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_output_tokens=max_output_tokens,
    )

    raw = result.text or ""
    if kind == "html":
        content = extract_fenced_block(raw, ("html",)) or strip_code_fence(raw)
    else:
        content = strip_code_fence(raw)

    report = validate_artifact(kind, content)
    title = _extract_title(kind, report.content, instruction)
    logger.info(
        "artifact_generated",
        extra={
            "artifact_kind": kind,
            "byte_size": report.byte_size,
            "sanitized": report.sanitized,
            "removed": report.removed,
            "evidence_chunks": len(chunks),
            "latency_ms": round(result.latency_ms, 1),
            "provider": result.provider,
            "model": result.model,
        },
    )
    return GeneratedArtifact(
        kind=kind,
        title=title,
        content=report.content,
        report=report,
        latency_ms=result.latency_ms,
    )
