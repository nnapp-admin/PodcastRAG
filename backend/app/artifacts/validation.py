"""Artifact validation and sanitisation.

Artifacts are rendered in the client inside a sandboxed iframe WITHOUT
allow-scripts, so script execution is already impossible in the browser.
This module is the second half of that defence: server-side, we reject or strip
anything script-like before the artifact is ever persisted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.errors import ArtifactInvalidError

SCRIPT_TAG = re.compile(r"<script\b.*?(?:</script\s*>|$)", re.IGNORECASE | re.DOTALL)
DANGEROUS_TAGS = re.compile(
    r"<\s*/?\s*(iframe|object|embed|applet|form|base|meta\s+http-equiv)\b[^>]*>",
    re.IGNORECASE,
)
EVENT_HANDLER = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
JS_URL = re.compile(r"(href|src|action|xlink:href)\s*=\s*(\"|')?\s*(javascript|data:text/html|vbscript):[^\"'>]*(\"|')?", re.IGNORECASE)
IMPORT_RULE = re.compile(r"@import[^;]+;", re.IGNORECASE)
MD_HTML_BLOCK = re.compile(r"<\s*(script|iframe|object|embed)\b", re.IGNORECASE)

ALLOWED_KINDS = {"markdown", "html"}


@dataclass(slots=True)
class ValidationReport:
    kind: str
    content: str
    removed: list[str] = field(default_factory=list)
    byte_size: int = 0

    @property
    def sanitized(self) -> bool:
        return bool(self.removed)


def validate_artifact(kind: str, content: str) -> ValidationReport:
    settings = get_settings()
    if kind not in ALLOWED_KINDS:
        raise ArtifactInvalidError(
            f"Unsupported artifact kind '{kind}'.",
            details={"allowed_kinds": sorted(ALLOWED_KINDS)},
        )
    content = (content or "").strip()
    if not content:
        raise ArtifactInvalidError("The artifact was empty.", details={"kind": kind})

    encoded = content.encode("utf-8")
    if len(encoded) > settings.artifact_max_bytes:
        raise ArtifactInvalidError(
            "The artifact exceeds the configured maximum size.",
            details={"byte_size": len(encoded), "max_bytes": settings.artifact_max_bytes},
        )

    removed: list[str] = []
    if kind == "html":
        content, removed = _sanitize_html(content)
        if "<" not in content:
            raise ArtifactInvalidError(
                "The artifact was declared as HTML but contains no markup.",
                details={"kind": kind},
            )
    elif MD_HTML_BLOCK.search(content):
        content = SCRIPT_TAG.sub("", content)
        content = DANGEROUS_TAGS.sub("", content)
        removed.append("embedded_html_in_markdown")

    return ValidationReport(kind=kind, content=content.strip(), removed=removed, byte_size=len(content.encode("utf-8")))


def _sanitize_html(content: str) -> tuple[str, list[str]]:
    removed: list[str] = []

    def track(pattern: re.Pattern[str], label: str, replacement: str, text: str) -> str:
        new_text, count = pattern.subn(replacement, text)
        if count:
            removed.append(f"{label}x{count}")
        return new_text

    content = track(SCRIPT_TAG, "script_tag", "", content)
    content = track(DANGEROUS_TAGS, "unsafe_tag", "", content)
    content = track(EVENT_HANDLER, "inline_event_handler", "", content)
    content = track(JS_URL, "unsafe_url", r'\1="#"', content)
    content = track(IMPORT_RULE, "css_import", "", content)
    return content, removed
