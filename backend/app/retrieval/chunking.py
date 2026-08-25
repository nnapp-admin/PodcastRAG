"""Stage 4 of ingestion: semantic chunking.

Chunks are built from cleaned segments so a chunk never splits mid-sentence and
always carries the timestamp/speaker of the first segment it contains. Chunks
overlap by `overlap_chars` worth of trailing segments to preserve context
across boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.retrieval.cleaning import CleanedSegment


@dataclass(slots=True)
class Chunk:
    index: int
    content: str
    start_timestamp: str | None = None
    end_timestamp: str | None = None
    speaker: str | None = None
    token_estimate: int = 0
    metadata: dict = field(default_factory=dict)


def _token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_segments(
    segments: list[CleanedSegment],
    *,
    target_chars: int = 1400,
    overlap_chars: int = 200,
) -> list[Chunk]:
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    usable_segments = [segment for segment in segments if segment.text.strip()]
    if not usable_segments:
        return []

    chunks: list[Chunk] = []
    buffer: list[CleanedSegment] = []
    buffer_len = 0

    def flush() -> None:
        nonlocal buffer, buffer_len
        if not buffer:
            return
        content = " ".join(segment.text.strip() for segment in buffer).strip()
        if not content:
            buffer, buffer_len = [], 0
            return
        timestamps = [segment.timestamp for segment in buffer if segment.timestamp]
        speakers = [segment.speaker for segment in buffer if segment.speaker]
        chunks.append(
            Chunk(
                index=len(chunks),
                content=content,
                start_timestamp=timestamps[0] if timestamps else None,
                end_timestamp=timestamps[-1] if timestamps else None,
                speaker=speakers[0] if speakers else None,
                token_estimate=_token_estimate(content),
                metadata={"segment_count": len(buffer)},
            )
        )
        # carry trailing segments forward as overlap
        carry: list[CleanedSegment] = []
        carry_len = 0
        for segment in reversed(buffer):
            if carry_len >= overlap_chars:
                break
            carry.insert(0, segment)
            carry_len += len(segment.text) + 1
        buffer = carry if carry_len < target_chars else []
        buffer_len = sum(len(segment.text) + 1 for segment in buffer)

    for segment in usable_segments:
        text = segment.text.strip()
        if len(text) > target_chars * 2:
            # A single very long paragraph: hard-split on sentence boundaries.
            flush()
            for piece in _split_long(text, target_chars):
                buffer = [CleanedSegment(text=piece, timestamp=segment.timestamp, speaker=segment.speaker)]
                buffer_len = len(piece)
                flush()
            continue
        buffer.append(segment)
        buffer_len += len(text) + 1
        if buffer_len >= target_chars:
            flush()

    # final flush without overlap carry
    if buffer:
        content = " ".join(segment.text.strip() for segment in buffer).strip()
        if content and (not chunks or chunks[-1].content != content):
            timestamps = [segment.timestamp for segment in buffer if segment.timestamp]
            speakers = [segment.speaker for segment in buffer if segment.speaker]
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=content,
                    start_timestamp=timestamps[0] if timestamps else None,
                    end_timestamp=timestamps[-1] if timestamps else None,
                    speaker=speakers[0] if speakers else None,
                    token_estimate=_token_estimate(content),
                    metadata={"segment_count": len(buffer)},
                )
            )
    return chunks


def _split_words(text: str, target_chars: int) -> list[str]:
    """Last-resort split for text with no sentence boundaries (auto-captions
    often have none). Splits on word boundaries so no chunk exceeds the target."""
    pieces: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > target_chars and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_long(text: str, target_chars: int) -> list[str]:
    sentences = [s.strip() for s in text.replace("? ", "?|").replace("! ", "!|").replace(". ", ".|").split("|")]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 > target_chars and current:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current.strip())
    # A single "sentence" can still exceed the target; enforce the bound.
    bounded: list[str] = []
    for piece in pieces:
        bounded.extend([piece] if len(piece) <= target_chars else _split_words(piece, target_chars))
    return bounded

