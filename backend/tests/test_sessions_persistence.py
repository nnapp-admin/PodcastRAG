"""Session persistence and isolation.

The assignment requires per-session conversation memory that survives reloads
and never leaks across sessions.
"""

from __future__ import annotations

from app.schemas import ChatResponse, SessionDetailResponse


def _send(client, session, message):
    response = client.post(f"/sessions/{session}/messages", json={"message": message})
    assert response.status_code == 200, response.text
    return ChatResponse.model_validate(response.json())


def test_history_survives_a_reload(client, session_id):
    _send(client, session_id, "What signals product-market fit?")
    _send(client, session_id, "And how do I measure it weekly?")

    detail = SessionDetailResponse.model_validate(client.get(f"/sessions/{session_id}").json())
    roles = [message.role for message in detail.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert detail.session.message_count == 4
    assert detail.messages[0].content == "What signals product-market fit?"
    # Citations were persisted, not just returned in the live response.
    assert detail.messages[1].citations


def test_sessions_are_isolated(client):
    first = client.post("/sessions", json={}).json()["id"]
    second = client.post("/sessions", json={}).json()["id"]

    _send(client, first, "Question about retention")
    _send(client, second, "Question about pricing")

    first_detail = SessionDetailResponse.model_validate(client.get(f"/sessions/{first}").json())
    second_detail = SessionDetailResponse.model_validate(client.get(f"/sessions/{second}").json())

    assert [m.content for m in first_detail.messages if m.role == "user"] == ["Question about retention"]
    assert [m.content for m in second_detail.messages if m.role == "user"] == ["Question about pricing"]
    assert {m.id for m in first_detail.messages}.isdisjoint({m.id for m in second_detail.messages})


def test_prior_turns_are_passed_to_the_agent_for_the_same_session_only(client):
    first = client.post("/sessions", json={}).json()["id"]
    second = client.post("/sessions", json={}).json()["id"]
    _send(client, first, "Question about retention")

    client.provider.calls.clear()
    _send(client, second, "Follow-up in a different session")

    sent = "\n".join(
        message.get("content", "")
        for call in client.provider.calls
        for message in call["messages"]
    )
    assert "Question about retention" not in sent


def test_first_message_titles_the_session(client, session_id):
    _send(client, session_id, "How do I run a good user interview?")
    detail = SessionDetailResponse.model_validate(client.get(f"/sessions/{session_id}").json())
    assert detail.session.title == "How do I run a good user interview?"
    assert detail.session.last_message_at is not None


def test_deleting_a_session_removes_its_messages(client, session_id, db_sessionmaker):
    _send(client, session_id, "Question about retention")
    assert client.delete(f"/sessions/{session_id}").status_code == 204

    # 1. Direct DB verification
    import uuid
    from app.db.models import Message, Session

    session_uuid = uuid.UUID(str(session_id))
    with db_sessionmaker() as session:
        assert session.query(Message).where(Message.session_id == session_uuid).count() == 0
        assert session.query(Session).where(Session.id == session_uuid).count() == 0

    # 2. Endpoint verification: GET /sessions/{id} returns 404
    assert client.get(f"/sessions/{session_id}").status_code == 404

    # 3. List verification: GET /sessions excludes deleted session
    list_res = client.get("/sessions").json()
    assert not any(s["id"] == str(session_id) for s in list_res["sessions"])
