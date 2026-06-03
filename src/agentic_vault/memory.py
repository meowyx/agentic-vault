"""Per-user long-term memory in Redis.

Distinct from the per-session working memory in session.py: these are durable
facts the agent chooses to remember (the user's name, preferences, decisions)
via the save_memory tool. They are injected into every conversation, so a fact
saved in one chat is recalled in another. Single local user, so a single key.
"""

import json

from redis.asyncio import Redis

from agentic_vault.config import settings

_MEMORY_KEY = "memory:user"  # single local user; multi-user would key by subject
MAX_MEMORIES = 50

_redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def get_memories() -> list[str]:
    raw = await _redis.get(_MEMORY_KEY)
    return json.loads(raw) if raw else []


async def add_memory(fact: str) -> bool:
    """Append a fact if it is new. Returns True if it was newly saved."""
    fact = fact.strip()
    if not fact:
        return False
    memories = await get_memories()
    if fact in memories:
        return False
    memories.append(fact)
    await _redis.set(_MEMORY_KEY, json.dumps(memories[-MAX_MEMORIES:]))
    return True
