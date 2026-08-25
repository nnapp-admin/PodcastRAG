"""Grounding behaviour of the agent runtime.

These are the assignment's hardest requirements: the assistant must always
retrieve first, must refuse rather than fall back on general model knowledge,
and must attribute its answer to real transcript chunks.
"""

from __future__ import annotations

from app.agent.contracts import AgentRequest
from app.agent.local_runtime import LocalAgentRuntime
from app.agent.prompts import INSUFFICIENT_EVIDENCE_RESPONSE
from app.agent.routing import preferred_artifact_kind, route_capability
from app.providers.base import ToolCall

from .conftest import DEFAULT_CHUNKS, FakeProvider, FakeRetriever, make_chunk


def build_runtime(retriever, provider) -> LocalAgentRuntime:
    return LocalAgentRuntime(retriever=retriever, provider=provider)


def test_retrieval_always_runs_before_generation():
    retriever, provider = FakeRetriever(), FakeProvider(["Answer grounded in [1]."])
    result = build_runtime(retriever, provider).run(AgentRequest(question="What signals PMF?"))
    assert retriever.calls, "the agent must search transcripts before answering"
    assert result.tool_invocations[0].name == "search_transcripts"
    assert result.grounded is True
    assert result.citations


def test_no_evidence_produces_a_refusal_not_a_guess():
    retriever = FakeRetriever(empty=True)
    provider = FakeProvider(["The three pillars of growth are acquisition, retention and monetisation."])
    result = build_runtime(retriever, provider).run(AgentRequest(question="Who won the 1998 World Cup?"))
    assert result.grounded is False
    assert result.text == INSUFFICIENT_EVIDENCE_RESPONSE
    assert result.citations == []
    assert result.notes["reason"] == "no_relevant_evidence"


def test_low_scoring_evidence_is_treated_as_no_evidence():
    weak = [make_chunk("Unrelated chatter about the weather.", score=0.05)]
    result = build_runtime(FakeRetriever(weak), FakeProvider(["Confident nonsense."])).run(
        AgentRequest(question="What is the best pricing model?")
    )
    assert result.grounded is False
    assert result.text == INSUFFICIENT_EVIDENCE_RESPONSE


def test_citations_point_at_the_retrieved_chunks():
    retriever = FakeRetriever()
    result = build_runtime(retriever, FakeProvider(["Retention is the signal [1]."])).run(
        AgentRequest(question="What signals PMF?")
    )
    retrieved_ids = {chunk.chunk_id for chunk in DEFAULT_CHUNKS}
    assert {citation.chunk_id for citation in result.citations} <= retrieved_ids
    assert all(citation.episode_title for citation in result.citations)
    assert all(citation.content for citation in result.citations)


def test_evidence_is_injected_into_the_prompt():
    provider = FakeProvider(["Answer [1]."])
    build_runtime(FakeRetriever(), provider).run(AgentRequest(question="What signals PMF?"))
    prompt_text = "\n".join(
        message.get("content", "") for call in provider.calls for message in call["messages"]
    )
    assert "retention" in prompt_text.lower()


def test_model_requested_extra_search_is_executed():
    retriever = FakeRetriever()
    provider = FakeProvider(
        [
            [ToolCall(id="1", name="search_transcripts", arguments={"query": "activation metrics"})],
            "Final grounded answer [1].",
        ]
    )
    result = build_runtime(retriever, provider).run(AgentRequest(question="What signals PMF?"))
    assert [call["query"] for call in retriever.calls] == ["What signals PMF?", "activation metrics"]
    assert result.text == "Final grounded answer [1]."


def test_a_failing_tool_call_degrades_instead_of_crashing():
    retriever = FakeRetriever()
    provider = FakeProvider(
        [
            [ToolCall(id="1", name="does_not_exist", arguments={})],
            "Recovered grounded answer [1].",
        ]
    )
    result = build_runtime(retriever, provider).run(AgentRequest(question="What signals PMF?"))
    failed = [call for call in result.tool_invocations if not call.ok]
    assert failed and "Unknown tool" in failed[0].summary
    assert result.grounded is True
    assert result.text == "Recovered grounded answer [1]."


def test_tool_loop_is_bounded():
    provider = FakeProvider(
        [[ToolCall(id=str(i), name="search_transcripts", arguments={"query": "loop"})] for i in range(3)]
        + ["Answer after the loop was cut short [1]."]
    )
    result = build_runtime(FakeRetriever(), provider).run(AgentRequest(question="What signals PMF?"))
    # The loop stops at AGENT_MAX_TOOL_STEPS (3) instead of following the model forever.
    assert len(provider.calls) <= 4  # 3 tool steps + the final grounded completion
    assert result.grounded is True


def test_observability_metrics_are_recorded():
    result = build_runtime(FakeRetriever(), FakeProvider(["Answer [1]."])).run(
        AgentRequest(question="What signals PMF?")
    )
    assert result.latency_ms > 0
    assert result.retrieval_latency_ms >= 0
    assert result.generation_latency_ms > 0
    assert result.provider == "fake"
    assert result.runtime == "local"


# --- routing --------------------------------------------------------------


def test_routing_picks_capabilities_from_intent():
    assert route_capability("What signals product-market fit?") == "qa"
    assert route_capability("Write a Ship 30 essay about retention") == "essay"
    assert route_capability("Build me a one-pager on growth loops") == "artifact"


def test_explicit_capability_request_wins():
    assert route_capability("What signals PMF?", "essay") == "essay"
    assert route_capability("Write me an essay", "qa") == "qa"


def test_artifact_kind_preference():
    assert preferred_artifact_kind("Make an HTML landing page") == "html"
    assert preferred_artifact_kind("Make a checklist document") == "markdown"


# --- Citation hardening & Grounding verification -------------------------


def test_irrelevant_retrieved_candidates_are_excluded_from_citations():
    chunk1 = make_chunk("Stewart Butterfield on communication and products.", score=0.85, episode_title="Stewart Butterfield", guest="Stewart Butterfield")
    chunk2 = make_chunk("Tony Fadell on hardware and iPod design.", score=0.60, episode_title="Tony Fadell", guest="Tony Fadell")
    chunk3 = make_chunk("Tomer Cohen on LinkedIn AI features.", score=0.55, episode_title="Tomer Cohen", guest="Tomer Cohen")

    retriever = FakeRetriever([chunk1, chunk2, chunk3])
    provider = FakeProvider(["Stewart Butterfield explains that communicating what a product does is essential [1]."])

    result = build_runtime(retriever, provider).run(AgentRequest(question="What did Stewart Butterfield say?"))

    assert result.grounded is True
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == chunk1.chunk_id
    assert result.citations[0].guest == "Stewart Butterfield"
    # Ensure un-cited chunks 2 & 3 are excluded from citations
    cited_ids = {c.chunk_id for c in result.citations}
    assert chunk2.chunk_id not in cited_ids
    assert chunk3.chunk_id not in cited_ids


def test_multiple_relevant_citations_are_preserved():
    chunk1 = make_chunk("First insight on user retention.", score=0.88, episode_title="Ep 1", guest="Guest A")
    chunk2 = make_chunk("Second insight on onboarding loops.", score=0.75, episode_title="Ep 2", guest="Guest B")
    chunk3 = make_chunk("Third insight on unrelated topic.", score=0.60, episode_title="Ep 3", guest="Guest C")

    retriever = FakeRetriever([chunk1, chunk2, chunk3])
    provider = FakeProvider(["Insights from both Guest A [1] and Guest B [2] demonstrate growth."])

    result = build_runtime(retriever, provider).run(AgentRequest(question="How does retention work?"))

    assert result.grounded is True
    assert len(result.citations) == 2
    cited_ids = [c.chunk_id for c in result.citations]
    assert cited_ids == [chunk1.chunk_id, chunk2.chunk_id]
    assert chunk3.chunk_id not in cited_ids


def test_citation_metadata_maps_to_actual_transcript_source():
    chunk = make_chunk(
        "Communication solves customer problems.",
        score=0.92,
        episode_title="Stewart Butterfield Episode",
        guest="Stewart Butterfield",
        source_url="https://www.youtube.com/watch?v=kLe-zy5r0Mk",
        index=4,
    )
    retriever = FakeRetriever([chunk])
    provider = FakeProvider(["According to Stewart Butterfield [1], communication solves customer problems."])

    result = build_runtime(retriever, provider).run(AgentRequest(question="What solves problems?"))

    assert result.grounded is True
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.episode_title == "Stewart Butterfield Episode"
    assert citation.guest == "Stewart Butterfield"
    assert citation.source_url == "https://www.youtube.com/watch?v=kLe-zy5r0Mk"
    assert citation.chunk_index == 4
    assert citation.score == 0.92
    assert "Communication solves customer problems." in citation.content


def test_follow_up_question_preserves_conversation_history():
    retriever = FakeRetriever([make_chunk("Follow-up answer content.", score=0.80)])
    provider = FakeProvider(["Follow-up grounded answer [1]."])

    history = [
        {"role": "user", "content": "Initial question about PMF"},
        {"role": "assistant", "content": "Initial answer about retention [1]"},
    ]
    request = AgentRequest(question="Can you elaborate on that?", history=history)
    result = build_runtime(retriever, provider).run(request)

    assert result.grounded is True
    # Verify history was passed to provider messages
    all_messages = [msg for call in provider.calls for msg in call.get("messages", [])]
    user_contents = [msg["content"] for msg in all_messages if msg.get("role") == "user"]
    assert any("Initial question about PMF" in c for c in user_contents)


def test_unsupported_question_refusal_returns_zero_citations():
    retriever = FakeRetriever(empty=True)
    provider = FakeProvider(["Should never be called."])

    result = build_runtime(retriever, provider).run(
        AgentRequest(question="What is the stoichiometric ratio of liquid oxygen to RP-1 kerosene?")
    )

    assert result.grounded is False
    assert result.text == INSUFFICIENT_EVIDENCE_RESPONSE
    assert len(result.citations) == 0
    assert result.notes.get("reason") == "no_relevant_evidence"


def test_normal_qa_never_leaks_tool_json():
    from app.agent.routing import route_capability
    q = "What does Stewart Butterfield say about why communication is just as important as building a great product?"
    assert route_capability(q) == "qa"

    chunk = make_chunk("Communication is essential for product-market fit.", score=0.85, episode_title="Butterfield", guest="Stewart Butterfield")
    retriever = FakeRetriever([chunk])
    # Simulate a model returning raw tool-call JSON text in the first step
    raw_json = '{"type":"function","function":{"name":"write_ship30_essay","parameters":{"topic":"communication"}}}'
    provider = FakeProvider([raw_json, "Stewart Butterfield emphasizes that communication is critical [1]."])

    result = build_runtime(retriever, provider).run(AgentRequest(question=q))

    assert result.grounded is True
    assert result.capability == "qa"
    assert not result.text.strip().startswith("{")
    assert "Stewart Butterfield emphasizes" in result.text
    assert len(result.citations) == 1


def test_capability_routing_distinguishes_qa_essay_and_artifact():
    from app.agent.routing import route_capability

    assert route_capability("What does Stewart Butterfield say about communication?") == "qa"
    assert route_capability("Why does Stewart Butterfield think communicating a product's value matters?") == "qa"
    assert route_capability("Write a Ship 30 for 30 essay about Stewart Butterfield's views on communication.") == "essay"
    assert route_capability("Create a visual summary of Stewart Butterfield's product principles.") == "artifact"
    assert route_capability("Build a Markdown checklist of PMF tactics") == "artifact"
    assert route_capability("Draft a newsletter essay on retention") == "essay"
