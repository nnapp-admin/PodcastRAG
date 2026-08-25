"""initial schema: users, sessions, messages, transcripts, transcript_chunks, artifacts

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIMENSIONS", "768"))
JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_id", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("email", sa.String(320)),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )

    op.create_table(
        "sessions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(255), nullable=False, server_default="New conversation"),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_last_message_at", "sessions", ["last_message_at"])

    op.create_table(
        "messages",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_messages_session_created", "messages", ["session_id", "created_at"])

    op.create_table(
        "transcripts",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("episode_title", sa.String(512), nullable=False),
        sa.Column("guest", sa.String(255)),
        sa.Column("source_url", sa.String(1024)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_transcripts_content_hash", "transcripts", ["content_hash"])

    op.create_table(
        "transcript_chunks",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("transcript_id", UUID, sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_timestamp", sa.String(32)),
        sa.Column("end_timestamp", sa.String(32)),
        sa.Column("speaker", sa.String(255)),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
        sa.UniqueConstraint("transcript_id", "chunk_index", name="uq_chunk_transcript_index"),
    )
    op.create_index("ix_chunks_transcript", "transcript_chunks", ["transcript_id"])
    # Cosine-distance ANN index. Lists=100 is fine for the corpus sizes in this
    # engagement; increase with the corpus.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_cosine ON transcript_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "artifacts",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", UUID, sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generation_latency_ms", sa.Float()),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_artifacts_session_created", "artifacts", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_table("artifacts")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_cosine")
    op.drop_table("transcript_chunks")
    op.drop_table("transcripts")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("users")
