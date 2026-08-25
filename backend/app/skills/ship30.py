"""Ship 30 for 30 essay skill.

This is a real skill module, not an inline prompt: the writing principles are
encoded here, the skill REQUIRES grounded evidence as an input (it raises
without it), and it validates its own output shape before returning.

Principles encoded below are drawn from the Ship 30 for 30 approach to online
writing (atomic essays, one idea per piece, hook-first structure, skimmable
formatting, concrete specificity over abstraction, plain conversational voice).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.errors import AppError
from app.logging_config import get_logger
from app.providers.base import LLMProvider
from app.prompt_utils import strip_code_fence
from app.retrieval.types import RetrievedChunk
from app.agent.prompts import SYSTEM_PROMPT, format_evidence

logger = get_logger(__name__)

TARGET_WORDS = 1250
MIN_WORDS = 1050
MAX_WORDS = 1450

PRINCIPLES = [
    "One idea per essay. Pick the single sharpest insight the evidence supports and commit to it.",
    "Open with a hook of 1-2 short lines that names a specific pain, tension or surprising claim. "
    "No 'In today's world' preambles, no restating the prompt.",
    "Write at a 6th-grade reading level: short sentences, plain words, active voice, second person "
    "('you') where it helps the reader act.",
    "Use skimmable structure: an H1 title, 3-5 H2 section headings, short paragraphs of 1-3 lines.",
    "Use bullets or numbered lists for anything enumerable, and keep list items parallel in form.",
    "Bold selectively - only the 5-8 phrases a skimmer must catch. Never bold whole paragraphs.",
    "Prove every claim with specifics from the evidence: names, numbers, company examples, quotes.",
    "Close with one specific, useful takeaway the reader can apply this week - not a summary.",
    "Never invent statistics, quotes or examples. If the transcripts don't support it, leave it out.",
]

SKILL_SYSTEM_PROMPT = (
    SYSTEM_PROMPT
    + "\nYou are now writing in the Ship 30 for 30 style. Follow these writing principles exactly:\n"
    + "\n".join(f"- {principle}" for principle in PRINCIPLES)
    + "\n\nOutput format: Markdown only. Start with an H1 title. Do not wrap the essay in a code "
    "fence. Include a short '## Sources' section at the end listing the episodes you drew on, "
    "using the evidence numbering."
)


@dataclass(slots=True)
class Ship30Essay:
    markdown: str
    title: str
    word_count: int
    latency_ms: float


def word_count(markdown: str) -> int:
    return len([w for w in re.sub(r"[#*_>`\-]", " ", markdown).split() if w.strip()])


def extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()[:200]
    return "Ship 30 for 30 Essay"


def build_prompt(topic: str, chunks: list[RetrievedChunk], conversation_summary: str | None = None) -> str:
    if not chunks:
        raise AppError("The Ship 30 skill requires grounded evidence and received none.")
    sections = [
        "EVIDENCE (transcript excerpts from Lenny's Podcast — the only source of claims):",
        format_evidence(chunks),
        "----",
        f"ESSAY BRIEF: {topic}",
        f"TARGET LENGTH: approximately {TARGET_WORDS} words (aim for {MIN_WORDS}–{MAX_WORDS} words).",
        "STRUCTURE RULES:",
        "- Start with an H1 title and a punchy 2-line hook.",
        "- Write 4 to 5 substantive sections with clear H2 headings.",
        "- In each section, provide multi-paragraph analysis, concrete tactical steps, and quotes from the evidence.",
        "- End with a practical weekly takeaway section and an H2 Sources section citing the episodes as [n].",
    ]
    if conversation_summary:
        sections.insert(2, f"CONVERSATION CONTEXT (what the user has been exploring):\n{conversation_summary}")
    sections.append(
        "Write the full ~1,250-word essay now. Ground every claim in the evidence and cite episodes as [n] inline."
    )
    return "\n\n".join(sections)


def write_essay(
    provider: LLMProvider,
    *,
    topic: str,
    chunks: list[RetrievedChunk],
    conversation_summary: str | None = None,
    max_output_tokens: int = 4096,
) -> Ship30Essay:
    """Generate the essay. Raises AppError when evidence is missing — the skill
    never invents claims of its own."""
    prompt = build_prompt(topic, chunks, conversation_summary)
    result = provider.complete(
        system=SKILL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_output_tokens=max(max_output_tokens, 4096),
    )
    markdown = strip_code_fence(result.text).strip()
    if not markdown:
        raise AppError("The model returned an empty essay.", details={"skill": "ship30"})
SECTION_BLUEPRINTS = [
    (
        "The Tension / Status Quo",
        "Deconstruct the root problem, friction users face, and why conventional product development "
        "fails when customer communication and market education are neglected. Ground your analysis "
        "deeply in the evidence with concrete quotes and operator observations.",
        260,
    ),
    (
        "The Core Framework & Mental Model",
        "Explain the foundational mental model or framework revealed in the evidence. "
        "Contrast intuitive vs counter-intuitive approaches, unpacking the underlying principles "
        "with verbatim quotes and concrete operator examples.",
        280,
    ),
    (
        "Tactical Playbook & Step-by-Step Execution",
        "Provide a concrete, step-by-step tactical playbook for implementing this insight. "
        "Include 3-4 distinct actionable steps, rules, or checklists with numbers, metrics, and "
        "practical workflows grounded in the transcripts.",
        280,
    ),
    (
        "Counterintuitive Nuances & Common Pitfalls",
        "Analyze critical edge cases, counterintuitive nuances, and common mistakes teams make when "
        "applying this approach. Contrast comprehension vs friction, and explain how top operators navigate these traps.",
        230,
    ),
    (
        "Practical Weekly Takeaway & Action Plan",
        "Deliver an immediate, high-leverage action plan the reader can execute this week. "
        "Provide 3-5 concrete action items or diagnostic questions to apply right away.",
        150,
    ),
]


def _build_sources_section(chunks: list[RetrievedChunk]) -> str:
    lines = ["## Sources\n"]
    for i, c in enumerate(chunks, 1):
        guest_part = f" | guest: {c.guest}" if c.guest else ""
        source_part = f" | source: {c.source_url}" if c.source_url else ""
        lines.append(f"[{i}] {c.episode_title}{guest_part}{source_part}")
    return "\n".join(lines)


def _expand_essay_sections(
    provider: LLMProvider,
    *,
    topic: str,
    chunks: list[RetrievedChunk],
    draft_markdown: str,
    max_output_tokens: int = 4096,
) -> tuple[str, int]:
    """Progressively expand sections using grounded evidence until reaching the target word band."""
    title = extract_title(draft_markdown)
    if not title or title == "Ship 30 for 30 Essay":
        title = topic.strip()[:120]

    # 1. Extract or generate punchy hook
    lines = [line.strip() for line in draft_markdown.splitlines() if line.strip() and not line.strip().startswith("#")]
    hook = " ".join(lines[:2]) if lines else "Building a great product is only half the battle without clear communication."
    hook_header = f"# {title}\n\n{hook}"

    section_mds: list[str] = [hook_header]
    evidence_text = format_evidence(chunks)

    for section_name, guidance, target in SECTION_BLUEPRINTS:
        prompt = (
            f"EVIDENCE (transcript excerpts from Lenny's Podcast — the only source of claims):\n"
            f"{evidence_text}\n"
            f"----\n"
            f"ESSAY TOPIC: {topic}\n"
            f"ESSAY HOOK & THESIS: {hook}\n"
            f"SECTION HEADING: ## {section_name}\n"
            f"SECTION OBJECTIVE: {guidance}\n"
            f"TARGET SECTION LENGTH: approximately {target} words.\n\n"
            f"Write this section now in the Ship 30 for 30 style under the heading '## {section_name}'. "
            f"Ground all claims, metrics, quotes, and takeaways strictly in the evidence. Cite evidence inline as [n]. "
            f"Use short paragraphs (1-3 lines), selective bolding, and bulleted lists. "
            f"Do not include the H1 title or other sections. Output ONLY this section."
        )
        try:
            res = provider.complete(
                system=SKILL_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_output_tokens=max(max_output_tokens, 2048),
            )
            sec_text = strip_code_fence(res.text).strip()
            if sec_text:
                if not sec_text.startswith("##"):
                    sec_text = f"## {section_name}\n\n{sec_text}"
                section_mds.append(sec_text)
        except Exception as exc:
            logger.warning("ship30_section_expansion_failed", extra={"section": section_name, "error": str(exc)})

    # Add sources section
    section_mds.append(_build_sources_section(chunks))
    combined_md = "\n\n".join(section_mds)
    words = word_count(combined_md)
    return combined_md, words


def write_essay(
    provider: LLMProvider,
    *,
    topic: str,
    chunks: list[RetrievedChunk],
    conversation_summary: str | None = None,
    max_output_tokens: int = 4096,
) -> Ship30Essay:
    """Generate the essay. Raises AppError when evidence is missing — the skill
    never invents claims of its own."""
    prompt = build_prompt(topic, chunks, conversation_summary)
    result = provider.complete(
        system=SKILL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_output_tokens=max(max_output_tokens, 4096),
    )
    markdown = strip_code_fence(result.text).strip()
    if not markdown:
        raise AppError("The model returned an empty essay.", details={"skill": "ship30"})
    if not markdown.lstrip().startswith("#"):
        markdown = f"# {topic.strip()[:120]}\n\n{markdown}"

    words = word_count(markdown)
    if words < MIN_WORDS:
        logger.info(
            "ship30_initiating_progressive_expansion",
            extra={"initial_words": words, "target_words": TARGET_WORDS, "min_words": MIN_WORDS},
        )
        expanded_md, expanded_words = _expand_essay_sections(
            provider,
            topic=topic,
            chunks=chunks,
            draft_markdown=markdown,
            max_output_tokens=max_output_tokens,
        )
        if expanded_words > words:
            markdown = expanded_md
            words = expanded_words

    logger.info(
        "ship30_essay_generated",
        extra={
            "word_count": words,
            "target_words": TARGET_WORDS,
            "below_minimum": words < MIN_WORDS,
            "evidence_chunks": len(chunks),
            "latency_ms": round(result.latency_ms, 1),
            "provider": result.provider,
            "model": result.model,
        },
    )
    return Ship30Essay(
        markdown=markdown,
        title=extract_title(markdown),
        word_count=words,
        latency_ms=result.latency_ms,
    )
