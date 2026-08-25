"""Retrieval data contracts shared by ingestion, retrieval and the agent layer."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class RetrievedChunk:
    """A transcript chunk plus everything needed to trace it back to its source."""

    chunk_id: uuid.UUID
    transcript_id: uuid.UUID
    chunk_index: int
    content: str
    score: float
    episode_title: str
    guest: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    start_timestamp: str | None = None
    end_timestamp: str | None = None
    speaker: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def citation_label(self) -> str:
        parts = [self.episode_title]
        if self.guest:
            parts.append(f"with {self.guest}")
        if self.start_timestamp:
            parts.append(f"@{self.start_timestamp}")
        return " ".join(parts)


@dataclass(slots=True)
class RetrievalResult:
    query: str
    top_k: int
    score_threshold: float
    chunks: list[RetrievedChunk]
    latency_ms: float
    candidates_considered: int = 0
    duplicates_removed: int = 0
    below_threshold: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.chunks


class Retriever(Protocol):
    """Interface a coding agent can re-implement (hybrid search, other stores)
    without touching the API or agent layers."""

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> RetrievalResult: ...

    def stats(self) -> dict[str, Any]: ...
