"""Redis-backed conversation sessions.

History is stored per session id with a sliding TTL. When a session grows past
MAX_MESSAGES, the oldest turns are folded into a running summary so the context
sent to the model stays bounded across a long conversation. Turns are stored as
simple {role, content} records (not raw graph messages), so replaying history
never produces dangling tool-call/tool-result pairs.
"""

import json
from functools import lru_cache
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from redis.asyncio import Redis

from agentic_vault.config import settings

SESSION_TTL_SECONDS = 3600  # sliding 1-hour expiry, reset on every turn
MAX_MESSAGES = 10  # summarize once history grows beyond this many messages
KEEP_RECENT = 4  # messages kept verbatim after summarizing the rest

_redis = Redis.from_url(settings.redis_url, decode_responses=True)


class Turn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class SessionState(TypedDict):
    summary: str
    messages: list[Turn]


def _key(session_id: str) -> str:
    return f"session:{session_id}"


async def load(session_id: str) -> SessionState:
    raw = await _redis.get(_key(session_id))
    if raw is None:
        return {"summary": "", "messages": []}
    return json.loads(raw)


async def save(session_id: str, state: SessionState) -> None:
    await _redis.set(_key(session_id), json.dumps(state), ex=SESSION_TTL_SECONDS)


def to_messages(
    state: SessionState, new_message: str, memories: list[str] | None = None
) -> list[BaseMessage]:
    """Build the agent input: known user facts, optional summary, recent turns, new message."""
    messages: list[BaseMessage] = []
    if memories:
        facts = "\n".join(f"- {m}" for m in memories)
        messages.append(
            SystemMessage(
                f"Known facts about the user from earlier conversations:\n{facts}"
            )
        )
    if state["summary"]:
        messages.append(
            SystemMessage(f"Summary of earlier conversation:\n{state['summary']}")
        )
    for turn in state["messages"]:
        if turn["role"] == "user":
            messages.append(HumanMessage(turn["content"]))
        else:
            messages.append(AIMessage(turn["content"]))
    messages.append(HumanMessage(new_message))
    return messages


@lru_cache(maxsize=1)
def _summarizer() -> ChatOpenAI:
    return ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key)


async def _summarize(existing: str, turns: list[Turn]) -> str:
    convo = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
    prompt = (
        "You maintain a running summary of a conversation. Update the summary so "
        "it incorporates the new exchanges below, staying concise and factual and "
        "preserving any names, preferences, or facts the user shared.\n\n"
        f"Current summary:\n{existing or '(none yet)'}\n\n"
        f"New exchanges:\n{convo}\n\n"
        "Updated summary:"
    )
    response = await _summarizer().ainvoke(prompt)
    return str(response.content)


async def append_turn(
    state: SessionState, user_message: str, assistant_message: str
) -> SessionState:
    """Append the latest exchange, summarizing older turns if the session overflows."""
    messages: list[Turn] = [
        *state["messages"],
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_message},
    ]
    summary = state["summary"]
    if len(messages) > MAX_MESSAGES:
        older = messages[:-KEEP_RECENT]
        summary = await _summarize(summary, older)
        messages = messages[-KEEP_RECENT:]
    return {"summary": summary, "messages": messages}
