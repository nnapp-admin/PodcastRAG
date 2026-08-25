"""API contract tests: status codes, response shape, and the single error envelope."""

from __future__ import annotations

import uuid

from app.schemas import (
    ArtifactListResponse,
    ChatResponse,
    HealthResponse,
    RetrievalResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)


def test_health_reports_every_component(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = HealthResponse.model_validate(response.json())
    assert payload.status in {"ok", "degraded", "error"}
    assert {"database", "provider", "retrieval", "agent"} <= set(payload.components)
    assert payload.provider == "fake"
    assert payload.agent_runtime in {"local", "claude_sdk"}


def test_request_id_header_is_echoed(client):
    response = client.get("/health", headers={"x-request-id": "req-123"})
    assert response.headers["x-request-id"] == "req-123"


def test_session_lifecycle_matches_contract(client):
    created = client.post("/sessions", json={"title": "PMF research"})
    assert created.status_code == 201
    session = SessionResponse.model_validate(created.json())
    assert session.title == "PMF research"
    assert session.message_count == 0

    listed = SessionListResponse.model_validate(client.get("/sessions").json())
    assert [s.id for s in listed.sessions] == [session.id]

    detail = SessionDetailResponse.model_validate(client.get(f"/sessions/{session.id}").json())
    assert detail.messages == []

    assert client.delete(f"/sessions/{session.id}").status_code == 204
    assert client.get(f"/sessions/{session.id}").status_code == 404


def test_chat_response_matches_contract(client, session_id):
    response = client.post(f"/sessions/{session_id}/messages", json={"message": "What signals PMF?"})
    assert response.status_code == 200, response.text
    payload = ChatResponse.model_validate(response.json())
    assert payload.user_message.role == "user"
    assert payload.assistant_message.role == "assistant"
    assert payload.assistant_message.grounded is True
    assert payload.assistant_message.citations
    assert payload.assistant_message.provider == "fake"
    assert payload.assistant_message.latency_ms is not None


def test_search_endpoint_matches_contract(client):
    response = client.post("/retrieval/search", json={"query": "retention", "top_k": 2})
    assert response.status_code == 200
    payload = RetrievalResponse.model_validate(response.json())
    assert payload.chunk_count == len(payload.results) == 2
    assert all(citation.excerpt for citation in payload.results)


def test_session_artifacts_endpoint_matches_contract(client, session_id):
    payload = ArtifactListResponse.model_validate(
        client.get(f"/sessions/{session_id}/artifacts").json()
    )
    assert payload.artifacts == []


# --- error envelope -------------------------------------------------------


def _assert_envelope(body: dict, code: str) -> None:
    assert set(body) >= {"error"}
    error = body["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert "details" in error
    assert "request_id" in error


def test_unknown_session_returns_not_found_envelope(client):
    response = client.post(f"/sessions/{uuid.uuid4()}/messages", json={"message": "hi"})
    assert response.status_code == 404
    _assert_envelope(response.json(), "not_found")


def test_invalid_payload_returns_validation_envelope(client, session_id):
    response = client.post(f"/sessions/{session_id}/messages", json={"message": ""})
    assert response.status_code == 422
    _assert_envelope(response.json(), "validation_failed")


def test_unknown_route_returns_envelope(client):
    response = client.get("/nope")
    assert response.status_code == 404
    _assert_envelope(response.json(), "not_found")


def test_empty_knowledge_base_returns_actionable_error(client):
    client.retriever.chunks = []
    session = client.post("/sessions", json={}).json()["id"]
    response = client.post(f"/sessions/{session}/messages", json={"message": "What signals PMF?"})
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "knowledge_base_empty"
    assert "ingest" in body["error"]["message"].lower()


def test_provider_failure_surfaces_structured_error(client, session_id):
    from app.errors import ProviderUnavailableError

    def boom(**_kwargs):
        raise ProviderUnavailableError("Cannot reach Ollama.", details={"provider": "fake"})

    client.provider.complete = boom  # type: ignore[method-assign]
    response = client.post(f"/sessions/{session_id}/messages", json={"message": "What signals PMF?"})
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"
    assert body["error"]["details"]["provider"] == "fake"
