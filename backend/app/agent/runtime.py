"""Agent runtime factory.

AGENT_RUNTIME:
  auto        -> Claude Agent SDK when it is genuinely available, else local
  claude_sdk  -> Claude Agent SDK, hard error if unavailable
  local       -> local tool-loop adapter

Both runtimes share tools, prompts and the grounding gate.
"""

from __future__ import annotations

from app.agent.claude_sdk_runtime import ClaudeSDKAgentRuntime, claude_sdk_available
from app.agent.contracts import AgentRequest, AgentResult, AgentRuntime  # noqa: F401
from app.agent.local_runtime import LocalAgentRuntime
from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.providers import get_provider
from app.providers.base import LLMProvider
from app.retrieval.types import Retriever

logger = get_logger(__name__)


def resolve_runtime_name(settings: Settings | None = None) -> tuple[str, str | None]:
    """Return (runtime_name, fallback_reason)."""
    settings = settings or get_settings()
    if settings.agent_runtime == "local":
        return "local", None
    available, reason = claude_sdk_available(settings)
    if settings.agent_runtime == "claude_sdk":
        return "claude_sdk", None if available else reason
    if settings.llm_provider == "anthropic" and available:
        return "claude_sdk", None
    return "local", reason if settings.llm_provider == "anthropic" else None


def build_agent_runtime(
    retriever: Retriever,
    *,
    provider: LLMProvider | None = None,
    settings: Settings | None = None,
) -> AgentRuntime:
    settings = settings or get_settings()
    provider = provider or get_provider()
    name, reason = resolve_runtime_name(settings)
    if name == "claude_sdk":
        return ClaudeSDKAgentRuntime(retriever=retriever, provider=provider, settings=settings)
    if reason:
        logger.info("agent_runtime_fallback", extra={"runtime": "local", "reason": reason})
    return LocalAgentRuntime(retriever=retriever, provider=provider, settings=settings)
