"""SQLite persistence for the conversation sidebar and transcripts.

Redis holds the agent's working memory per session (summarized, TTL'd). This
SQLite store is the durable record: the sidebar list and full transcripts that
survive restarts and page refreshes. A conversation's id is its session id (1:1).
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import TypedDict

DB_PATH = Path("conversations.db")


class ConversationRow(TypedDict):
    id: str
    title: str
    updated_at: int


class MessageRow(TypedDict):
    role: str
    content: str
    sources: list[str]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id         TEXT PRIMARY KEY,
            title      TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            sources         TEXT NOT NULL DEFAULT '[]',
            created_at      INTEGER NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
        """
    )
    conn.commit()
    conn.close()


def list_conversations(limit: int = 200) -> list[ConversationRow]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        ConversationRow(id=r["id"], title=r["title"], updated_at=r["updated_at"])
        for r in rows
    ]


def get_messages(conversation_id: str) -> list[MessageRow]:
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content, sources FROM messages "
        "WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    conn.close()
    return [
        MessageRow(role=r["role"], content=r["content"], sources=json.loads(r["sources"]))
        for r in rows
    ]


def append_exchange(
    conversation_id: str,
    title: str,
    user_message: str,
    assistant_message: str,
    sources: list[str],
) -> None:
    """Persist one user/assistant exchange. Title is set on first insert only."""
    now = int(time.time())
    conn = _connect()
    conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at",
        (conversation_id, title, now, now),
    )
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, sources, created_at) "
        "VALUES (?, 'user', ?, '[]', ?)",
        (conversation_id, user_message, now),
    )
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, sources, created_at) "
        "VALUES (?, 'assistant', ?, ?, ?)",
        (conversation_id, assistant_message, json.dumps(sources), now),
    )
    conn.commit()
    conn.close()


def delete_conversation(conversation_id: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()
