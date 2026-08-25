# Manual UI Evaluation & Test Plan

This document provides a step-by-step evaluation procedure to manually verify the complete functionality, grounding, safety, and persistence of the Lenny Growth Assistant.

---

## Prerequisites

1. Ensure the PostgreSQL + pgvector container is running:
   ```bash
   docker ps --filter "name=lenny-growth-assistant-db"
   ```
2. Ensure Ollama is running with models loaded:
   ```bash
   ollama list
   # Should list: llama3.2:1b (or llama3.1:8b) and nomic-embed-text
   ```
3. Start the backend and frontend (or `docker compose up --build`):
   - Frontend: `http://localhost:8080`
   - Backend: `http://localhost:8000`

---

## 12-Step Evaluator Test Script

### Step 1: Start & Health Check
- Open `http://localhost:8000/health` in your browser.
- **Expected Result**: HTTP 200 with status `"ok"` across `database`, `provider`, `retrieval`, and `agent`.

### Step 2: Open Frontend & Create Session
- Open `http://localhost:8080`.
- Click **"New Conversation"** (or observe the initial chat view).
- **Expected Result**: Empty chat interface with suggested prompts and active session indicator.

### Step 3: Ask Supported Lenny Question
- Enter query:
  ```text
  What does Stewart Butterfield say about why communication is just as important as building a great product?
  ```
- **Expected Result**:
  - Assistant responds with a synthesized, grounded explanation of Butterfield's product communication philosophy.
  - Claims are accompanied by numbered citation markers (e.g. `[1]`).

### Step 4: Verify Answer + Citations
- Inspect the **Sources** drawer / citation cards below the message.
- **Expected Result**:
  - Citation `[1]` points directly to the Stewart Butterfield episode (*Slack founder: Mental models for building products people love*).
  - Contains exact guest name, timestamp/episode metadata, and URL.
  - Irrelevant retrieved episodes are excluded from the citation list.

### Step 5: Ask Unsupported Question (Refusal Gate)
- Enter an off-corpus query:
  ```text
  What is the precise stoichiometric ratio of liquid oxygen to RP-1 kerosene in the Saturn V F-1 rocket engine?
  ```
- **Expected Result**:
  - Assistant refuses immediately (<100ms) with:
    *"I don't have enough information in the available transcripts to answer that..."*
  - Zero citations are returned (`citations: []`).
  - No model hallucination or generic speculative answers.

### Step 6: Ask Follow-up in Context
- In the same conversation, enter:
  ```text
  How did this approach specifically influence how Slack was launched?
  ```
- **Expected Result**:
  - Assistant maintains multi-turn conversation memory, connecting the Butterfield mental model to Slack's early preview and feedback strategy with grounded citations.

### Step 7: Generate Markdown Artifact
- Enter command/request:
  ```text
  Build me a Markdown one-pager on Stewart Butterfield's product communication mental models
  ```
- **Expected Result**:
  - Assistant generates a structured Markdown document with `#` title, `##` sections, bulleted takeaways, and `## Sources`.
  - Artifact button appears in the message or automatically opens the **Artifact Viewer** pane.

### Step 8: Inspect Markdown Artifact in Viewer
- Open the Artifact Viewer.
- **Expected Result**:
  - Rendered preview shows formatted typography, bold text, code/quote blocks, and headings.
  - "Code" tab shows clean raw Markdown without wrapping code fences.
  - "Download" button exports `.md` file.

### Step 9: Generate HTML/CSS Artifact
- Enter request:
  ```text
  Build an HTML conversion dashboard card based on podcast metrics
  ```
- **Expected Result**:
  - Assistant generates standalone HTML with semantic tags (`<div class="card">`) and CSS styling in `<style>` block.
  - Artifact Viewer displays the visual card inside an isolated frame.

### Step 10: Verify Security & Sandbox Boundary
- Inspect the HTML preview iframe in browser DevTools.
- **Expected Result**:
  - `iframe` has `sandbox=""` attribute (no `allow-scripts`, no `allow-same-origin`).
  - Injected CSP meta-tag is active: `default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none';`.
  - Injected scripts, event handlers (`onerror=`, `onclick=`), and `@import` rules are stripped by server sanitization before reaching the client.

### Step 11: Generate Ship 30 for 30 Essay
- Enter prompt:
  ```text
  Write a Ship 30 for 30 essay about mental models for building products people love, using Stewart Butterfield insights.
  ```
- **Expected Result**:
  - Generates an atomic essay adhering to Ship 30 principles:
    - Clear H1 title
    - Compelling 2-line hook
    - 3–4 subheadings (`##`)
    - Skimmable paragraphs (1–3 lines)
    - Actionable practical takeaway
    - Target length in the **1,050–1,450 word band** (~1,250 words)
    - `## Sources` citation section at bottom.

### Step 12: Verify Session Persistence & Isolation
- Refresh the browser page (`F5`).
- Re-open the previous conversation from the sidebar.
- **Expected Result**:
  - All messages, citation metadata, and generated artifacts are fully restored from PostgreSQL.
- Create a brand new conversation:
  - **Expected Result**: The new conversation has an empty artifact list and does not leak artifacts or messages from the previous conversation.
