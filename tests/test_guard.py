"""Unit tests for the output post-guard schema."""

from agentic_vault import guard


def test_valid_output_passes():
    reply = guard.validate_output("a real answer", ["rust 8 - ownership.md"])
    assert reply is not None
    assert reply.answer == "a real answer"
    assert reply.sources == ["rust 8 - ownership.md"]


def test_empty_answer_fails_closed():
    assert guard.validate_output("", []) is None
