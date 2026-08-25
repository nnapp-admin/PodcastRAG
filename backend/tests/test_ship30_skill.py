"""Ship 30 for 30 skill: prompt construction, grounding requirement, output shape."""

from __future__ import annotations

import pytest

from app.agent.contracts import AgentRequest
from app.agent.local_runtime import LocalAgentRuntime
from app.errors import AppError
from app.skills.ship30 import MIN_WORDS, TARGET_WORDS, build_prompt, word_count, write_essay

from .conftest import DEFAULT_CHUNKS, FakeProvider, FakeRetriever

ESSAY = "# Retention Is the Only PMF Signal That Matters\n\n" + ("word " * 1300)


def test_prompt_encodes_the_ship30_constraints():
    prompt = build_prompt("retention", DEFAULT_CHUNKS)
    lowered = prompt.lower()
    assert "retention" in lowered
    assert str(TARGET_WORDS) in prompt
    assert "cite" in lowered
    # The evidence itself must be in the prompt, not a summary of it.
    assert DEFAULT_CHUNKS[0].content[:40] in prompt


def test_skill_refuses_without_evidence():
    with pytest.raises(AppError):
        build_prompt("retention", [])


def test_essay_output_shape():
    provider = FakeProvider([ESSAY])
    essay = write_essay(provider, topic="retention", chunks=DEFAULT_CHUNKS)
    assert essay.title == "Retention Is the Only PMF Signal That Matters"
    assert essay.word_count >= MIN_WORDS
    assert essay.markdown.startswith("# ")
    assert essay.latency_ms > 0


def test_missing_heading_is_repaired():
    essay = write_essay(FakeProvider(["No heading here, just prose. " * 200]), topic="retention", chunks=DEFAULT_CHUNKS)
    assert essay.markdown.startswith("# retention")


def test_fenced_output_is_unwrapped():
    essay = write_essay(
        FakeProvider([f"```markdown\n{ESSAY}\n```"]), topic="retention", chunks=DEFAULT_CHUNKS
    )
    assert not essay.markdown.startswith("```")


def test_empty_model_output_is_an_error():
    with pytest.raises(AppError):
        write_essay(FakeProvider(["   "]), topic="retention", chunks=DEFAULT_CHUNKS)


def test_word_count_ignores_markdown_syntax():
    assert word_count("# Title\n\none two three") == pytest.approx(word_count("Title one two three"), abs=1)


def test_essay_capability_runs_the_skill_end_to_end():
    runtime = LocalAgentRuntime(retriever=FakeRetriever(), provider=FakeProvider(["", ESSAY]))
    result = runtime.run(AgentRequest(question="Write a Ship 30 essay about retention", requested_capability="essay"))
    assert result.capability == "essay"
    assert result.grounded is True
    assert result.word_count and result.word_count >= MIN_WORDS
    assert result.notes["essay_title"]
    assert "write_ship30_essay" in {call.name for call in result.tool_invocations}


def test_essay_is_persisted_as_a_markdown_artifact(client, session_id):
    client.provider.responses = ["", ESSAY]
    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"message": "Write a Ship 30 essay about retention", "capability": "essay"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact"]["kind"] == "markdown"
    assert body["artifact"]["content"].startswith("# ")
    assert body["assistant_message"]["artifact_id"] == body["artifact"]["id"]

    listed = client.get(f"/sessions/{session_id}/artifacts").json()["artifacts"]
    assert len(listed) == 1


def test_ship30_expansion_pass_when_draft_too_short():
    short_draft = "# Brief Retention Draft\n\nShort initial content about product retention. " * 20  # ~100 words (< MIN_WORDS)
    sec1 = "## The Tension / Status Quo\n\nMost teams obsess over top-of-funnel acquisition while retention decays. " * 25  # ~250 words
    sec2 = "## The Core Framework & Mental Model\n\nThe fundamental metric is cohort flattening over 30 and 90 days. " * 25  # ~250 words
    sec3 = "## Tactical Playbook & Step-by-Step Execution\n\nFirst, instrument day-1 activation telemetry with precise event tracking. " * 25  # ~250 words
    sec4 = "## Counterintuitive Nuances & Common Pitfalls\n\nDo not confuse superficial vanity signups with genuine core value loop habituation. " * 20  # ~200 words
    sec5 = "## Practical Weekly Takeaway & Action Plan\n\nAudit your primary onboarding drop-off step before allocating new paid ad spend. " * 20  # ~200 words

    provider = FakeProvider([short_draft, sec1, sec2, sec3, sec4, sec5])

    essay = write_essay(provider, topic="retention", chunks=DEFAULT_CHUNKS)
    assert essay.word_count >= MIN_WORDS
    assert len(provider.calls) == 6  # 1 initial draft + 5 progressive section expansion calls
    assert "## The Tension / Status Quo" in essay.markdown
    assert "## The Core Framework & Mental Model" in essay.markdown
    assert "## Tactical Playbook" in essay.markdown
    assert "## Sources" in essay.markdown


def test_ship30_sufficient_draft_not_unnecessarily_expanded():
    long_draft = ESSAY  # 1,300 words (>= MIN_WORDS)
    provider = FakeProvider([long_draft])

    essay = write_essay(provider, topic="retention", chunks=DEFAULT_CHUNKS)
    assert essay.word_count >= MIN_WORDS
    assert len(provider.calls) == 1  # Only 1 initial call needed


def test_ship30_structure_headings_and_takeaway():
    structured_essay = (
        "# Why Retention Is the Single True North of Product Growth\n\n"
        "Most product teams obsess over acquisition. They pour money into top-of-funnel ads, "
        "celebrate signups, and watch their user base quietly evaporate.\n\n"
        "## The Silent Killer: Cohort Decay\n\n"
        "If your retention curve does not flatten [1], every dollar spent on growth is wasted.\n\n"
        "## Three Rules for Durable Retention\n\n"
        "- **Measure Day-1 Activation**: The first 5 minutes decide retention.\n"
        "- **Track Cohort Flattening**: Healthy cohorts curve into horizontal asymptotes.\n"
        "- **Build Core Value Loops**: Users must return without artificial nudges.\n\n"
        "## Practical Takeaway\n\n"
        "This week, audit your 30-day cohort retention curve before touching acquisition.\n\n"
        "## Sources\n\n"
        "[1] Lenny Podcast: Finding Product-Market Fit\n"
    ) + ("word " * 950)

    provider = FakeProvider([structured_essay])
    essay = write_essay(provider, topic="retention", chunks=DEFAULT_CHUNKS)
    assert "## The Silent Killer" in essay.markdown
    assert "## Practical Takeaway" in essay.markdown
    assert "## Sources" in essay.markdown
    assert "**Measure Day-1 Activation**" in essay.markdown


def test_unsupported_topic_essay_request_refuses_without_hallucination():
    runtime = LocalAgentRuntime(retriever=FakeRetriever(empty=True), provider=FakeProvider(["Fabricated essay"]))
    result = runtime.run(
        AgentRequest(
            question="Write a Ship 30 essay about the quantum mechanics of black hole information paradox",
            requested_capability="essay",
        )
    )
    assert result.grounded is False
    assert "write_ship30_essay" not in {call.name for call in result.tool_invocations if call.ok}
    assert len(result.citations) == 0
    assert result.notes.get("reason") == "no_relevant_evidence"
