"""Engine / session factory plus a database health probe."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.errors import DatabaseUnavailableError
from app.logging_config import get_logger

logger = get_logger(__name__)

_settings = get_settings()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def build_engine(url: str) -> Engine:
    """PostgreSQL is the production database; SQLite is only used by the test
    suite, and needs different pool arguments."""
    if url.startswith("sqlite"):
        return create_engine(
            url,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)


engine = build_engine(_settings.database_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[OrmSession]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("database_error", extra={"error_type": type(exc).__name__})
        raise DatabaseUnavailableError(details={"error_type": type(exc).__name__}) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[OrmSession]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def database_health() -> dict:
    """Cheap probe used by /health. Never raises."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            if conn.dialect.name != "postgresql":
                return {"status": "ok", "pgvector": False, "detail": "non-postgresql dialect"}
            has_vector = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            ).scalar()
        return {"status": "ok", "pgvector": bool(has_vector)}
    except SQLAlchemyError as exc:
        logger.error("database_health_failed", extra={"error_type": type(exc).__name__})
        return {"status": "error", "detail": f"{type(exc).__name__}: unable to connect"}
