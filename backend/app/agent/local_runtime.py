"""Local agent runtime.

A real tool-calling loop that works with any configured provider (Ollama first,
Anthropic/OpenAI too). It uses the SAME tools, prompts and grounding rules as
the Claude Agent SDK runtime, so switching runtimes cannot change behaviour.

Loop shape:
  1. Seed retrieval with the user's question (guarantees grounding is attempted
     even with a small local model that under-calls tools).
  2. Let the model call tools for up to AGENT_MAX_TOOL_STEPS steps.
  3. Enforce the grounding gate: no evidence -> the canned insufficient-evidence
     response, never a general-knowledge answer.
  4. Finalise per capability (QA answer / Ship 30 essay / artifact).
"""

from __future__ import annotations

import time
from typing import Any

from app.agent.contracts import AgentRequest, AgentResult, ToolInvocation
from app.agent.prompts import (
    INSUFFICIENT_EVIDENCE_RESPONSE,
    SYSTEM_PROMPT,
    TOOL_SYSTEM_PROMPT,
    grounded_answer_prompt,
    resolve_citations,
)
from app.agent.routing import extract_query_topic, preferred_artifact_kind, route_capability
from app.agent.tools import TOOL_SPECS, ToolContext, execute_tool
from app.config import Settings, get_settings
from app.errors import ProviderError
from app.logging_config import get_logger
from app.providers.base import LLMProvider
from app.retrieval.types import Retriever

logger = get_logger(__name__)

MAX_HISTORY_MESSAGES = 10


class LocalAgentRuntime:
    name = "local"

    def __init__(
        self,
        *,
        retriever: Retriever,
        provider: LLMProvider,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider
        self.retriever = retriever
        self.context = ToolContext(retriever=retriever, provider=provider, settings=self.settings)

    def run(self, request: AgentRequest) -> AgentResult:
        started = time.perf_counter()
        capability = route_capability(request.question, request.requested_capability)
        invocations: list[ToolInvocation] = []
        self.context = ToolContext(retriever=self.retriever, provider=self.provider, settings=self.settings)
        context = self.context

        logger.info(
            "agent_run_start",
            extra={"runtime": self.name, "capability": capability, "provider": self.provider.name},
        )

        # 1. Seeded retrieval — the agent always grounds before reasoning.
        query = extract_query_topic(request.question) or request.question
        invocations.append(
            self._invoke("search_transcripts", {"query": query, "top_k": request.top_k})
        )

        # 2. Grounding gate — refuse immediately if evidence is insufficient.
        if not context.has_sufficient_evidence:
            logger.info(
                "agent_refused_ungrounded",
                extra={"runtime": self.name, "capability": capability, "searches": context.searches},
            )
            return self._result(
                text=INSUFFICIENT_EVIDENCE_RESPONSE,
                capability=capability,
                grounded=False,
                invocations=invocations,
                started=started,
                notes={"reason": "no_relevant_evidence", "searches": context.searches},
            )

        # 3. Model-driven tool loop (scoped by capability to prevent cross-capability tool misfires).
        if capability == "qa":
            available_tools = [t for t in TOOL_SPECS if t.name == "search_transcripts"]
            system_prompt = SYSTEM_PROMPT
        elif capability == "essay":
            available_tools = [t for t in TOOL_SPECS if t.name in {"search_transcripts", "write_ship30_essay"}]
            system_prompt = TOOL_SYSTEM_PROMPT
        elif capability == "artifact":
            available_tools = [t for t in TOOL_SPECS if t.name in {"search_transcripts", "generate_artifact"}]
            system_prompt = TOOL_SYSTEM_PROMPT
        else:
            available_tools = TOOL_SPECS
            system_prompt = TOOL_SYSTEM_PROMPT

        messages = self._build_messages(request, context)
        steps = 0
        final_text = ""
        tools_to_pass = available_tools if (self.provider.name != "ollama" or capability != "qa") else None
        while steps < self.settings.agent_max_tool_steps:
            steps += 1
            try:
                completion = self.provider.complete(
                    system=system_prompt,
                    messages=messages,
                    tools=tools_to_pass,
                )
            except ProviderError:
                raise
            if not completion.tool_calls:
                final_text = (completion.text or "").strip()
                context.generation_latency_ms += completion.latency_ms
                break
            for call in completion.tool_calls:
                invocation = self._invoke(call.name, call.arguments)
                invocations.append(invocation)
                messages.append(
                    {"role": "assistant", "content": f"[tool_call] {call.name}({call.arguments})"}
                )
                messages.append({"role": "user", "content": f"[tool_result] {invocation.summary}"})
                if context.artifact is not None or context.essay is not None:
                    break
            if context.artifact is not None or context.essay is not None:
                break

        # 4. Capability finalisation.
        if capability == "essay":
            if context.essay is None:
                invocations.append(self._invoke("write_ship30_essay", {"topic": request.question}))
            if context.essay is None:
                raise ProviderError("The Ship 30 skill did not produce an essay.")
            return self._result(
                text=context.essay.markdown,
                capability=capability,
                grounded=True,
                invocations=invocations,
                started=started,
                word_count=context.essay.word_count,
                notes={"essay_title": context.essay.title, "target_words": 1250},
            )

        if capability == "artifact":
            if context.artifact is None:
                invocations.append(
                    self._invoke(
                        "generate_artifact",
                        {
                            "kind": preferred_artifact_kind(request.question),
                            "instruction": request.question,
                        },
                    )
                )
            if context.artifact is None:
                raise ProviderError("Artifact generation did not produce an artifact.")
            summary = final_text or (
                f"I built a {context.artifact.kind} artifact — “{context.artifact.title}” — "
                f"grounded in {len(context.top_evidence())} transcript excerpts. It's open in the "
                "Artifact Viewer."
            )
            return self._result(
                text=summary,
                capability=capability,
                grounded=True,
                invocations=invocations,
                started=started,
                notes={"artifact_title": context.artifact.title, "artifact_kind": context.artifact.kind},
            )

        # QA: always finish with an explicitly grounded completion.
        answer = final_text
        if (
            not answer
            or "[tool_call]" in answer
            or answer.strip().startswith("{")
            or "function" in answer
        ):
            completion = self.provider.complete(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": grounded_answer_prompt(request.question, context.top_evidence())}],
            )
            answer = (completion.text or "").strip()
            context.generation_latency_ms += completion.latency_ms
        if not answer:
            raise ProviderError("The model returned an empty answer.")
        return self._result(
            text=answer,
            capability=capability,
            grounded=True,
            invocations=invocations,
            started=started,
        )

    # --- helpers -----------------------------------------------------------

    def _invoke(self, name: str, arguments: dict[str, Any]) -> ToolInvocation:
        cleaned = {key: value for key, value in (arguments or {}).items() if value is not None}
        output, latency_ms, ok = execute_tool(self.context, name, cleaned)
        return ToolInvocation(name=name, arguments=cleaned, latency_ms=latency_ms, summary=output, ok=ok)

    def _build_messages(self, request: AgentRequest, context: ToolContext) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for message in (request.history or [])[-MAX_HISTORY_MESSAGES:]:
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content[:1500]})
        messages.append(
            {"role": "user", "content": grounded_answer_prompt(request.question, context.top_evidence())}
        )
        return messages

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
            provider=self.provider.name,
            model=self.provider.model,
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
                "retrieval_latency_ms": round(result.retrieval_latency_ms, 1),
                "generation_latency_ms": round(result.generation_latency_ms, 1),
            },
        )
        return result
