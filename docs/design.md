# Design decisions and trade-offs

## 1. Grounding is enforced by the system, not requested from the model

A prompt asking a model to "only use the provided context" is a suggestion. Instead:

- retrieval is **seeded** — the runtime searches with the user's question before the model gets
  a turn, so no answer exists without evidence having been fetched;
- a **score threshold** decides whether the corpus is relevant, in code;
- below the threshold the runtime returns a refusal **without asking the model for prose**,
  which removes the opportunity to hallucinate;
- citations are built from the retrieved rows, not parsed out of model output, so they cannot
  point at an episode that was never retrieved.

Trade-off: the assistant refuses more often than a general chatbot, including on questions it
could plausibly bluff. That is the intended product behaviour for an attributable assistant.

## 2. Ollama as the default, cloud as an option

The default path costs nothing and runs offline, so the reviewer needs no credentials to see
the product work. Cloud providers exist behind the same interface for quality. Embeddings are
pinned to one provider (`EMBEDDING_PROVIDER`) because mixing embedding models silently
corrupts a vector index — vectors from different models are not comparable, and the failure
looks like bad retrieval rather than a config error. Dimension checks on write make the
mismatch loud.

Trade-off: a local 8B model writes less polished essays than Claude. Switching is one env var.

## 3. Two agent runtimes instead of one

The assignment asks for the Claude Agent SDK; a demo that only works with an Anthropic key is
a demo that mostly does not work. Both runtimes implement one contract and return one result
shape, and `AGENT_RUNTIME=auto` selects by available credentials.

Trade-off: two loops to keep behaviourally aligned. Mitigated by testing against the contract
(grounding, refusal, citations, bounded steps) rather than against either implementation.

## 4. pgvector rather than a dedicated vector database

The corpus is one podcast's transcripts, and chunks need relational neighbours (transcripts,
sessions, messages, artifacts) with cascading deletes. One Postgres gives transactional
ingestion, joins, and vector search with no second system to run or sync. `ivfflat` ANN is
ample at this scale.

Trade-off: less specialised than a purpose-built vector store at very large scale; not a
constraint here.

## 5. Hybrid lexical + vector reranking

Pure vector search on conversational transcripts retrieves topically adjacent but unhelpful
chunks, especially for questions containing proper nouns and jargon ("PLG", "Superhuman",
"NPS"). Over-fetching candidates and reranking with lexical overlap folded into the score
puts exact-term matches back on top cheaply, with no cross-encoder to serve.

Trade-off: weaker than a learned reranker; a fraction of the cost and latency, and swappable
via `RETRIEVAL_RERANKER`.

## 6. Sentence-aware chunking with overlap

Fixed-width chunks cut mid-thought, and podcast answers are multi-sentence arguments. Chunks
are assembled from sentence-bounded segments up to a target size with overlap so context
spanning a boundary survives. Auto-caption text without punctuation is split on word
boundaries so the size bound always holds — the alternative was oversized chunks silently
blowing the embedding request.

## 7. Artifacts are sanitised on the server and sandboxed in the client

Model output rendered as HTML is untrusted input. Scripts, iframes, and event handlers are
stripped before persistence, so a stored artifact cannot execute even if a later client
renders it carelessly; the viewer additionally uses a sandboxed frame. Defence at both layers,
because either alone is one refactor away from a hole.

## 8. Idempotent ingestion keyed on content hash

Re-running ingest is the normal case while iterating on chunking. Unchanged files are skipped
by hash; changed files have their old chunks deleted and replaced in one transaction. Without
this, repeated runs quietly duplicate chunks and skew retrieval toward whatever was ingested
most often.

## 9. Split frontend/backend rather than one framework

The API is a normal FastAPI service, so the agent, retrieval, and ingestion code is testable
and runnable without a browser, and the ingestion CLI shares exactly the code the API uses.
The frontend talks to it over `VITE_API_BASE_URL` and validates every response with Zod
mirroring the Pydantic contracts, so a contract drift surfaces as a clear parse error instead
of a rendering bug.

Trade-off: two processes and CORS to configure — handled by `docker compose up`.

## 10. Tests run with no external dependencies

The suite uses in-memory SQLite plus fake provider and retriever implementations that satisfy
the real interfaces, so the full agent loop, API contract, and error envelope are exercised
with no Ollama, Postgres, or key. Tests requiring real infrastructure are marked `postgres` /
`ollama` and opt-in. This keeps the behaviour that matters — grounding, refusal, citation
integrity, session isolation, sanitisation, idempotency — verified on any machine in seconds.

Trade-off: fakes can drift from real providers. Bounded by keeping the provider layer thin and
covering its HTTP mapping with transport-level tests.

## 11. Known limitations

- Answer quality is bounded by transcript coverage; an empty `data/transcripts/` means the API
  correctly reports an empty knowledge base rather than answering.
- No streaming responses yet; a turn returns once complete.
- Single-user by design — no auth, no tenancy.
- The lexical reranker is language-agnostic but tuned for English transcripts.
