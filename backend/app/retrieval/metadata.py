"""Stage 3 of ingestion: metadata extraction.

Metadata is read from (in priority order):
  1. an explicit sidecar / JSON field in the transcript file itself
  2. YAML-ish front matter at the top of the file
  3. the filename convention `YYYY-MM-DD__episode-title__guest-name.ext`
Nothing is guessed beyond that: a missing guest stays NULL rather than invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})[_\-\s]+")


@dataclass(slots=True)
class TranscriptMetadata:
    episode_title: str
    guest: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    extra: dict | None = None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().strip('"').strip("'")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%B %d, %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip().strip('"').strip("'")
    return fields, raw[match.end() :]


def from_filename(path: Path) -> TranscriptMetadata:
    stem = path.stem
    published_at = None
    date_match = DATE_PREFIX.match(stem)
    if date_match:
        published_at = _parse_date(date_match.group(1))
        stem = stem[date_match.end() :]
    parts = [p.strip() for p in re.split(r"__|\s+-\s+", stem) if p.strip()]
    title = parts[0].replace("-", " ").replace("_", " ").strip() if parts else path.stem
    guest = parts[1].replace("-", " ").replace("_", " ").strip() if len(parts) > 1 else None
    return TranscriptMetadata(
        episode_title=title.title() if title.islower() else title,
        guest=guest.title() if guest and guest.islower() else guest,
        published_at=published_at,
    )


def extract_metadata(path: Path, front_matter: dict[str, str], embedded: dict | None = None) -> TranscriptMetadata:
    fallback = from_filename(path)
    sources: list[dict] = [embedded or {}, front_matter or {}]

    def pick(*keys: str) -> str | None:
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value:
                    return str(value)
        return None

    extra_info: dict[str, str] = {"source_file": path.name}
    for key in ("description", "word_count", "type"):
        val = pick(key)
        if val:
            extra_info[key] = val

    return TranscriptMetadata(
        episode_title=pick("episode_title", "title", "episode") or fallback.episode_title,
        guest=pick("guest", "guests", "speaker") or fallback.guest,
        source_url=pick("source_url", "post_url", "url", "link", "youtube_url"),
        published_at=_parse_date(pick("published_at", "date", "published", "publish_date")) or fallback.published_at,
        extra=extra_info,
    )
