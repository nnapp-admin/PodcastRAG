# PRD — The Lenny Growth Assistant

## 1. Problem

Lenny's Podcast holds thousands of hours of specific, hard-won product and growth advice from
operators. That knowledge is effectively unsearchable: you cannot ask "what do founders
actually use as a product-market-fit signal?" and get an answer attributable to the people who
said it. General-purpose chatbots answer such questions fluently and unverifiably — which is
worse than not answering, because the user cannot tell the difference.

## 2. Goal

A growth assistant that answers from the transcript corpus **only**, always shows its
sources, and turns that grounded knowledge into publishable writing.

## 3. Users

- **Founders / PMs / growth leads** who want a specific answer with a source they can go
  listen to.
- **Operators building an audience** who want to turn a podcast insight into a Ship 30 for 30
  atomic essay.

## 4. Core requirements

### 4.1 Grounded Q&A (must)

- The assistant retrieves before it reasons, on every turn.
- Answers cite the transcript chunks they used: episode, guest, timestamp, speaker.
- When retrieval returns nothing above the relevance threshold, the assistant says the corpus
  does not cover the question. It never fills the gap from model priors.
- If the knowledge base is empty, the API returns a distinct, actionable error rather than an
  empty-sounding answer.

### 4.2 Ship 30 for 30 essay skill (must)

Given a topic, the assistant produces an atomic essay grounded in transcript evidence and
conforming to Ship 30 constraints:

- one single idea, stated in the first line
- a hook that earns the second sentence
- short paragraphs, plain language, no filler transitions
- approximately 1,250 words (1,050–1,450 word target band), validated after generation
- a concrete takeaway the reader can act on

The essay is grounded like any other answer: its claims come from retrieved chunks, and the
citations are attached to the output.

### 4.3 Artifacts (must)

Substantive deliverables (essays, briefs, summaries) are persisted as artifacts with a title,
kind, format (`markdown` or `html`), and body, linked to the message that produced them. The
UI renders them in a dedicated viewer with copy and download. HTML artifacts are sanitised
server-side and rendered sandboxed.

### 4.4 Conversations (must)

- Multiple named conversations, listed most-recent-first.
- Full history survives a reload; history is sent as context on later turns.
- Sessions are strictly isolated — one conversation never reads another's messages or
  artifacts.
- A conversation is titled from its first message.

### 4.5 Model flexibility (must)

The user can run the whole product locally and free with Ollama, or switch to Anthropic or
OpenAI with one config change and no code change. Embeddings stay on one provider so the
vector space stays consistent.

### 4.6 Transparency (must)

The UI always shows: which provider and model answered, which agent runtime ran, how many
chunks were retrieved, and latency. Backend health is visible, and an unreachable backend is
stated plainly rather than hidden.

## 5. Non-goals

- No audio ingestion or transcription — transcripts are the input.
- No multi-tenant accounts or auth; this is a single-operator local tool.
- No fine-tuning; grounding is retrieval, not training.
- No web search fallback. Out-of-corpus questions get an honest refusal, by design.

## 6. Success criteria

1. A question covered by the corpus returns an answer whose citations point at real
   transcript text that actually supports it.
2. A question outside the corpus returns a refusal, not an invention.
3. "Write me a Ship 30 essay about onboarding" returns an approximately 1,250-word atomic essay, saved as
   an artifact, with citations.
4. Reloading the browser restores every conversation and artifact.
5. `docker compose up` plus one ingest command is the entire setup for a new machine.
6. Switching `LLM_PROVIDER` changes the answering model with no code edits.
7. The test suite passes with no cloud credentials and no running Ollama.
