"""Session CRUD + session-scoped reads.

Session isolation is enforced here: every message/artifact query filters by the
path session id, so one conversation can never see another's history.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.api.deps import DbSession, ProviderDep
from app.api.serializers import artifact_to_response, message_to_response, session_to_response
from app.db.models import Artifact, Message, Session, User
from app.errors import NotFoundError
from app.logging_config import get_logger
from app.schemas import (
    ArtifactListResponse,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = get_logger(__name__)


def load_session(db: DbSession, session_id: uuid.UUID) -> Session:
    session = db.get(Session, session_id)
    if session is None:
        raise NotFoundError(f"Session {session_id} does not exist.", details={"session_id": str(session_id)})
    return session


def _counts(db: DbSession, session_id: uuid.UUID) -> tuple[int, int]:
    messages = db.scalar(
        select(func.count()).select_from(Message).where(Message.session_id == session_id)
    ) or 0
    artifacts = db.scalar(
        select(func.count()).select_from(Artifact).where(Artifact.session_id == session_id)
    ) or 0
    return messages, artifacts


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreateRequest, db: DbSession, provider: ProviderDep) -> SessionResponse:
    user: User | None = None
    if payload.user is not None:
        user = db.scalar(select(User).where(User.external_id == payload.user.external_id))
        if user is None:
            user = User(
                external_id=payload.user.external_id,
                display_name=payload.user.display_name,
                email=payload.user.email,
            )
            db.add(user)
            db.flush()

    session = Session(
        title=(payload.title or "New conversation")[:255],
        provider=provider.name,
        model=provider.model,
        user_id=user.id if user else None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("session_created", extra={"session_id": str(session.id), "provider": provider.name})
    return session_to_response(session, message_count=0, artifact_count=0)


@router.get("", response_model=SessionListResponse)
def list_sessions(db: DbSession, limit: int = 50) -> SessionListResponse:
    limit = max(1, min(limit, 200))
    rows = db.execute(
        select(Session).order_by(
            func.coalesce(Session.last_message_at, Session.created_at).desc()
        ).limit(limit)
    ).scalars().all()
    sessions = []
    for session in rows:
        messages, artifacts = _counts(db, session.id)
        sessions.append(session_to_response(session, message_count=messages, artifact_count=artifacts))
    return SessionListResponse(sessions=sessions)


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: uuid.UUID, db: DbSession) -> SessionDetailResponse:
    session = load_session(db, session_id)
    messages = db.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
    ).scalars().all()
    message_count, artifact_count = _counts(db, session.id)
    return SessionDetailResponse(
        session=session_to_response(session, message_count=message_count, artifact_count=artifact_count),
        messages=[message_to_response(message) for message in messages],
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_session(session_id: uuid.UUID, db: DbSession) -> None:
    session = load_session(db, session_id)
    db.delete(session)
    db.commit()
    logger.info("session_deleted", extra={"session_id": str(session_id)})


@router.get("/{session_id}/artifacts", response_model=ArtifactListResponse)
def list_session_artifacts(session_id: uuid.UUID, db: DbSession) -> ArtifactListResponse:
    load_session(db, session_id)
    artifacts = db.execute(
        select(Artifact).where(Artifact.session_id == session_id).order_by(Artifact.created_at.desc())
    ).scalars().all()
    return ArtifactListResponse(artifacts=[artifact_to_response(a) for a in artifacts])
