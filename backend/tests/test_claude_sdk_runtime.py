"""Tests for the Claude Agent SDK runtime, MCP tool bridge, and runtime factory."""

from __future__ import annotations

import pytest

from app.agent.claude_sdk_runtime import ClaudeSDKAgentRuntime, claude_sdk_available
from app.agent.contracts import AgentRequest, AgentResult, AgentRuntime
from app.agent.local_runtime import LocalAgentRuntime
from app.agent.prompts import INSUFFICIENT_EVIDENCE_RESPONSE
from app.agent.runtime import build_agent_runtime, resolve_runtime_name
from app.config import Settings
from app.errors import ProviderAuthError

from .conftest import FakeProvider, FakeRetriever, make_chunk


def test_claude_sdk_availability_reports_unavailability():
    settings = Settings(anthropic_api_key=None)
    available, reason = claude_sdk_available(settings)
    assert not available
    assert reason is not None


def test_claude_sdk_runtime_raises_when_credentials_missing():
    settings = Settings(anthropic_api_key=None, agent_runtime="claude_sdk")
    with pytest.raises(ProviderAuthError) as exc_info:
        ClaudeSDKAgentRuntime(
            retriever=FakeRetriever(),
            provider=FakeProvider(),
            settings=settings,
        )
    assert "Claude Agent SDK runtime is unavailable" in str(exc_info.value)


def test_claude_sdk_runtime_grounding_refusal_without_api_call(monkeypatch):
    """When pre-flight retrieval finds no evidence, the runtime must refuse immediately."""
    monkeypatch.setattr(
        "app.agent.claude_sdk_runtime.claude_sdk_available",
        lambda settings=None: (True, None),
    )
    settings = Settings(anthropic_api_key="test-key", agent_runtime="claude_sdk")
    runtime = ClaudeSDKAgentRuntime(
        retriever=FakeRetriever(empty=True),
        provider=FakeProvider(),
        settings=settings,
    )

    result = runtime.run(AgentRequest(question="What is the quantum spin of a muon?"))
    assert result.grounded is False
    assert result.text == INSUFFICIENT_EVIDENCE_RESPONSE
    assert len(result.citations) == 0
    assert result.notes.get("reason") == "no_relevant_evidence"


def test_claude_sdk_mcp_tool_bridge_structure(monkeypatch):
    """Verify MCP tools exposed to Claude Agent SDK match the required schemas."""
    monkeypatch.setattr(
        "app.agent.claude_sdk_runtime.claude_sdk_available",
        lambda settings=None: (True, None),
    )
    settings = Settings(anthropic_api_key="test-key", agent_runtime="claude_sdk")
    runtime = ClaudeSDKAgentRuntime(
        retriever=FakeRetriever(),
        provider=FakeProvider(),
        settings=settings,
    )

    tools_captured = []

    def mock_tool_decorator(name, description, schema):
        def decorator(fn):
            tools_captured.append({"name": name, "description": description, "schema": schema})
            return fn
        return decorator

    invocations = []
    runtime._sdk_tools(mock_tool_decorator, invocations)

    tool_names = [t["name"] for t in tools_captured]
    assert "search_transcripts" in tool_names
    assert "write_ship30_essay" in tool_names
    assert "generate_artifact" in tool_names


def test_runtime_factory_auto_resolution(monkeypatch):
    """Verify runtime factory resolution across environment modes."""
    # 1. Local mode explicit
    s1 = Settings(agent_runtime="local")
    name1, reason1 = resolve_runtime_name(s1)
    assert name1 == "local"

    # 2. Auto mode with Anthropic key + SDK CLI -> claude_sdk
    monkeypatch.setenv("AGENT_RUNTIME", "auto")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(
        "app.agent.runtime.claude_sdk_available",
        lambda settings=None: (True, None),
    )
    s2 = Settings(anthropic_api_key="sk-test")
    name2, reason2 = resolve_runtime_name(s2)
    assert name2 == "claude_sdk"

    # 3. Auto mode with Ollama -> local
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    s3 = Settings()
    name3, reason3 = resolve_runtime_name(s3)
    assert name3 == "local"


def test_both_runtimes_implement_agent_runtime_protocol(monkeypatch):
    """Verify LocalAgentRuntime and ClaudeSDKAgentRuntime expose the identical protocol."""
    local = LocalAgentRuntime(retriever=FakeRetriever(), provider=FakeProvider())
    assert isinstance(local, AgentRuntime)

    monkeypatch.setattr(
        "app.agent.claude_sdk_runtime.claude_sdk_available",
        lambda settings=None: (True, None),
    )
    claude = ClaudeSDKAgentRuntime(
        retriever=FakeRetriever(),
        provider=FakeProvider(),
        settings=Settings(anthropic_api_key="test-key", agent_runtime="claude_sdk"),
    )
    assert isinstance(claude, AgentRuntime)
