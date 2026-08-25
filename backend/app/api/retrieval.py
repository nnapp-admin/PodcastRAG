"""Raw retrieval endpoint — useful for debugging grounding and for the
evaluator to inspect ranking without going through the model.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import RetrieverDep
from app.api.serializers import chunk_to_citation
from app.schemas import RetrievalRequest, RetrievalResponse

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/search", response_model=RetrievalResponse)
def search(payload: RetrievalRequest, retriever: RetrieverDep) -> RetrievalResponse:
    result = retriever.search(
        payload.query, top_k=payload.top_k, score_threshold=payload.score_threshold
    )
    return RetrievalResponse(
        query=result.query,
        top_k=result.top_k,
        score_threshold=result.score_threshold,
        chunk_count=len(result.chunks),
        latency_ms=round(result.latency_ms, 2),
        results=[chunk_to_citation(chunk) for chunk in result.chunks],
    )
