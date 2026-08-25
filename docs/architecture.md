# Architecture — The Lenny Growth Assistant

## 1. System shape

```text
                 ┌──────────────────────────────────────────┐
   Browser  ───► │ React + TanStack Start (Vite, port 8080)  │
                 │  typed API client (Zod) + React Query     │
                 └───────────────────┬──────────────────────┘
                                     │ HTTP, VITE_API_BASE_URL
                 ┌───────────────────▼──────────────────────┐
                 │ FastAPI (port 8000)                       │
                 │  /health /sessions /retrieval /artifacts  │
                 └───────┬───────────────────────┬──────────┘
                         │                       │
             ┌───────────▼──────────┐  ┌─────────▼───────────┐
             │ Agent runtime         │  │ Retrieval engine     │
             │ claude_sdk | local    │  │ embed → search →     │
             │ bounded tool loop     │  │ rerank → threshold   │
             └───────┬───────────────┘  └─────────┬───────────┘
                     │ LLMProvider                │ SQLAlchemy
       ┌─────────────▼──────────────┐   ┌──────────▼──────────┐
       │ Ollama | Anthropic | OpenAI │   │ Postgres + pgvector │
       └────────────────────────────┘   └─────────────────────┘
                                                  ▲
                                    ┌─────────────┴───────────┐
                                    │ Ingestion CLI            │
                                    │ clean → chunk → embed    │
                                    │ data/transcripts/*       │
                                    └──────────────────────────┘
```

## 2. Backend modules

```text
backend/app/
  main.py             application factory: CORS, request IDs, logging, error envelope
  config.py           pydantic-settings; every knob is an env var
  errors.py           AppError hierarchy → one JSON error envelope
  logging_config.py   structured JSON-line logs with request/session context
  schemas.py          Pydantic request/response contracts
  db/                 models (portable across Postgres/SQLite), session, Alembic migrations
  providers/          LLMProvider ABC + ollama, anthropic, openai_provider + factory
  retrieval/          cleaning, metadata, chunking, embedder, reranker, pgvector_retriever
  agent/              contracts, tools, routing, prompts, local_runtime, claude_sdk_runtime
  skills/ship30.py    Ship 30 for 30 atomic-essay skill + validation
  artifacts/          generator + server-side sanitisation
  ingestion/          pipeline (idempotent) + CLI
  api/                health, sessions, chat, retrieval, artifacts, deps, serializers
```

## 3. Request path for one chat turn

1. `POST /sessions/{id}/messages` validates the body and loads the session with its history
   (404 if the session does not exist).
2. Dependencies resolve the configured provider, retriever, and agent runtime.
3. The runtime performs a **seeded retrieval** with the user's question — grounding is not left
   to the model's discretion.
4. Intent routing picks the capability: `qa`, `essay`, or `artifact`.
5. The model runs a **bounded** tool loop (`AGENT_MAX_TOOL_STEPS`) over
   `search_transcripts`, `write_ship30_essay`, `generate_artifact`.
6. If no chunk clears `RETRIEVAL_SCORE_THRESHOLD`, the runtime returns a grounded refusal
   without calling the model for an answer.
7. The answer, its citations, any artifact, and the run metadata (provider, model, runtime,
   chunk count, latency) are persisted and returned.

## 4. Retrieval design

- **Cleaning** normalises `.vtt`/`.srt` (timestamps, WebVTT `<v Speaker>` voice tags,
  duplicate rolling captions), JSON transcript arrays, and plain text into segments that keep
  timestamp and speaker.
- **Metadata** comes from YAML front-matter, falling back to a filename convention.
- **Chunking** is sentence-aware with overlap, bounded by `CHUNK_TARGET_CHARS`; a segment with
  no sentence boundaries (common in auto-captions) is split on word boundaries so no chunk
  ever exceeds the bound.
- **Embedding** is batched through the provider abstraction and dimension-checked against
  `EMBEDDING_DIMENSIONS` — a model/schema mismatch fails loudly.
- **Search** is pgvector cosine ANN (`ivfflat` index) over
  `top_k × RETRIEVAL_CANDIDATE_MULTIPLIER` candidates.
- **Reranking** blends vector similarity with lexical overlap, then applies the score
  threshold. Below the threshold, the corpus is treated as silent.

## 5. Model abstraction

`LLMProvider` defines `complete(system, messages, tools)` and `embed(texts)` and returns a
normalised `CompletionResult` (text, tool calls, token usage, latency). Provider-specific HTTP
shapes, tool-call formats, and error codes are mapped inside each implementation, so nothing
above the provider layer knows which vendor answered. The factory is the only switch, and it
validates cloud keys at construction time.

## 6. Two agent runtimes

Both implement the same `AgentRuntime` contract and return the same `AgentResult`:

- **`claude_sdk_runtime`** delegates the loop to the Anthropic Claude Agent SDK.
- **`local_runtime`** is a deterministic tool loop that works with any provider, including
  Ollama.

`AGENT_RUNTIME=auto` picks the SDK when an Anthropic key is configured and falls back to local
otherwise, so the app is fully functional offline and the SDK path is exercised when
credentials exist.

## 7. Data model

- `sessions` — conversation, title, timestamps
- `messages` — role, content, citations, run metadata, session FK
- `transcripts` — source path, content hash, episode metadata
- `transcript_chunks` — text, ordinal, timestamp, speaker, `vector` embedding, transcript FK
- `artifacts` — kind, format, title, sanitised body, session + message FKs

Cascades delete a session's messages and artifacts together. Models are dialect-portable so
the suite runs on SQLite while production uses pgvector.

## 8. Cross-cutting

- **Errors:** every failure is an `AppError` subclass rendered as one envelope with a code, a
  human message, details, and the request ID.
- **Logging:** JSON lines with request ID, session ID, provider, runtime, latency, and chunk
  counts.
- **Resilience:** provider timeouts and HTTP failures map to typed provider errors; the tool
  loop is step-bounded; the frontend surfaces an unreachable backend explicitly.
- **Security:** artifacts are sanitised server-side and rendered in a sandboxed iframe;
  ingestion reads only under the configured transcripts root.
