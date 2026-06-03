"""FastAPI app.

/login issues a password-gated JWT. /chat streams the agent's answer over SSE
(behind the token) with per-session Redis working memory. Conversations and full
transcripts are persisted in SQLite (the durable sidebar + history); Redis holds
the summarized working memory per session.
"""

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agentic_vault import db
from agentic_vault import guard
from agentic_vault import memory
from agentic_vault import session as sessions
from agentic_vault.agent import stream_agent
from agentic_vault.auth import check_password, issue, require_auth

app = FastAPI(title="agentic-vault")
db.init_db()

_STATIC_DIR = Path(__file__).parent / "static"
_SOURCE_RE = re.compile(r"\[([^\]\n]+?\.md)\]")

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


def _title(message: str) -> str:
    words = message.split()
    return " ".join(words[:7]) + ("…" if len(words) > 7 else "")


def _sources(text: str) -> list[str]:
    seen: list[str] = []
    for name in _SOURCE_RE.findall(text):
        if name not in seen:
            seen.append(name)
    return seen


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _tool_detail(name: str, inp: object) -> str:
    if not isinstance(inp, dict):
        return ""
    return str(inp.get("query") or inp.get("expression") or "")


@app.get("/")
async def login_page() -> FileResponse:
    """The sign-in page (public)."""
    return FileResponse(_STATIC_DIR / "login.html")


@app.get("/app")
async def app_page() -> FileResponse:
    """The chat app shell (public HTML; the page checks the token client-side)."""
    return FileResponse(_STATIC_DIR / "app.html")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: int


class MessageOut(BaseModel):
    role: str
    content: str
    sources: list[str]


@app.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    if not check_password(req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password"
        )
    return TokenResponse(token=issue("user"))


@app.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    subject: Annotated[str, Depends(require_auth)],
) -> list[ConversationSummary]:
    return [ConversationSummary(**c) for c in db.list_conversations()]


@app.get("/conversations/{conversation_id}", response_model=list[MessageOut])
async def conversation_messages(
    conversation_id: str,
    subject: Annotated[str, Depends(require_auth)],
) -> list[MessageOut]:
    return [MessageOut(**m) for m in db.get_messages(conversation_id)]


@app.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    subject: Annotated[str, Depends(require_auth)],
) -> None:
    db.delete_conversation(conversation_id)


@app.post("/chat")
async def chat(
    req: ChatRequest,
    subject: Annotated[str, Depends(require_auth)],
) -> StreamingResponse:
    # ---- pre-guard: length cap + input moderation, before the model runs ----
    async def refusal(text: str) -> AsyncIterator[str]:
        yield _sse({"type": "token", "text": text})
        yield _sse({"type": "guard", "ok": False})
        yield _sse({"type": "done"})

    if len(req.message) > guard.MAX_INPUT_CHARS:
        return StreamingResponse(
            refusal(
                f"That message is too long ({len(req.message)} characters; the "
                f"limit is {guard.MAX_INPUT_CHARS}). Please shorten it."
            ),
            media_type="text/event-stream",
        )
    if await guard.is_flagged(req.message):
        return StreamingResponse(
            refusal(guard.INPUT_REFUSAL), media_type="text/event-stream"
        )

    state = await sessions.load(req.session_id)
    memories = await memory.get_memories()
    history = sessions.to_messages(state, req.message, memories)

    async def events() -> AsyncIterator[str]:
        parts: list[str] = []
        sources: list[str] = []
        async for ev in stream_agent(history):
            if ev["type"] == "token":
                parts.append(ev["text"])
                yield _sse({"type": "token", "text": ev["text"]})
            elif ev["type"] == "tool":
                if ev["name"] == "save_memory":
                    inp = ev.get("input") if isinstance(ev.get("input"), dict) else {}
                    if "saved" in (ev.get("output", "") or "").lower():
                        yield _sse({"type": "memory", "text": inp.get("fact", "")})
                    continue
                is_retriever = ev["name"] == "search_rust_notes"
                src = _sources(ev.get("output", "")) if is_retriever else []
                for s in src:
                    if s not in sources:
                        sources.append(s)
                yield _sse(
                    {
                        "type": "tool",
                        "name": ev["name"],
                        "detail": _tool_detail(ev["name"], ev.get("input")),
                        "sources": src,
                        "result": "" if is_retriever else ev.get("output", "")[:40],
                    }
                )

        # ---- post-guard: validate + moderate the final answer (fail closed) ----
        reply = "".join(parts)
        validated = guard.validate_output(reply, sources)
        flagged = await guard.is_flagged(reply) if reply else False
        if validated is None or flagged:
            reply = guard.OUTPUT_FALLBACK
            sources = []
            yield _sse({"type": "replace", "text": reply})
            yield _sse({"type": "guard", "ok": False})
        else:
            yield _sse({"type": "guard", "ok": True})

        new_state = await sessions.append_turn(state, req.message, reply)
        await sessions.save(req.session_id, new_state)
        db.append_exchange(
            req.session_id, _title(req.message), req.message, reply, sources
        )
        yield _sse({"type": "done"})

    return StreamingResponse(events(), media_type="text/event-stream")
