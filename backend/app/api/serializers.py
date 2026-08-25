"""Domain -> API serialisation. One place converts retrieval/agent/db objects
into the pydantic contracts, so citations can never drift between endpoints.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.models import Artifact, Message, Session
from app.retrieval.types import RetrievedChunk
from app.schemas import ArtifactResponse, Citation, MessageResponse, SessionResponse

EXCERPT_CHARS = 700


def chunk_to_citation(chunk: RetrievedChunk) -> Citation:
    return Citation(
        chunk_id=chunk.chunk_id,
        transcript_id=chunk.transcript_id,
        episode_title=chunk.episode_title,
        guest=chunk.guest,
        source_url=chunk.source_url,
        published_at=chunk.published_at,
        chunk_index=chunk.chunk_index,
        start_timestamp=chunk.start_timestamp,
        end_timestamp=chunk.end_timestamp,
        score=chunk.score,
        excerpt=chunk.content.strip()[:EXCERPT_CHARS],
    )


def citations_to_json(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    """Persisted form of a citation (JSON-safe, stored on the message row)."""
    return [chunk_to_citation(chunk).model_dump(mode="json") for chunk in chunks]


def message_to_response(message: Message) -> MessageResponse:
    metadata = message.metadata_json or {}
    raw_citations = metadata.get("citations") or []
    citations = [Citation.model_validate(item) for item in raw_citations]
    artifact_id = metadata.get("artifact_id")
    return MessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        citations=citations,
        capability=metadata.get("capability"),
        grounded=bool(metadata.get("grounded", True)),
        provider=metadata.get("provider"),
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        artifact_id=uuid.UUID(artifact_id) if isinstance(artifact_id, str) else artifact_id,
    )


def session_to_response(session: Session, *, message_count: int, artifact_count: int) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        title=session.title,
        provider=session.provider,
        model=session.model,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_message_at=session.last_message_at,
        message_count=message_count,
        artifact_count=artifact_count,
    )


def artifact_to_response(artifact: Artifact) -> ArtifactResponse:
    metadata = artifact.metadata_json or {}
    citations = [Citation.model_validate(item) for item in (metadata.get("citations") or [])]
    return ArtifactResponse(
        id=artifact.id,
        session_id=artifact.session_id,
        message_id=artifact.message_id,
        kind=artifact.kind,  # type: ignore[arg-type]
        title=artifact.title,
        content=artifact.content,
        byte_size=artifact.byte_size,
        created_at=artifact.created_at,
        citations=citations,
    )
