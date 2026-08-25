"""FastAPI dependencies.

The API layer depends on interfaces only (`Retriever`, `LLMProvider`,
`AgentRuntime`), so tests can substitute fakes at the boundary and provider /
runtime switching stays a configuration concern.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session as OrmSession

from app.agent.contracts import AgentRuntime
from app.agent.runtime import build_agent_runtime
from app.config import Settings, get_settings
from app.db.session import get_db
from app.providers import get_provider
from app.providers.base import LLMProvider
from app.retrieval.pgvector_retriever import PgVectorRetriever
from app.retrieval.types import Retriever

DbSession = Annotated[OrmSession, Depends(get_db)]


def settings_dep() -> Settings:
    return get_settings()


def provider_dep(request: Request) -> LLMProvider:
    """Overridable in tests via `app.dependency_overrides`."""
    override = getattr(request.app.state, "provider_override", None)
    return override or get_provider()


def retriever_dep(request: Request, db: DbSession) -> Retriever:
    override = getattr(request.app.state, "retriever_override", None)
    if override is not None:
        return override
    return PgVectorRetriever(db)


def agent_dep(
    retriever: Annotated[Retriever, Depends(retriever_dep)],
    provider: Annotated[LLMProvider, Depends(provider_dep)],
) -> AgentRuntime:
    return build_agent_runtime(retriever, provider=provider)


SettingsDep = Annotated[Settings, Depends(settings_dep)]
ProviderDep = Annotated[LLMProvider, Depends(provider_dep)]
RetrieverDep = Annotated[Retriever, Depends(retriever_dep)]
AgentDep = Annotated[AgentRuntime, Depends(agent_dep)]
