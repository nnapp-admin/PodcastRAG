"""Shared test fixtures.

The suite runs with NO external services: SQLite replaces PostgreSQL, and fake
implementations of the two boundary interfaces (`LLMProvider`, `Retriever`)
replace Ollama/Anthropic and pgvector. Because the API and agent layers depend
only on those interfaces, the tests exercise the real chat turn, real agent
runtime, real skills, real artifact pipeline and real persistence.

Tests that genuinely need PostgreSQL/pgvector or Ollama are marked
`postgres` / `ollama` and skip unless the service is configured.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest

# Environment must be set before app.config caches Settings.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("AGENT_RUNTIME", "local")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("RETRIEVAL_SCORE_THRESHOLD", "0.2")
os.environ.setdefault("AGENT_MAX_TOOL_STEPS", "3")
# Tiny embeddings keep the suite fast; the Embedder validates against this value.
os.environ.setdefault("EMBEDDING_DIMENSIONS", "8")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base  # noqa: E402
from app.db.session import build_engine, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.providers.base import CompletionResult, LLMProvider, ToolCall, ToolSpec  # noqa: E402
from app.retrieval.types import RetrievalResult, RetrievedChunk  # noqa: E402

# --- Fakes ----------------------------------------------------------------


def make_chunk(
    content: str,
    *,
    score: float = 0.82,
    episode_title: str = "How to find product-market fit",
    guest: str | None = "Ada Lovelace",
    index: int = 0,
    transcript_id: uuid.UUID | None = None,
    source_url: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        transcript_id=transcript_id or uuid.uuid4(),
        chunk_index=index,
        content=content,
        score=score,
        episode_title=episode_title,
        guest=guest,
        source_url=source_url or "https://example.com/episode",
        published_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        start_timestamp="00:12:30",
        end_timestamp="00:14:02",
        speaker=guest,
        metadata={},
    )


DEFAULT_CHUNKS = [
    make_chunk(
        "The clearest signal of product-market fit is retention: cohorts flatten "
        "instead of decaying, and users come back without being nudged.",
        score=0.88,
        index=0,
    ),
    make_chunk(
        "Before PMF your only job is learning velocity. Talk to fifteen users a "
        "week and ship something every week based on what you heard.",
        score=0.74,
        episode_title="Growth loops that actually compound",
        guest="Grace Hopper",
        index=1,
    ),
]


class FakeRetriever:
    """In-memory Retriever implementation with recorded calls."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None, *, empty: bool = False) -> None:
        self.chunks = [] if empty else list(chunks if chunks is not None else DEFAULT_CHUNKS)
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> RetrievalResult:
        self.calls.append({"query": query, "top_k": top_k, "score_threshold": score_threshold})
        threshold = 0.2 if score_threshold is None else score_threshold
        kept = [chunk for chunk in self.chunks if chunk.score >= threshold][: (top_k or 6)]
        return RetrievalResult(
            query=query,
            top_k=top_k or 6,
            score_threshold=threshold,
            chunks=kept,
            latency_ms=1.5,
            candidates_considered=len(self.chunks),
            duplicates_removed=0,
            below_threshold=len(self.chunks) - len(kept),
        )

    def stats(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.chunks else "degraded",
            "detail": None,
            "extra": {"transcripts": 1 if self.chunks else 0, "chunks": len(self.chunks)},
        }


class FakeProvider(LLMProvider):
    """Scripted provider. `responses` is a queue of str (text) or list[ToolCall]."""

    name = "fake"

    def __init__(self, responses: list[Any] | None = None, *, dimensions: int = 8) -> None:
        super().__init__(model="fake-model", timeout=5.0, max_output_tokens=512, temperature=0.0)
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.dimensions = dimensions

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec] | None = None,
        max_output_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls.append({"system": system, "messages": messages, "tools": [t.name for t in tools or []]})
        nxt = self.responses.pop(0) if self.responses else "Grounded answer from the transcripts [1]."
        tool_calls: list[ToolCall] = []
        text = ""
        if isinstance(nxt, list):
            tool_calls = nxt
        else:
            text = str(nxt)
        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            latency_ms=2.0,
            provider=self.name,
            model=self.model,
            usage={},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float((len(t) + i) % 7) / 7.0] * self.dimensions for i, t in enumerate(texts)]

    def healthcheck(self) -> dict[str, Any]:
        return {"status": "ok", "detail": None, "extra": {}}


# --- Fixtures -------------------------------------------------------------


@pytest.fixture()
def db_sessionmaker():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db(db_sessionmaker) -> Iterator[Any]:
    session = db_sessionmaker()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def retriever() -> FakeRetriever:
    return FakeRetriever()


@pytest.fixture()
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture()
def client(db_sessionmaker, retriever, provider) -> Iterator[TestClient]:
    app = create_app()
    app.state.retriever_override = retriever
    app.state.provider_override = provider

    def override_get_db() -> Iterator[Any]:
        session = db_sessionmaker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.retriever = retriever  # type: ignore[attr-defined]
        test_client.provider = provider  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def session_id(client: TestClient) -> str:
    response = client.post("/sessions", json={"title": "New conversation"})
    assert response.status_code == 201, response.text
    return response.json()["id"]
