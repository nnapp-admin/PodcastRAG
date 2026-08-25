"""Claude Agent SDK runtime backed by the real Claude Code SDK.

When selected, Claude Code runs through ``claude_agent_sdk.ClaudeSDKClient``.
The app's existing retrieval, Ship 30, and artifact functions are exposed as an
in-process SDK MCP server. Ollama continues to use ``LocalAgentRuntime``.
"""

from __future__ import annotations

import shutil
import time
from typing import Any

import anyio

from app.agent.contracts import AgentRequest, AgentResult, ToolInvocation
from app.agent.prompts import (
    INSUFFICIENT_EVIDENCE_RESPONSE,
    TOOL_SYSTEM_PROMPT,
    resolve_citations,
)
from app.agent.routing import extract_query_topic, preferred_artifact_kind, route_capability
from app.agent.tools import ToolContext, execute_tool
from app.config import Settings, get_settings
from app.errors import ProviderAuthError, ProviderError, ProviderUnavailableError
from app.logging_config import get_logger
from app.providers.base import LLMProvider
from app.retrieval.types import Retriever

logger = get_logger(__name__)

MAX_HISTORY_MESSAGES = 10
MCP_SERVER_NAME = "lenny_growth"


def claude_sdk_available(settings: Settings | None = None) -> tuple[bool, str | None]:
    """Check the actual SDK, its Claude Code executable, and credentials."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:  # pragma: no cover - depends on install
        return False, "The `claude-agent-sdk` package is not installed."
    if shutil.which("claude") is None:
        return False, "Claude Code CLI is not installed or is not on PATH."
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        return False, "ANTHROPIC_API_KEY is not set."
    return True, None


class ClaudeSDKAgentRuntime:
    """Adapter that drives the shared tool layer through Claude Agent SDK MCP."""

    name = "claude_sdk"

    def __init__(
        self,
        *,
        retriever: Retriever,
        provider: LLMProvider,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        available, reason = claude_sdk_available(self.settings)
        if not available:
            raise ProviderAuthError(
                f"The Claude Agent SDK runtime is unavailable: {reason}",
                details={
                    "fix": "Install Claude Code and `claude-agent-sdk`, set ANTHROPIC_API_KEY, "
                    "or set AGENT_RUNTIME=local for Ollama.",
                },
            )
        self.provider = provider
        self.retriever = retriever
        self.model = self.settings.llm_model
        self.context = ToolContext(retriever=retriever, provider=provider, settings=self.settings)

    def run(self, request: AgentRequest) -> AgentResult:
        started = time.perf_counter()
        capability = route_capability(request.question, request.requested_capability)
        self.context = ToolContext(retriever=self.retriever, provider=self.provider, settings=self.settings)
        context = self.context
        query = extract_query_topic(request.question) or request.question
        invocations: list[ToolInvocation] = [
            self._invoke("search_transcripts", {"query": query, "top_k": request.top_k})
        ]

        if not context.has_sufficient_evidence:
            return self._result(
                text=INSUFFICIENT_EVIDENCE_RESPONSE,
                capability=capability,
                grounded=False,
                invocations=invocations,
                started=started,
                notes={"reason": "no_relevant_evidence", "searches": context.searches},
            )

        final_text = anyio.run(self._run_sdk, request, capability, invocations)

        # Keep deterministic capability completion if Claude provides prose
        # instead of calling the requested tool.
        if capability == "essay" and context.essay is None:
            invocations.append(self._invoke("write_ship30_essay", {"topic": request.question}))
        if capability == "artifact" and context.artifact is None:
            invocations.append(
                self._invoke(
                    "generate_artifact",
                    {"kind": preferred_artifact_kind(request.question), "instruction": request.question},
                )
            )

        if capability == "essay" and context.essay is not None:
            return self._result(
                text=context.essay.markdown,
                capability=capability,
                grounded=True,
                invocations=invocations,
                started=started,
                word_count=context.essay.word_count,
                notes={"essay_title": context.essay.title},
            )
        if capability == "artifact" and context.artifact is not None:
            return self._result(
                text=final_text or f"I built “{context.artifact.title}” — it's open in the Artifact Viewer.",
                capability=capability,
                grounded=True,
                invocations=invocations,
                started=started,
                notes={"artifact_title": context.artifact.title, "artifact_kind": context.artifact.kind},
            )
        if not final_text:
            raise ProviderError("The Claude Agent SDK run produced no answer text.")
        return self._result(
            text=final_text,
            capability=capability,
            grounded=True,
            invocations=invocations,
            started=started,
        )

    async def _run_sdk(
        self,
        request: AgentRequest,
        capability: str,
        invocations: list[ToolInvocation],
    ) -> str:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ClaudeSDKError,
            ResultMessage,
            TextBlock,
            create_sdk_mcp_server,
            tool,
        )

        server = create_sdk_mcp_server(name=MCP_SERVER_NAME, tools=self._sdk_tools(tool, invocations))
        if capability == "qa":
            allowed_tools = [f"mcp__{MCP_SERVER_NAME}__search_transcripts"]
        elif capability == "essay":
            allowed_tools = [
                f"mcp__{MCP_SERVER_NAME}__search_transcripts",
                f"mcp__{MCP_SERVER_NAME}__write_ship30_essay",
            ]
        elif capability == "artifact":
            allowed_tools = [
                f"mcp__{MCP_SERVER_NAME}__search_transcripts",
                f"mcp__{MCP_SERVER_NAME}__generate_artifact",
            ]
        else:
            allowed_tools = [
                f"mcp__{MCP_SERVER_NAME}__search_transcripts",
                f"mcp__{MCP_SERVER_NAME}__write_ship30_essay",
                f"mcp__{MCP_SERVER_NAME}__generate_artifact",
            ]

        options = ClaudeAgentOptions(
            system_prompt=TOOL_SYSTEM_PROMPT,
            model=self.model,
            max_turns=self.settings.agent_max_tool_steps,
            mcp_servers={MCP_SERVER_NAME: server},
            allowed_tools=allowed_tools,
            # Sent only to the Claude Code child process, never persisted.
            env={"ANTHROPIC_API_KEY": self.settings.anthropic_api_key or ""},
        )
        text_parts: list[str] = []
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(self._sdk_prompt(request, capability, invocations[0].summary))
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        text_parts.extend(
                            block.text.strip()
                            for block in message.content
                            if isinstance(block, TextBlock) and block.text.strip()
                        )
                    elif isinstance(message, ResultMessage) and message.result and not text_parts:
                        text_parts.append(message.result.strip())
        except ClaudeSDKError as exc:
            raise ProviderUnavailableError(
                f"Claude Agent SDK execution failed: {exc}",
                details={"runtime": self.name, "fix": "Check Claude Code installation and ANTHROPIC_API_KEY."},
            ) from exc
        return "\n\n".join(text_parts).strip()

    def _sdk_tools(self, tool_decorator: Any, invocations: list[ToolInvocation]) -> list[Any]:
        """Bridge the existing synchronous tool handlers into SDK MCP handlers."""

        def make_tool(name: str, description: str, schema: dict[str, Any]) -> Any:
            @tool_decorator(name, description, schema)
            async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
                invocation = self._invoke(name, arguments)
                invocations.append(invocation)
                return {
                    "content": [{"type": "text", "text": invocation.summary}],
                    "is_error": not invocation.ok,
                }

            return handler

        return [
            make_tool(
                "search_transcripts",
                "Search indexed Lenny transcript excerpts before answering.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                    "required": ["query"],
                },
            ),
            make_tool(
                "write_ship30_essay",
                "Write a grounded Ship 30 essay from gathered transcript evidence.",
                {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]},
            ),
            make_tool(
                "generate_artifact",
                "Generate a grounded Markdown or HTML artifact from gathered evidence.",
                {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["markdown", "html"]},
                        "instruction": {"type": "string"},
                    },
                    "required": ["kind", "instruction"],
                },
            ),
        ]

    def _sdk_prompt(self, request: AgentRequest, capability: str, seed_result: str) -> str:
        history = []
        for message in (request.history or [])[-MAX_HISTORY_MESSAGES:]:
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                history.append(f"{role}: {content[:4000]}")
        hint = {
            "essay": "Call write_ship30_essay after reviewing the evidence.",
            "artifact": f"Call generate_artifact with kind '{preferred_artifact_kind(request.question)}'.",
            "qa": "Answer only from the evidence and cite it inline as [n].",
        }[capability]
        return "\n\n".join(
            [
                "CONVERSATION HISTORY:\n" + ("\n".join(history) or "(none)"),
                f"USER QUESTION:\n{request.question}",
                f"PRE-FLIGHT RETRIEVAL (already run):\n{seed_result}",
                f"ROUTING INSTRUCTION: {hint}",
            ]
        )

    def _invoke(self, name: str, arguments: dict[str, Any]) -> ToolInvocation:
        cleaned = {key: value for key, value in (arguments or {}).items() if value is not None}
        output, latency_ms, ok = execute_tool(self.context, name, cleaned)
        return ToolInvocation(name=name, arguments=cleaned, latency_ms=latency_ms, summary=output, ok=ok)

    def _result(
        self,
        *,
        text: str,
        capability: str,
        grounded: bool,
        invocations: list[ToolInvocation],
        started: float,
        word_count: int | None = None,
        notes: dict[str, Any] | None = None,
    ) -> AgentResult:
        context = self.context
        result = AgentResult(
            text=text,
            capability=capability,  # type: ignore[arg-type]
            grounded=grounded,
            citations=resolve_citations(text, context.top_evidence(), capability) if grounded else [],
            artifact=context.artifact,
            tool_invocations=invocations,
            runtime=self.name,
            provider="anthropic",
            model=self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
            retrieval_latency_ms=context.retrieval_latency_ms,
            generation_latency_ms=context.generation_latency_ms,
            word_count=word_count,
            notes=notes or {},
        )
        logger.info(
            "agent_run_end",
            extra={
                "runtime": self.name,
                "capability": result.capability,
                "grounded": result.grounded,
                "citations": len(result.citations),
                "tool_calls": len(invocations),
                "latency_ms": round(result.latency_ms, 1),
            },
        )
        return result
