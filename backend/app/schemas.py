"""Request/response contracts for the public API.

These pydantic models are the single source of truth for the HTTP contract and
are mirrored by the frontend Zod schemas in `src/lib/api/schemas.ts`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Mirrors app.agent.contracts.Capability exactly — one vocabulary end to end.
Capability = Literal["qa", "essay", "artifact"]
ArtifactKind = Literal["markdown", "html"]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Health ---------------------------------------------------------------


class ComponentHealth(ApiModel):
    status: Literal["ok", "degraded", "error"]
    detail: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded", "error"]
    version: str
    environment: str
    provider: str
    model: str
    embedding_model: str
    agent_runtime: str
    components: dict[str, ComponentHealth]


# --- Sessions -------------------------------------------------------------


class UserMetadata(ApiModel):
    external_id: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)


class SessionCreateRequest(ApiModel):
    title: str | None = Field(default=None, max_length=255)
    user: UserMetadata | None = None


class SessionResponse(ApiModel):
    id: uuid.UUID
    title: str
    provider: str
    model: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    message_count: int = 0
    artifact_count: int = 0


class SessionListResponse(ApiModel):
    sessions: list[SessionResponse]


# --- Citations / retrieval ------------------------------------------------


class Citation(ApiModel):
    chunk_id: uuid.UUID
    transcript_id: uuid.UUID
    episode_title: str
    guest: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    chunk_index: int
    start_timestamp: str | None = None
    end_timestamp: str | None = None
    score: float
    excerpt: str


class RetrievalRequest(ApiModel):
    query: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=25)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class RetrievalResponse(ApiModel):
    query: str
    top_k: int
    score_threshold: float
    chunk_count: int
    latency_ms: float
    results: list[Citation]


# --- Chat -----------------------------------------------------------------


class MessageResponse(ApiModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    citations: list[Citation] = Field(default_factory=list)
    capability: Capability | None = None
    grounded: bool = True
    provider: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    artifact_id: uuid.UUID | None = None


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=8000)
    top_k: int | None = Field(default=None, ge=1, le=25)
    # Optional explicit capability request; when omitted the agent routes.
    capability: Capability | None = None
    artifact_kind: ArtifactKind | None = None


class ChatResponse(ApiModel):
    session_id: uuid.UUID
    user_message: MessageResponse
    assistant_message: MessageResponse
    artifact: "ArtifactResponse | None" = None


class SessionDetailResponse(ApiModel):
    session: SessionResponse
    messages: list[MessageResponse]


# --- Artifacts ------------------------------------------------------------


class ArtifactResponse(ApiModel):
    id: uuid.UUID
    session_id: uuid.UUID
    message_id: uuid.UUID | None
    kind: ArtifactKind
    title: str
    content: str
    byte_size: int
    created_at: datetime
    citations: list[Citation] = Field(default_factory=list)


class ArtifactListResponse(ApiModel):
    artifacts: list[ArtifactResponse]


ChatResponse.model_rebuild()
