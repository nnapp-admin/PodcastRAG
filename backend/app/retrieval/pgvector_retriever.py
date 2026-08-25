"""pgvector-backed retrieval.

Pipeline: query -> embed -> cosine ANN search (top_k * multiplier candidates)
-> optional rerank -> dedupe -> score threshold -> top_k.

`score` is cosine similarity in [0, 1] (1 - cosine distance), so the
configurable threshold is directly interpretable.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession

from app.config import Settings, get_settings
from app.db.models import Transcript, TranscriptChunk
from app.errors import DatabaseUnavailableError
from app.logging_config import get_logger
from app.retrieval.embedder import Embedder
from app.retrieval.reranker import build_reranker
from app.retrieval.types import RetrievalResult, RetrievedChunk

logger = get_logger(__name__)


class PgVectorRetriever:
    """Implements the `Retriever` protocol."""

    def __init__(
        self,
        db: OrmSession,
        *,
        embedder: Embedder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(settings=self.settings)
        self.reranker = build_reranker(self.settings.retrieval_reranker)

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> RetrievalResult:
        resolved_top_k = top_k or self.settings.retrieval_top_k
        resolved_threshold = (
            self.settings.retrieval_score_threshold if score_threshold is None else score_threshold
        )
        started = time.perf_counter()
        logger.info(
            "retrieval_start",
            extra={"query_chars": len(query), "top_k": resolved_top_k, "score_threshold": resolved_threshold},
        )

        query_vector = self.embedder.embed_query(query)
        candidate_limit = max(resolved_top_k * self.settings.retrieval_candidate_multiplier, resolved_top_k)

        distance = TranscriptChunk.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(TranscriptChunk, Transcript, distance)
            .join(Transcript, Transcript.id == TranscriptChunk.transcript_id)
            .order_by(distance)
            .limit(candidate_limit)
        )
        try:
            rows = self.db.execute(stmt).all()
        except SQLAlchemyError as exc:
            logger.error("retrieval_db_error", extra={"error_type": type(exc).__name__})
            raise DatabaseUnavailableError(details={"stage": "retrieval"}) from exc

        candidates = [
            RetrievedChunk(
                chunk_id=chunk.id,
                transcript_id=transcript.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=round(max(0.0, 1.0 - float(dist)), 6),
                episode_title=transcript.episode_title,
                guest=transcript.guest,
                source_url=transcript.source_url,
                published_at=transcript.published_at,
                start_timestamp=chunk.start_timestamp,
                end_timestamp=chunk.end_timestamp,
                speaker=chunk.speaker,
                metadata={"embedding_model": chunk.embedding_model},
            )
            for chunk, transcript, dist in rows
        ]

        ranked = self.reranker.rerank(query, candidates)
        deduped, duplicates_removed = _dedupe(ranked)
        kept = [chunk for chunk in deduped if chunk.score >= resolved_threshold][:resolved_top_k]
        below_threshold = len(deduped) - len([c for c in deduped if c.score >= resolved_threshold])
        latency_ms = (time.perf_counter() - started) * 1000

        logger.info(
            "retrieval_end",
            extra={
                "candidates": len(candidates),
                "duplicates_removed": duplicates_removed,
                "below_threshold": below_threshold,
                "chunks_retrieved": len(kept),
                "top_score": kept[0].score if kept else None,
                "latency_ms": round(latency_ms, 1),
                "reranker": self.settings.retrieval_reranker,
            },
        )
        return RetrievalResult(
            query=query,
            top_k=resolved_top_k,
            score_threshold=resolved_threshold,
            chunks=kept,
            latency_ms=latency_ms,
            candidates_considered=len(candidates),
            duplicates_removed=duplicates_removed,
            below_threshold=below_threshold,
        )

    def stats(self) -> dict[str, Any]:
        try:
            transcripts = self.db.scalar(select(func.count()).select_from(Transcript)) or 0
            chunks = self.db.scalar(select(func.count()).select_from(TranscriptChunk)) or 0
            models = self.db.execute(
                text("SELECT DISTINCT embedding_model FROM transcript_chunks")
            ).scalars().all()
        except SQLAlchemyError as exc:
            return {"status": "error", "detail": f"{type(exc).__name__}: retrieval index unavailable"}
        status = "ok" if chunks else "degraded"
        detail = None if chunks else "No transcript chunks indexed. Run the ingestion CLI."
        return {
            "status": status,
            "detail": detail,
            "extra": {
                "transcripts": transcripts,
                "chunks": chunks,
                "embedding_models": list(models),
                "top_k": self.settings.retrieval_top_k,
                "score_threshold": self.settings.retrieval_score_threshold,
                "reranker": self.settings.retrieval_reranker,
            },
        }


def _dedupe(chunks: list[RetrievedChunk]) -> tuple[list[RetrievedChunk], int]:
    """Drop exact chunk repeats and near-identical overlapping text."""
    seen_ids: set[Any] = set()
    seen_fingerprints: set[str] = set()
    kept: list[RetrievedChunk] = []
    removed = 0
    for chunk in chunks:
        fingerprint = " ".join(chunk.content.lower().split())[:220]
        if chunk.chunk_id in seen_ids or fingerprint in seen_fingerprints:
            removed += 1
            continue
        seen_ids.add(chunk.chunk_id)
        seen_fingerprints.add(fingerprint)
        kept.append(chunk)
    return kept, removed
