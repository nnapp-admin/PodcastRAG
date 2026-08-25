#!/usr/bin/env bash
# Wait for PostgreSQL, apply Alembic migrations from a clean database, then run
# the given command. Migrations are idempotent, so restarts are safe.
set -euo pipefail

echo "[entrypoint] waiting for database..."
for attempt in $(seq 1 60); do
  if python - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL", "postgresql+psycopg://lenny:lenny@db:5432/lenny")
try:
    with create_engine(url, pool_pre_ping=True).connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception as exc:
    print(f"  not ready: {type(exc).__name__}", file=sys.stderr)
    sys.exit(1)
PY
  then
    echo "[entrypoint] database is up (attempt ${attempt})"
    break
  fi
  if [ "${attempt}" -eq 60 ]; then
    echo "[entrypoint] ERROR: database never became reachable at DATABASE_URL" >&2
    exit 1
  fi
  sleep 2
done

echo "[entrypoint] applying migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
