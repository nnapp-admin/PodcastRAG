"""Optional reranking stage.

`none`    -> keep vector order (pure ANN ranking)
`lexical` -> blend cosine similarity with lexical overlap of query terms, which
             measurably helps small local embedding models on keyword-heavy
             product/growth questions. Deliberately cheap: no extra model call.

A coding agent can add a cross-encoder implementation behind `Reranker`
without touching callers.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.retrieval.types import RetrievedChunk

WORD = re.compile(r"[a-z0-9']+")
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
    "what", "how", "why", "do", "does", "did", "with", "about", "should", "i",
    "we", "you", "it", "that", "this", "be", "can", "at", "as", "from", "my",
}


def _terms(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


class Reranker(Protocol):
    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...


class NoopReranker:
    name = "none"

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return chunks


class LexicalReranker:
    name = "lexical"

    def __init__(self, vector_weight: float = 0.8, lexical_weight: float = 0.2) -> None:
        self.vector_weight = vector_weight
        self.lexical_weight = lexical_weight

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        query_terms = _terms(query)
        if not query_terms or not chunks:
            return chunks
        for chunk in chunks:
            overlap = len(query_terms & _terms(chunk.content)) / len(query_terms)
            blended = self.vector_weight * chunk.score + self.lexical_weight * overlap
            chunk.metadata = {
                **chunk.metadata,
                "vector_score": round(chunk.score, 4),
                "lexical_overlap": round(overlap, 4),
            }
            chunk.score = round(min(1.0, blended), 6)
        return sorted(chunks, key=lambda c: c.score, reverse=True)


def build_reranker(name: str) -> Reranker:
    return LexicalReranker() if name == "lexical" else NoopReranker()
