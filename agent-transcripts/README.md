# agent-transcripts/

This directory is reserved for actual, captured agent interaction logs — full traces of the
Lenny Growth Assistant answering real questions, including retrieval calls, tool invocations,
and the final grounded answer.

## Why this directory is currently empty

No agent transcripts are fabricated. The assistant refuses to answer without retrieved
transcript evidence, so a meaningful trace requires:

1. A running PostgreSQL + pgvector instance.
2. At least one real Lenny's Podcast transcript ingested into the vector index.
3. Either Ollama running locally **or** an `ANTHROPIC_API_KEY` set.

If those prerequisites are not yet met on this machine, see the main `README.md` for setup
instructions.

## How to capture a real agent trace

Once the stack is running:

```bash
# Create a session and ask a grounded question:
curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "PMF interview"}' | python -m json.tool

SESSION_ID="<paste id from above>"

curl -s -X POST "http://localhost:8000/sessions/$SESSION_ID/messages" \
  -H "Content-Type: application/json" \
  -d '{"message": "What signals product-market fit, according to the transcripts?"}' \
  | python -m json.tool
```

The response JSON includes:

- `assistant_message.content` — grounded answer with inline citations like `[1]`
- `assistant_message.citations` — episode title, guest, timestamp, URL for each citation
- `assistant_message.metadata_json.tool_calls` — every `search_transcripts` call made
- `assistant_message.metadata_json.runtime` — `local` or `claude_sdk`
- `assistant_message.metadata_json.latency_ms` — end-to-end latency

Save the response JSON here as e.g. `2024-12-01-pmf-signals-ollama-llama3.json`.

## What a valid grounded trace looks like

1. A `search_transcripts` tool call *before* any model answer.
2. A non-empty `citations` array pointing at real chunk IDs, episode titles, and timestamps.
3. The answer text referencing citations as `[1]`, `[2]`, etc.
4. `grounded: true` in the assistant message metadata.

A trace with `grounded: false` and `reason: no_relevant_evidence` is also valid — it proves
the refusal path works when the corpus does not cover the question.

## Formats accepted here

- `.json` — raw API response JSON
- `.md` — prose description of the session + key excerpts
- `.txt` — plain curl/httpie output
