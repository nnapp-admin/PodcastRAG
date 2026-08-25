"""Aggregate health: api, database, provider, embeddings, retrieval index.

Never raises — a degraded dependency is reported, not thrown, so the UI can
render an accurate connection banner.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.agent.runtime import resolve_runtime_name
from app.api.deps import ProviderDep, RetrieverDep, SettingsDep
from app.db.session import database_health
from app.schemas import ComponentHealth, HealthResponse

router = APIRouter(tags=["health"])

VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep, provider: ProviderDep, retriever: RetrieverDep) -> HealthResponse:
    components: dict[str, ComponentHealth] = {"api": ComponentHealth(status="ok")}

    db_result = database_health()
    components["database"] = ComponentHealth(
        status="ok" if db_result.get("status") == "ok" else "error",
        detail=db_result.get("detail"),
        extra={"pgvector": db_result.get("pgvector", False)},
    )

    provider_result = provider.healthcheck()
    components["provider"] = ComponentHealth(
        status=provider_result.get("status", "error"),  # type: ignore[arg-type]
        detail=provider_result.get("detail"),
        extra={k: v for k, v in provider_result.items() if k not in {"status", "detail"}},
    )

    try:
        retrieval_result = retriever.stats()
    except Exception as exc:  # never let /health fail
        retrieval_result = {"status": "error", "detail": f"{type(exc).__name__}"}
    components["retrieval"] = ComponentHealth(
        status=retrieval_result.get("status", "error"),  # type: ignore[arg-type]
        detail=retrieval_result.get("detail"),
        extra=retrieval_result.get("extra", {}),
    )

    runtime_name, fallback_reason = resolve_runtime_name(settings)
    components["agent"] = ComponentHealth(
        status="ok",
        detail=fallback_reason,
        extra={"runtime": runtime_name, "configured": settings.agent_runtime},
    )

    statuses = {component.status for component in components.values()}
    overall = "error" if "error" in statuses else ("degraded" if "degraded" in statuses else "ok")

    return HealthResponse(
        status=overall,  # type: ignore[arg-type]
        version=VERSION,
        environment=settings.environment,
        provider=provider.name,
        model=provider.model,
        embedding_model=settings.ollama_embedding_model,
        agent_runtime=runtime_name,
        components=components,
    )
