"""The ingestion pipeline.

    discover files -> clean -> extract metadata -> chunk -> embed -> upsert

Idempotency: a transcript is keyed by its `source_path` and a sha256 of its raw
bytes. Unchanged files are skipped unless `reindex=True`, in which case the
transcript's chunks are deleted and rebuilt. Nothing is invented: a file that
cannot be parsed is reported as a failure, never silently replaced.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from app.config import Settings, get_settings
from app.db.models import Transcript, TranscriptChunk
from app.logging_config import get_logger
from app.retrieval.chunking import chunk_segments
from app.retrieval.cleaning import clean_transcript
from app.retrieval.embedder import Embedder
from app.retrieval.metadata import extract_metadata, parse_front_matter

logger = get_logger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".vtt", ".srt"}


@dataclass(slots=True)
class FileOutcome:
    path: str
    status: str  # ingested | reindexed | skipped | failed
    chunks: int = 0
    detail: str | None = None


@dataclass(slots=True)
class IngestionSummary:
    files_discovered: int = 0
    ingested: int = 0
    reindexed: int = 0
    skipped: int = 0
    failed: int = 0
    chunks_written: int = 0
    duration_ms: float = 0.0
    outcomes: list[FileOutcome] = field(default_factory=list)

    def record(self, outcome: FileOutcome) -> None:
        self.outcomes.append(outcome)
        setattr(self, outcome.status, getattr(self, outcome.status) + 1)
        self.chunks_written += outcome.chunks


def discover_files(root: Path) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(
            f"Transcript folder not found: {root}. Create it and drop transcript files in "
            f"({', '.join(sorted(SUPPORTED_SUFFIXES))}), or pass --path."
        )
    if root.is_file():
        return [root] if root.suffix.lower() in SUPPORTED_SUFFIXES else []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SUFFIXES
        and not path.name.lower().startswith("readme")
    )


def _hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def ingest_file(
    db: OrmSession,
    path: Path,
    *,
    embedder: Embedder,
    settings: Settings,
    reindex: bool = False,
    root: Path | None = None,
) -> FileOutcome:
    key = str(path.relative_to(root)) if root and root in path.parents else str(path)
    raw_bytes = path.read_bytes()
    content_hash = _hash(raw_bytes)

    existing = db.scalar(select(Transcript).where(Transcript.source_path == key))
    if existing and existing.content_hash == content_hash and not reindex:
        chunk_count = len(existing.chunks)
        if chunk_count:
            return FileOutcome(path=key, status="skipped", detail="unchanged", chunks=0)

    raw_text = raw_bytes.decode("utf-8", errors="replace")
    front_matter, body = parse_front_matter(raw_text)
    cleaned = clean_transcript(body, path.suffix)
    if not cleaned.text.strip():
        return FileOutcome(path=key, status="failed", detail="no readable transcript text after cleaning")

    metadata = extract_metadata(path, front_matter, cleaned.raw_metadata)
    chunks = chunk_segments(
        cleaned.segments,
        target_chars=settings.chunk_target_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    if not chunks:
        return FileOutcome(path=key, status="failed", detail="cleaning produced no chunks")

    vectors = embedder.embed_documents([chunk.content for chunk in chunks])

    if existing is None:
        transcript = Transcript(source_path=key)
        db.add(transcript)
    else:
        transcript = existing
        db.execute(delete(TranscriptChunk).where(TranscriptChunk.transcript_id == transcript.id))
        db.flush()

    transcript.content_hash = content_hash
    transcript.episode_title = metadata.episode_title[:512]
    transcript.guest = metadata.guest[:255] if metadata.guest else None
    transcript.source_url = metadata.source_url[:1024] if metadata.source_url else None
    transcript.published_at = metadata.published_at
    transcript.word_count = len(cleaned.text.split())
    transcript.metadata_json = {
        "source_file": path.name,
        "suffix": path.suffix.lower(),
        "segments": len(cleaned.segments),
        **(metadata.extra or {}),
    }
    db.flush()

    for chunk, vector in zip(chunks, vectors, strict=True):
        db.add(
            TranscriptChunk(
                transcript_id=transcript.id,
                chunk_index=chunk.index,
                content=chunk.content,
                token_estimate=chunk.token_estimate,
                start_timestamp=chunk.start_timestamp,
                end_timestamp=chunk.end_timestamp,
                speaker=chunk.speaker,
                embedding=vector,
                embedding_model=embedder.model_name,
                metadata_json=chunk.metadata,
            )
        )
    db.flush()

    status = "reindexed" if existing is not None else "ingested"
    logger.info(
        "transcript_ingested",
        extra={
            "source_path": key,
            "episode_title": transcript.episode_title,
            "chunks": len(chunks),
            "status": status,
            "embedding_model": embedder.model_name,
        },
    )
    return FileOutcome(path=key, status=status, chunks=len(chunks))


def ingest_path(
    db: OrmSession,
    root: Path,
    *,
    embedder: Embedder | None = None,
    settings: Settings | None = None,
    reindex: bool = False,
    on_progress=None,
) -> IngestionSummary:
    settings = settings or get_settings()
    embedder = embedder or Embedder(settings=settings)
    started = time.perf_counter()
    summary = IngestionSummary()

    files = discover_files(root)
    summary.files_discovered = len(files)
    for path in files:
        try:
            outcome = ingest_file(
                db, path, embedder=embedder, settings=settings, reindex=reindex, root=root
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            outcome = FileOutcome(path=str(path), status="failed", detail=f"{type(exc).__name__}: {exc}")
            logger.error("transcript_ingest_failed", extra={"source_path": str(path), "error": str(exc)[:400]})
        summary.record(outcome)
        if on_progress:
            on_progress(outcome, summary)

    summary.duration_ms = (time.perf_counter() - started) * 1000
    return summary
