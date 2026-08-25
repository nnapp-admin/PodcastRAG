"""SQLAlchemy models. The authoritative schema lives in the Alembic migration;
these models mirror it and are used by the application at runtime.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dimensions

# Portable column types. PostgreSQL is the production database (and the only one
# that can host `vector`); the SQLite variants exist so the API/persistence test
# suite can run without a live PostgreSQL, using the exact same models.
GUID = Uuid(as_uuid=True)
JsonDict = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    metadata_json: Mapped[dict] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JsonDict, default=dict, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_sessions_last_message_at", "last_message_at"),)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # grounding: citations, retrieval stats, provider/model, latency, capability
    metadata_json: Mapped[dict] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    session: Mapped[Session] = relationship(back_populates="messages")
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    episode_title: Mapped[str] = mapped_column(String(512), nullable=False)
    guest: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    chunks: Mapped[list["TranscriptChunk"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_transcripts_content_hash", "content_hash"),)


class TranscriptChunk(Base, TimestampMixin):
    __tablename__ = "transcript_chunks"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_timestamp: Mapped[str | None] = mapped_column(String(32))
    end_timestamp: Mapped[str | None] = mapped_column(String(32))
    speaker: Mapped[str | None] = mapped_column(String(255))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    transcript: Mapped[Transcript] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("transcript_id", "chunk_index", name="uq_chunk_transcript_index"),
        Index("ix_chunks_transcript", "transcript_id"),
    )


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("messages.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # markdown | html
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generation_latency_ms: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict] = mapped_column("metadata", JsonDict, default=dict, nullable=False)

    session: Mapped[Session] = relationship(back_populates="artifacts")
    message: Mapped[Message | None] = relationship(back_populates="artifacts")

    __table_args__ = (Index("ix_artifacts_session_created", "session_id", "created_at"),)
