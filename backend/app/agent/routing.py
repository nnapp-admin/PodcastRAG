"""Capability routing.

The agent still decides *how* to use its tools; this router only resolves which
capability the user asked for so the runtime can bias tool selection and the API
can report it. Explicit user selection in the UI always wins.
"""

from __future__ import annotations

import re

from app.agent.contracts import Capability

ESSAY_PATTERNS = (
    r"\bessay\b", r"\bship\s*30\b", r"\bblog post\b", r"\bnewsletter\b",
    r"\blinkedin post\b", r"\bwrite (?:me )?(?:a|an) (?:post|piece|article)\b",
    r"\blong[- ]form\b", r"\barticle\b",
)
ARTIFACT_PATTERNS = (
    r"\bone[- ]pager\b", r"\bdocument\b", r"\bdoc\b", r"\bchecklist\b", r"\btemplate\b",
    r"\bplaybook\b", r"\bmemo\b", r"\bbrief\b", r"\bslide\b", r"\btable\b", r"\bmatrix\b",
    r"\bframework\b(?=.*\b(?:doc|page|pager|template)\b)", r"\blanding page\b",
    r"\bhtml\b", r"\bweb ?page\b", r"\bmarkdown\b", r"\breport\b", r"\bscorecard\b",
    r"\bdashboard\b", r"\bpdf\b", r"\bexport\b", r"\bvisual\b", r"\bcard\b",
    r"\bdiagram\b", r"\bchart\b", r"\bartifact\b",
)
HTML_PATTERNS = (r"\bhtml\b", r"\bweb ?page\b", r"\blanding page\b", r"\bstyled\b", r"\bvisual\b", r"\bpage\b")


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def route_capability(question: str, requested: Capability | None = None) -> Capability:
    if requested in ("qa", "essay", "artifact"):
        return requested
    text = (question or "").lower()
    if _matches(text, ESSAY_PATTERNS):
        return "essay"
    if _matches(text, ARTIFACT_PATTERNS):
        return "artifact"
    return "qa"


def preferred_artifact_kind(question: str) -> str:
    return "html" if _matches((question or "").lower(), HTML_PATTERNS) else "markdown"


def extract_query_topic(question: str) -> str:
    """Strip directive prefixes ('Write a Ship 30 essay about...') to focus retrieval."""
    cleaned = re.sub(
        r"^(?:please\s+)?(?:write|build|create|generate|draft|make)(?:\s+me)?\s+(?:a|an|the)?\s*"
        r"(?:ship\s*30(?:\s*for\s*30)?\s*)?(?:atomic\s*)?(?:essay|post|article|one[- ]pager|document|checklist|template|dashboard|page)?\s*"
        r"(?:about|on|covering|for|regarding|exploring|discussing)?\s*",
        "",
        question,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned if len(cleaned) >= 3 else question.strip()
