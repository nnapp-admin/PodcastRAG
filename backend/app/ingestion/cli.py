"""Transcript ingestion CLI.

    python -m app.ingestion.cli --path ./data/transcripts
    python -m app.ingestion.cli --path ./data/transcripts --reindex
    python -m app.ingestion.cli --stats

Run it from the `backend/` directory (or inside the backend container) so
DATABASE_URL and OLLAMA_BASE_URL resolve the same way the API resolves them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db.models import Transcript, TranscriptChunk
from app.db.session import SessionLocal, database_health
from app.errors import AppError
from app.ingestion.pipeline import FileOutcome, IngestionSummary, ingest_path
from app.logging_config import configure_logging
from app.retrieval.embedder import Embedder


def _print_progress(outcome: FileOutcome, summary: IngestionSummary) -> None:
    marker = {"ingested": "+", "reindexed": "~", "skipped": "=", "failed": "!"}[outcome.status]
    suffix = f" ({outcome.chunks} chunks)" if outcome.chunks else ""
    detail = f" - {outcome.detail}" if outcome.detail else ""
    print(f"  [{marker}] {outcome.path}{suffix}{detail}", flush=True)


def _stats() -> int:
    with SessionLocal() as db:
        transcripts = db.scalar(select(func.count()).select_from(Transcript)) or 0
        chunks = db.scalar(select(func.count()).select_from(TranscriptChunk)) or 0
        rows = db.execute(
            select(Transcript.episode_title, Transcript.guest, func.count(TranscriptChunk.id))
            .join(TranscriptChunk, TranscriptChunk.transcript_id == Transcript.id)
            .group_by(Transcript.id)
            .order_by(Transcript.episode_title)
        ).all()
    print(f"Transcripts: {transcripts}   Chunks: {chunks}")
    for title, guest, count in rows:
        print(f"  - {title}{f' (guest: {guest})' if guest else ''}: {count} chunks")
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="python -m app.ingestion.cli",
        description="Ingest Lenny's Podcast transcripts into PostgreSQL/pgvector.",
    )
    parser.add_argument("--path", default=settings.transcripts_path, help="Transcript file or folder.")
    parser.add_argument("--reindex", action="store_true", help="Re-chunk and re-embed even if unchanged.")
    parser.add_argument("--stats", action="store_true", help="Print index statistics and exit.")
    parser.add_argument("--quiet", action="store_true", help="Only print the final summary.")
    args = parser.parse_args(argv)

    configure_logging("WARNING" if args.quiet else settings.log_level)

    db_state = database_health()
    if db_state.get("status") != "ok":
        print(
            f"ERROR: cannot reach the database ({db_state.get('detail')}).\n"
            f"       DATABASE_URL={settings.database_url.split('@')[-1]}\n"
            "       Start it with `docker compose up -d db` and run `alembic upgrade head`.",
            file=sys.stderr,
        )
        return 2
    if not db_state.get("pgvector"):
        print(
            "ERROR: the `vector` extension is not installed in this database.\n"
            "       Run `alembic upgrade head` (the first migration creates it).",
            file=sys.stderr,
        )
        return 2

    if args.stats:
        return _stats()

    embedder = Embedder(settings=settings)
    embed_state = embedder.healthcheck()
    if embed_state.get("status") == "error":
        print(
            f"ERROR: the embedding provider is unavailable ({embed_state.get('detail')}).\n"
            f"       OLLAMA_BASE_URL={settings.ollama_base_url}\n"
            f"       Start Ollama (`ollama serve`) and run "
            f"`ollama pull {settings.ollama_embedding_model}`.",
            file=sys.stderr,
        )
        return 3

    root = Path(args.path).expanduser()
    print(f"Ingesting from {root} (embedding model: {embedder.model_name}, reindex={args.reindex})")

    try:
        with SessionLocal() as db:
            summary = ingest_path(
                db,
                root,
                embedder=embedder,
                settings=settings,
                reindex=args.reindex,
                on_progress=None if args.quiet else _print_progress,
            )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4
    except (AppError, SQLAlchemyError) as exc:
        print(f"ERROR: ingestion aborted: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    if summary.files_discovered == 0:
        print(
            f"No supported transcript files found under {root}.\n"
            "Supported extensions: .txt, .md, .markdown, .json, .vtt, .srt",
            file=sys.stderr,
        )
        return 4

    print(
        "\nSummary: "
        f"{summary.files_discovered} file(s) discovered, {summary.ingested} ingested, "
        f"{summary.reindexed} reindexed, {summary.skipped} skipped, {summary.failed} failed, "
        f"{summary.chunks_written} chunks written in {summary.duration_ms / 1000:.1f}s"
    )
    if summary.failed:
        for outcome in summary.outcomes:
            if outcome.status == "failed":
                print(f"  FAILED {outcome.path}: {outcome.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
