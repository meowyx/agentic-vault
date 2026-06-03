"""Test setup.

Set dummy env vars BEFORE importing the app so config loads without a real .env
or real credentials, then provide a TestClient whose external dependencies (the
agent/OpenAI, Redis sessions, SQLite, moderation) are mocked. This keeps route
tests fast, offline, deterministic, and free.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "test")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "test")
os.environ.setdefault("LANGFUSE_BASE_URL", "https://example.test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("VAULT_CORPUS_PATH", "/tmp")
os.environ.setdefault("JWT_SECRET", "0" * 64)  # 32+ bytes, avoids the key-length warning
os.environ.setdefault("APP_PASSWORD", "test-password")

TEST_PASSWORD = "test-password"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from agentic_vault import db, guard, main, memory
    from agentic_vault import session as sessions

    # no real Redis / SQLite / OpenAI during route tests
    async def empty_state(_session_id):
        return {"summary": "", "messages": []}

    async def passthrough(state, *_args, **_kwargs):
        return state

    async def noop_async(*_args, **_kwargs):
        return None

    async def no_memories():
        return []

    async def not_flagged(_text):
        return False

    monkeypatch.setattr(sessions, "load", empty_state)
    monkeypatch.setattr(sessions, "save", noop_async)
    monkeypatch.setattr(sessions, "append_turn", passthrough)
    monkeypatch.setattr(memory, "get_memories", no_memories)
    monkeypatch.setattr(guard, "is_flagged", not_flagged)
    monkeypatch.setattr(db, "append_exchange", lambda *a, **k: None)
    monkeypatch.setattr(db, "list_conversations", lambda: [])
    monkeypatch.setattr(db, "get_messages", lambda _cid: [])
    monkeypatch.setattr(db, "delete_conversation", lambda _cid: None)

    # a fake agent: one tool call, then two answer tokens
    async def fake_stream(_messages):
        yield {
            "type": "tool",
            "name": "search_rust_notes",
            "input": {"query": "ownership"},
            "output": "[rust 8 - ownership.md]\nsome retrieved context",
        }
        yield {"type": "token", "text": "Hello "}
        yield {"type": "token", "text": "world"}

    monkeypatch.setattr(main, "stream_agent", fake_stream)

    return TestClient(main.app)


@pytest.fixture
def token(client):
    return client.post("/login", json={"password": TEST_PASSWORD}).json()["token"]


@pytest.fixture
def auth_header(token):
    return {"Authorization": f"Bearer {token}"}
