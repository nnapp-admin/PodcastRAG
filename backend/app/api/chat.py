"""The chat turn: persist user message -> run the agent -> persist the grounded
assistant message (+ artifact) -> return both.

Only the addressed session's history is loaded, so sessions cannot leak context.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.agent.contracts import AgentRequest, AgentResult
from app.api.deps import AgentDep, DbSession, RetrieverDep
from app.api.serializers import artifact_to_response, citations_to_json, message_to_response
from app.api.sessions import load_session
from app.db.models import Artifact, Message, Session
from app.errors import KnowledgeBaseEmptyError
from app.logging_config import get_logger, session_id_var
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/sessions", tags=["chat"])
logger = get_logger(__name__)

HISTORY_LIMIT = 20
CAPABILITY_TO_API = {"qa": "qa", "essay": "essay", "artifact": "artifact"}


@router.post("/{session_id}/messages", response_model=ChatResponse)
def create_message(
    session_id: uuid.UUID,
    payload: ChatRequest,
    db: DbSession,
    agent: AgentDep,
    retriever: RetrieverDep,
) -> ChatResponse:
    session = load_session(db, session_id)
    session_id_var.set(str(session_id))

    stats = retriever.stats()
    if stats.get("extra", {}).get("chunks", 1) == 0:
        raise KnowledgeBaseEmptyError(details=stats.get("extra", {}))

    user_message = Message(session_id=session.id, role="user", content=payload.message, metadata_json={})
    db.add(user_message)
    db.flush()

    history = _load_history(db, session.id, exclude_id=user_message.id)

    result: AgentResult = agent.run(
        AgentRequest(
            question=payload.message,
            history=history,
            requested_capability=payload.capability,
            top_k=payload.top_k,
        )
    )

    artifact_row: Artifact | None = None
    artifact_id: uuid.UUID | None = None

    if result.artifact is not None:
        artifact_id = uuid.uuid4()
        artifact_row = Artifact(
            id=artifact_id,
            session_id=session.id,
            kind=result.artifact.kind,
            title=result.artifact.title,
            content=result.artifact.content,
            byte_size=result.artifact.report.byte_size,
            generation_latency_ms=result.artifact.latency_ms,
            metadata_json={
                "citations": citations_to_json(result.citations),
                "sanitized": result.artifact.report.sanitized,
                "removed": result.artifact.report.removed,
            },
        )
    elif result.capability == "essay" and result.grounded:
        # The essay itself is the deliverable: persist it as a markdown artifact
        # so the Artifact Viewer can render and export it.
        artifact_id = uuid.uuid4()
        artifact_row = Artifact(
            id=artifact_id,
            session_id=session.id,
            kind="markdown",
            title=str(result.notes.get("essay_title") or "Ship 30 essay")[:255],
            content=result.text,
            byte_size=len(result.text.encode("utf-8")),
            generation_latency_ms=result.generation_latency_ms,
            metadata_json={
                "citations": citations_to_json(result.citations),
                "skill": "ship30",
                "word_count": result.word_count,
            },
        )

    assistant_message_id = uuid.uuid4()
    assistant_metadata: dict[str, Any] = {
        "citations": citations_to_json(result.citations),
        "capability": CAPABILITY_TO_API.get(result.capability, result.capability),
        "grounded": result.grounded,
        "provider": result.provider,
        "model": result.model,
        "runtime": result.runtime,
        "latency_ms": round(result.latency_ms, 1),
        "retrieval_latency_ms": round(result.retrieval_latency_ms, 1),
        "generation_latency_ms": round(result.generation_latency_ms, 1),
        "tool_calls": [
            {"name": call.name, "ok": call.ok, "latency_ms": round(call.latency_ms, 1)}
            for call in result.tool_invocations
        ],
        "word_count": result.word_count,
        "notes": result.notes,
    }
    if artifact_id is not None:
        assistant_metadata["artifact_id"] = str(artifact_id)

    assistant_message = Message(
        id=assistant_message_id,
        session_id=session.id,
        role="assistant",
        content=result.text,
        metadata_json=assistant_metadata,
    )
    db.add(assistant_message)
    db.flush()

    if artifact_row is not None:
        artifact_row.message_id = assistant_message_id
        db.add(artifact_row)
        db.flush()

    if session.title in {"New conversation", ""}:
        session.title = payload.message.strip()[:80]
    session.last_message_at = assistant_message.created_at or user_message.created_at

    db.commit()

    logger.info(
        "chat_turn_complete",
        extra={
            "session_id": str(session.id),
            "capability": result.capability,
            "grounded": result.grounded,
            "citations": len(result.citations),
            "artifact": artifact_row.kind if artifact_row else None,
            "latency_ms": round(result.latency_ms, 1),
        },
    )

    return ChatResponse(
        session_id=session.id,
        user_message=message_to_response(user_message),
        assistant_message=message_to_response(assistant_message),
        artifact=artifact_to_response(artifact_row) if artifact_row else None,
    )


def _load_history(db: DbSession, session_id: uuid.UUID, *, exclude_id: uuid.UUID) -> list[dict[str, str]]:
    rows = db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.id != exclude_id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_LIMIT)
    ).scalars().all()
    return [{"role": message.role, "content": message.content} for message in reversed(rows)]


__all__ = ["router", "Session"]
