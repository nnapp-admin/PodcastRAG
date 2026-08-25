"""Retrieval: reranking, thresholds, deduplication, embedder batching.

The pgvector-backed retriever itself needs a live PostgreSQL + pgvector, so its
integration test is marked `postgres` and skips without TEST_DATABASE_URL.
"""

from __future__ import annotations

import os

import pytest

from app.retrieval.embedder import Embedder
from app.retrieval.reranker import LexicalReranker, NoopReranker, build_reranker

from .conftest import FakeProvider, FakeRetriever, make_chunk


# --- reranker -------------------------------------------------------------


def test_lexical_reranker_promotes_term_overlap():
    chunks = [
        make_chunk("Pricing experiments and packaging tiers.", score=0.60, index=0),
        make_chunk("Retention curves flatten once you have product-market fit.", score=0.58, index=1),
    ]
    reranked = LexicalReranker().rerank("retention curves flatten", chunks)
    assert "Retention curves" in reranked[0].content


def test_noop_reranker_preserves_order():
    chunks = [make_chunk("a", score=0.9), make_chunk("b", score=0.8)]
    assert [c.content for c in NoopReranker().rerank("anything", chunks)] == ["a", "b"]


def test_build_reranker_selects_by_name():
    assert isinstance(build_reranker("lexical"), LexicalReranker)
    assert isinstance(build_reranker("none"), NoopReranker)
    assert isinstance(build_reranker("unknown-name"), NoopReranker)


def test_reranker_handles_empty_input():
    assert LexicalReranker().rerank("query", []) == []


# --- thresholds / top_k ---------------------------------------------------


def test_threshold_filters_weak_matches():
    retriever = FakeRetriever(
        [make_chunk("strong", score=0.8, index=0), make_chunk("weak", score=0.1, index=1)]
    )
    result = retriever.search("query", score_threshold=0.5)
    assert [chunk.content for chunk in result.chunks] == ["strong"]
    assert result.below_threshold == 1
    assert result.is_empty is False


def test_empty_index_reports_empty_result():
    result = FakeRetriever(empty=True).search("query")
    assert result.is_empty
    assert result.chunks == []


def test_top_k_is_respected():
    chunks = [make_chunk(f"chunk {i}", score=0.9, index=i) for i in range(10)]
    assert len(FakeRetriever(chunks).search("query", top_k=3).chunks) == 3


# --- embedder -------------------------------------------------------------


def test_embedder_batches_and_preserves_order():
    provider = FakeProvider()
    calls: list[int] = []
    original = provider.embed

    def counting_embed(texts):
        calls.append(len(texts))
        return original(texts)

    provider.embed = counting_embed  # type: ignore[method-assign]
    vectors = Embedder(provider).embed_documents([f"text {i}" for i in range(5)], batch_size=2)
    assert len(vectors) == 5
    assert calls == [2, 2, 1]
    assert all(len(vector) == provider.dimensions for vector in vectors)


def test_embedder_handles_empty_input():
    assert Embedder(FakeProvider()).embed_documents([]) == []


def test_query_and_document_embeddings_use_the_same_provider_model():
    embedder = Embedder(FakeProvider())
    query = embedder.embed_query("retention")
    document = embedder.embed_documents(["retention"])[0]
    assert len(query) == len(document)


# --- pgvector integration (opt-in) ---------------------------------------


@pytest.mark.postgres
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
def test_pgvector_retriever_returns_ranked_chunks():
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base, Transcript, TranscriptChunk
    from app.db.session import build_engine
    from app.retrieval.pgvector_retriever import PgVectorRetriever

    engine = build_engine(os.environ["TEST_DATABASE_URL"])
    Base.metadata.create_all(engine)
    provider = FakeProvider(dimensions=768)
    with sessionmaker(bind=engine)() as db:
        transcript = Transcript(source_path="test.vtt", episode_title="Retention deep dive")
        db.add(transcript)
        db.flush()
        for index, text in enumerate(["Retention is the PMF signal.", "Pricing tiers and packaging."]):
            db.add(
                TranscriptChunk(
                    transcript_id=transcript.id,
                    chunk_index=index,
                    content=text,
                    embedding=provider.embed([text])[0],
                    token_count=10,
                )
            )
        db.commit()

        retriever = PgVectorRetriever(db, provider=provider)
        result = retriever.search("retention", top_k=2, score_threshold=0.0)
        assert result.chunks
        assert retriever.stats()["extra"]["chunks"] == 2
