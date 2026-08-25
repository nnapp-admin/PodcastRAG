# The Lenny Growth Assistant

A grounded, local-first growth assistant over Lenny's Podcast transcripts. It answers
product/growth questions **only** from retrieved transcript evidence, writes Ship 30 for 30
atomic essays, and renders downloadable artifacts.

- **Backend:** FastAPI (Python 3.11+), SQLAlchemy, Alembic, PostgreSQL + pgvector
- **Frontend:** React + TanStack Start (Vite), typed API client validated with Zod
- **Models:** provider-agnostic — Ollama (default, free/offline), Anthropic, OpenAI
- **Agent:** Anthropic Claude Agent SDK runtime, with a behaviourally equivalent local
  tool-loop runtime so the whole app runs with no cloud key

See [`docs/architecture.md`](./docs/architecture.md) for the system design, [`docs/design.md`](./docs/design.md)
for the engineering decisions and trade-offs, and [`docs/PRD.md`](./docs/PRD.md) for the product spec.

---

## 1. Prerequisites

| Requirement | Why |
| --- | --- |
| Docker + Docker Compose | Postgres/pgvector, backend, frontend |
| [Ollama](https://ollama.com) running on the host | Default chat model + embeddings (no cloud key needed) |
| Lenny's Podcast transcripts | The knowledge base — nothing is fabricated, so an empty corpus means no answers |

Pull the local models once:

```bash
# If Ollama is installed on your host:
ollama pull llama3.2:1b          # CPU/lightweight (or llama3.1:8b for GPU)
ollama pull nomic-embed-text     # Embedding model (768 dimensions)

# Or if running Ollama in a Docker container:
docker exec ollama ollama pull llama3.2:1b
docker exec ollama ollama pull nomic-embed-text
```

## 2. Configure

```bash
cp .env.example .env
```

Defaults run fully local against Ollama (`llama3.2:1b` or `llama3.1:8b`). To use a cloud model instead, set
`LLM_PROVIDER=anthropic` (or `openai`) and the matching API key (`ANTHROPIC_API_KEY`). Embeddings stay on Ollama
(`EMBEDDING_PROVIDER=ollama`) so vectors remain comparable when you switch chat providers.
If a cloud provider is selected without its key, the app fails fast at startup with an
actionable error rather than mid-conversation.

## 3. Add transcripts

The official public transcript dataset is available from Lenny's public starter repository:
[LennysNewsletter/lennys-newsletterpodcastdata](https://github.com/LennysNewsletter/lennys-newsletterpodcastdata).

Copy the official podcast `.md` files into:
`data/transcripts/`

Supported: `.vtt`, `.srt`, `.txt`, `.md`, `.json`. Metadata (title, guest, date, description, `source_url`/`post_url`) comes from YAML front-matter when present, otherwise from the filename (`YYYY-MM-DD - Guest - Episode title.vtt`). See `data/transcripts/README.md`.

## 4. Run

```bash
docker compose up --build
```

- Frontend: http://localhost:8080
- API: http://localhost:8000 (docs at http://localhost:8000/docs)
- Health: http://localhost:8000/health

Migrations run automatically on backend start.

## 5. Ingest the knowledge base

```bash
docker compose exec backend python -m app.ingestion.cli
docker compose exec backend python -m app.ingestion.cli --stats
```

Ingestion is idempotent: unchanged files are skipped by content hash, changed files are
re-chunked and re-embedded with their old chunks removed (no duplicates).

Useful flags:

```bash
python -m app.ingestion.cli --path data/transcripts/one-episode.md
python -m app.ingestion.cli --reindex     # re-chunk and re-embed even if unchanged
python -m app.ingestion.cli --stats       # print index statistics
python -m app.ingestion.cli --quiet       # only print final summary
```

## 6. Running without Docker

```bash
# 1. Postgres with pgvector must be reachable at DATABASE_URL
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.ingestion.cli
uvicorn app.main:app --reload --port 8000
```

```bash
# 2. Frontend
npm install
npm run dev
```

The frontend reads `VITE_API_BASE_URL`. When the backend is unreachable, the UI shows an explicit "backend unavailable" state instead of pretending to work.

## 7. Tests

```bash
cd backend
# If using a venv:
pytest tests/
# If using uv:
uv run --with-requirements requirements.txt pytest tests/
```

114 tests cover grounding behaviour, citation resolution, session persistence and isolation, Claude Agent SDK MCP runtime, the Ship 30 skill,
artifact sanitisation, ingestion/cleaning/chunking, retrieval reranking, provider selection,
and the API contract + error envelope. They run against in-memory SQLite with fake provider
and retriever implementations, so **no Ollama, Postgres, or API key is required**. Tests
marked `postgres` or `ollama` are opt-in:

```bash
pytest tests/ -m postgres
```


## 8. What the assistant will and will not do

- It answers only from retrieved chunks and cites them; with no relevant evidence above the
  score threshold it says so instead of guessing.
- Every answer carries citations resolvable to a real transcript, timestamp, and speaker.
- Artifacts are sanitised server-side (no scripts, iframes, or event handlers) and rendered
  in a sandboxed frame.

## 9. API surface

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Per-component health: database, provider, retrieval, agent |
| `POST` | `/sessions` | Create a conversation |
| `GET` | `/sessions` | List conversations |
| `GET` | `/sessions/{id}` | Conversation with full message history |
| `DELETE` | `/sessions/{id}` | Delete a conversation and its artifacts |
| `POST` | `/sessions/{id}/messages` | Send a message, get a grounded answer + citations |
| `GET` | `/sessions/{id}/artifacts` | Artifacts produced in a conversation |
| `GET` | `/artifacts/{id}` | Single artifact, sanitised |
| `POST` | `/retrieval/search` | Raw retrieval inspection (debugging/evaluation) |

All failures return one structured envelope:

```json
{ "error": { "code": "knowledge_base_empty", "message": "...", "details": {}, "request_id": "..." } }
```

