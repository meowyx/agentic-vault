"""Route tests: auth, the SSE contract, and the guards. The agent and external
services are mocked in conftest, so these assert the route behavior, not the LLM."""


def test_login_wrong_password(client):
    assert client.post("/login", json={"password": "nope"}).status_code == 401


def test_login_correct_password(client):
    resp = client.post("/login", json={"password": "test-password"})
    assert resp.status_code == 200
    assert resp.json()["token"]
    assert resp.json()["token_type"] == "bearer"


def test_chat_requires_a_token(client):
    resp = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert resp.status_code == 401


def test_chat_rejects_a_bad_token(client):
    resp = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hi"},
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert resp.status_code == 401


def test_chat_streams_tokens_tool_and_guard(client, auth_header):
    resp = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hi"},
        headers=auth_header,
    )
    assert resp.status_code == 200
    body = resp.text
    # the typed SSE contract
    assert '"type": "tool"' in body
    assert '"type": "token"' in body
    assert '"type": "guard"' in body  # post-guard ran
    assert "[DONE]" in body or '"type": "done"' in body
    # the streamed answer made it through
    assert "Hello " in body and "world" in body


def test_chat_length_cap_refuses(client, auth_header):
    resp = client.post(
        "/chat",
        json={"session_id": "s1", "message": "x" * 5000},
        headers=auth_header,
    )
    assert resp.status_code == 200
    assert "too long" in resp.text.lower()


def test_chat_empty_message_is_422(client, auth_header):
    resp = client.post(
        "/chat", json={"session_id": "s1", "message": ""}, headers=auth_header
    )
    assert resp.status_code == 422  # Pydantic min_length


def test_conversations_requires_a_token(client):
    assert client.get("/conversations").status_code == 401


def test_conversations_list_with_token(client, auth_header):
    resp = client.get("/conversations", headers=auth_header)
    assert resp.status_code == 200
    assert resp.json() == []
