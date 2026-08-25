"""Stage 2 of ingestion: cleaning / normalisation.

Handles the transcript shapes that actually appear in podcast repositories:
plain text, markdown, WebVTT/SRT captions and JSON transcript objects.
No content is invented — cleaning only removes caption scaffolding and
normalises whitespace.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

TIMESTAMP_LINE = re.compile(
    r"^\s*(?:\d+\s*$)|^\s*(\d{1,2}:\d{2}(?::\d{2})?[.,]?\d*)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?[.,]?\d*)"
)
INLINE_TIMESTAMP = re.compile(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*[-–]?\s*")
VOICE_TAG = re.compile(r"^<v\s+([^>]+)>", re.IGNORECASE)
SPEAKER_PREFIX = re.compile(r"^([A-Z][A-Za-z .'-]{1,40}):\s+")
MULTISPACE = re.compile(r"[ \t]{2,}")
MULTINEWLINE = re.compile(r"\n{3,}")


@dataclass(slots=True)
class CleanedSegment:
    text: str
    timestamp: str | None = None
    speaker: str | None = None


@dataclass(slots=True)
class CleanedTranscript:
    text: str
    segments: list[CleanedSegment] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


def _clean_line(line: str) -> str:
    line = line.replace("\u00a0", " ").strip()
    line = MULTISPACE.sub(" ", line)
    return line


def clean_vtt(raw: str) -> CleanedTranscript:
    segments: list[CleanedSegment] = []
    current_timestamp: str | None = None
    buffer: list[str] = []
    buffer_speaker: str | None = None

    def append(text: str, speaker: str | None) -> None:
        """Append a segment, dropping captions that repeat the previous one —
        rolling caption files emit the same line two or three times."""
        text = text.strip()
        if not text:
            return
        if segments and segments[-1].text == text:
            return
        segments.append(CleanedSegment(text=text, timestamp=current_timestamp, speaker=speaker))

    def flush() -> None:
        nonlocal buffer_speaker
        if buffer:
            append(" ".join(buffer), buffer_speaker)
            buffer.clear()
        buffer_speaker = None

    for raw_line in raw.splitlines():
        line = _clean_line(raw_line)
        if not line or line.upper().startswith("WEBVTT"):
            continue
        match = TIMESTAMP_LINE.match(line)
        if match:
            flush()
            current_timestamp = (match.group(1) or "").split(".")[0].split(",")[0] or None
            continue
        # WebVTT voice spans (`<v Speaker>text`) carry the speaker; other tags are noise.
        voice_match = VOICE_TAG.match(line)
        speaker = None
        if voice_match:
            speaker = voice_match.group(1).strip() or None
            line = line[voice_match.end() :]
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        speaker_match = SPEAKER_PREFIX.match(line)
        if speaker is None and speaker_match:
            speaker = speaker_match.group(1)
            line = line[speaker_match.end() :]
        if speaker:
            flush()
            append(line, speaker)
            continue
        buffer.append(line)
    flush()

    text = "\n".join(segment.text for segment in segments if segment.text)
    return CleanedTranscript(text=MULTINEWLINE.sub("\n\n", text).strip(), segments=segments)



def clean_json(raw: str) -> CleanedTranscript:
    data = json.loads(raw)
    if isinstance(data, list):
        data = {"segments": data}
    if not isinstance(data, dict):
        raise ValueError("Unsupported JSON transcript shape (expected object or list of segments)")

    segments: list[CleanedSegment] = []
    raw_segments = data.get("segments") or data.get("transcript") or data.get("utterances") or []
    if isinstance(raw_segments, str):
        segments.append(CleanedSegment(text=_clean_line(raw_segments)))
    else:
        for item in raw_segments:
            if isinstance(item, str):
                segments.append(CleanedSegment(text=_clean_line(item)))
                continue
            text = _clean_line(str(item.get("text") or item.get("content") or ""))
            if not text:
                continue
            timestamp = item.get("start") or item.get("timestamp") or item.get("start_time")
            segments.append(
                CleanedSegment(
                    text=text,
                    timestamp=_format_timestamp(timestamp),
                    speaker=item.get("speaker") or item.get("name"),
                )
            )

    if not segments and isinstance(data.get("text"), str):
        segments.append(CleanedSegment(text=_clean_line(data["text"])))

    text = "\n".join(segment.text for segment in segments)
    metadata = {
        key: value
        for key, value in data.items()
        if key in {"title", "episode_title", "guest", "url", "source_url", "published_at", "date"}
    }
    return CleanedTranscript(text=text.strip(), segments=segments, raw_metadata=metadata)


def _format_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        total = int(value)
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    text = str(value).strip()
    return text or None


def clean_text(raw: str) -> CleanedTranscript:
    segments: list[CleanedSegment] = []
    for raw_line in raw.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        if line.startswith("#"):  # markdown heading — keep as content, drop hashes
            line = line.lstrip("#").strip()
        timestamp = None
        inline = INLINE_TIMESTAMP.match(line)
        if inline:
            timestamp = inline.group(1)
            line = line[inline.end() :]
        speaker = None
        speaker_match = SPEAKER_PREFIX.match(line)
        if speaker_match:
            speaker = speaker_match.group(1)
            line = line[speaker_match.end() :]
        if line:
            segments.append(CleanedSegment(text=line, timestamp=timestamp, speaker=speaker))

    text = "\n".join(segment.text for segment in segments)
    return CleanedTranscript(text=MULTINEWLINE.sub("\n\n", text).strip(), segments=segments)


def clean_transcript(raw: str, suffix: str) -> CleanedTranscript:
    suffix = suffix.lower()
    if suffix in {".vtt", ".srt"}:
        return clean_vtt(raw)
    if suffix == ".json":
        return clean_json(raw)
    return clean_text(raw)
