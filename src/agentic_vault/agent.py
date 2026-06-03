"""Stage 2: the LangGraph agent.

A decide/tools loop over three tools: the Rust-notes retriever, a calculator,
and current-datetime. The model decides each turn whether to call a tool or
answer. Built on an explicit StateGraph (not create_react_agent) so the
decide -> tools -> decide cycle is visible and debuggable.
"""

import ast
import datetime as dt
import operator
from collections.abc import AsyncIterator
from functools import lru_cache

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agentic_vault import memory
from agentic_vault.config import settings
from agentic_vault.rag import _langfuse_handler, retrieve

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. "
    "For questions about Rust, call search_rust_notes and cite source filenames "
    "inline like [filename.md]; if the notes do not cover it, say so plainly. "
    "For arithmetic, call calculator. For the current date or time, call "
    "current_datetime. When the user shares a durable fact about themselves "
    "(their name, preferences, goals, or a decision), call save_memory to keep it "
    "for future conversations; never save trivia or one-off questions. "
    "If a question needs none of these, just answer directly."
)


@tool
async def search_rust_notes(query: str) -> str:
    """Search the user's Rust learning notes for relevant context. Use for any
    question about Rust (ownership, borrowing, traits, syntax, etc.). Returns
    note excerpts with their [filename.md] source headers."""
    return await retrieve(query)


# Arithmetic-only AST walker: numbers and math operators only, no names, no calls.
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _compute(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_compute(node.left), _compute(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_compute(node.operand))
    raise ValueError("unsupported expression")


@tool
def calculator(expression: str) -> str:
    """Compute a basic arithmetic expression (e.g. for '15% of 240' pass
    '0.15 * 240'). Supports + - * / // % ** and parentheses."""
    # mode="eval" is Python's parser flag for "a single expression". It only
    # builds a parse tree, it does not run code; _compute then walks that tree.
    try:
        return str(_compute(ast.parse(expression, mode="eval").body))
    except Exception:
        return f"Could not compute: {expression!r}"


@tool
def current_datetime() -> str:
    """Return the current local date and time. Use when asked the current date,
    time, or day of week."""
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@tool
async def save_memory(fact: str) -> str:
    """Remember a durable fact about the user for future conversations: their
    name, preferences, goals, or decisions. Call this only when the user shares
    something worth keeping long-term, never for trivia or one-off questions."""
    saved = await memory.add_memory(fact)
    return "Saved." if saved else "Already known."


TOOLS = [search_rust_notes, calculator, current_datetime, save_memory]


@lru_cache(maxsize=1)
def _agent():
    llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key).bind_tools(
        TOOLS
    )

    async def decide(state: MessagesState) -> dict:
        response = await llm.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("decide", decide)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "decide")
    builder.add_conditional_edges("decide", tools_condition)
    builder.add_edge("tools", "decide")
    return builder.compile()


async def stream_agent(messages: list[BaseMessage]) -> AsyncIterator[dict]:
    """Yield typed events from the agent run, for the SSE stream:

      {"type": "token", "text": ...}                     a chunk of the answer
      {"type": "tool",  "name", "input", "output"}       a finished tool call

    astream_events surfaces tool calls alongside the streamed tokens. Only
    assistant content chunks become tokens; the silent tool-deciding step has
    empty content and is skipped.
    """
    tool_inputs: dict[str, object] = {}
    async for event in _agent().astream_events(
        {"messages": messages},
        version="v2",
        config={"callbacks": [_langfuse_handler()]},
    ):
        kind = event["event"]
        if kind == "on_tool_start":
            tool_inputs[event["run_id"]] = event["data"].get("input")
        elif kind == "on_tool_end":
            output = event["data"].get("output")
            content = getattr(output, "content", output)
            yield {
                "type": "tool",
                "name": event.get("name", ""),
                "input": tool_inputs.pop(event["run_id"], None),
                "output": "" if content is None else str(content),
            }
        elif kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            text = getattr(chunk, "content", "") if chunk is not None else ""
            if text:
                yield {"type": "token", "text": text}
