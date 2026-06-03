"""Pre/post guards.

Pre (before the model): a length cap and an OpenAI moderation check on the user's
input. Post (after the answer streams): the final answer is validated against a
Pydantic schema and moderated, so a malformed or harmful response fails closed
instead of being saved or kept as the final state.

Moderation here is a harmful-content check, not prompt-injection defense; those
are different problems. (Injection is handled elsewhere by treating tool args and
tool output as untrusted and keeping fixed system-prompt boundaries.)
"""

from functools import lru_cache

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agentic_vault.config import settings

MAX_INPUT_CHARS = 4000
_MODERATION_MODEL = "omni-moderation-latest"

INPUT_REFUSAL = (
    "I can't help with that request. Try rephrasing, or ask about your Rust "
    "notes, a calculation, or the date."
)
OUTPUT_FALLBACK = (
    "I produced a response that did not pass the output safety check, so I am "
    "holding it back. Please try rephrasing your question."
)


class AgentReply(BaseModel):
    """Post-guard schema for the final answer. Fails closed if it does not fit."""

    answer: str = Field(min_length=1, max_length=20000)
    sources: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


async def is_flagged(text: str) -> bool:
    """True if OpenAI moderation flags the text as harmful content.

    Fails open (returns False) if the moderation call itself errors, so a
    moderation outage degrades to "unguarded" rather than taking down chat.
    """
    if not text.strip():
        return False
    try:
        response = await _client().moderations.create(
            model=_MODERATION_MODEL, input=text
        )
        return bool(response.results[0].flagged)
    except Exception:
        return False


def validate_output(answer: str, sources: list[str]) -> AgentReply | None:
    """Return a validated AgentReply, or None if it fails the schema."""
    try:
        return AgentReply(answer=answer, sources=sources)
    except Exception:
        return None
