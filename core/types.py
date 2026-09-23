"""Provider-neutral conversation types for ntCode.

Everything above the provider adapters works with these types.  Wire formats
(Anthropic ``tool_use`` blocks, OpenAI ``tool_calls``, text dialects such as
``<tool_call>`` or ``tool: NAME({...})``) are converted to and from them at
the edge, and never seen by the agent loop or the conversation history.

A conversation is a list of :class:`Message`.  Each message has a role
(``"user"`` or ``"assistant"``) and a tuple of content blocks:

* :class:`TextBlock` — plain text, in either role.
* :class:`ToolCall` — a tool invocation; assistant messages only.
* :class:`ToolResult` — the outcome of a call, referencing its id; user
  messages only, in the message right after the calls, in call order.
* :class:`OpaqueBlock` — provider data that must be sent back unchanged but
  is not interpreted here, such as Anthropic ``thinking`` blocks; assistant
  messages only.  Only the provider that produced it re-sends it; others
  drop it.

The dict form produced by :func:`message_to_dict` is the same one the
wire-contract fixtures use (tests/fixtures/wire/README.md), and is what
conversations are saved as.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, Union

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation.

    ``raw_arguments`` is set only when the model's arguments could not be
    parsed as a JSON object; it then holds the text as received and ``args``
    is empty.  Such a call must be answered with an error result, not run.
    """

    id: str
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    raw_arguments: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class OpaqueBlock:
    provider: str
    data: Dict[str, Any]


Block = Union[TextBlock, ToolCall, ToolResult, OpaqueBlock]


def new_call_id() -> str:
    """Return a fresh id for a tool call that arrived without one (text mode)."""
    return "call_" + uuid.uuid4().hex[:24]


@dataclass(frozen=True)
class Message:
    role: Role
    content: Tuple[Block, ...]

    def __post_init__(self) -> None:
        if self.role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {self.role!r}")
        # Accept any iterable of blocks, but store an immutable tuple.
        object.__setattr__(self, "content", tuple(self.content))
        for block in self.content:
            if isinstance(block, ToolCall) and self.role != "assistant":
                raise ValueError("ToolCall blocks belong in assistant messages")
            if isinstance(block, ToolResult) and self.role != "user":
                raise ValueError("ToolResult blocks belong in user messages")
            if isinstance(block, OpaqueBlock) and self.role != "assistant":
                raise ValueError("OpaqueBlock blocks belong in assistant messages")
            if not isinstance(block, (TextBlock, ToolCall, ToolResult, OpaqueBlock)):
                raise TypeError(f"not a content block: {block!r}")

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls("user", (TextBlock(text),))

    @classmethod
    def assistant(cls, text: str = "", tool_calls: Iterable[ToolCall] = ()) -> "Message":
        blocks: List[Block] = [TextBlock(text)] if text else []
        blocks.extend(tool_calls)
        return cls("assistant", tuple(blocks))

    @classmethod
    def tool_results(cls, results: Iterable[ToolResult]) -> "Message":
        return cls("user", tuple(results))

    @property
    def text(self) -> str:
        """All text blocks joined with newlines."""
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> List[ToolCall]:
        return [b for b in self.content if isinstance(b, ToolCall)]

    @property
    def results(self) -> List[ToolResult]:
        return [b for b in self.content if isinstance(b, ToolResult)]


@dataclass(frozen=True)
class ToolSpec:
    """A tool as offered to the model: name, description, JSON-Schema parameters."""

    name: str
    description: str
    parameters: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class AssistantTurn:
    """One model reply as returned by a provider adapter.

    ``stop_reason`` uses one vocabulary for every provider: ``end_turn``,
    ``tool_use``, ``max_tokens``, ``refusal``, ``stop_sequence``; adapters
    translate their API's values (and pass through any they cannot map).
    """

    message: Message
    stop_reason: str = ""
    usage: Usage = field(default_factory=Usage)


# ---------------------------------------------------------------------------
# Dict form (fixtures, saved conversations)
# ---------------------------------------------------------------------------

def block_to_dict(block: Block) -> Dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolCall):
        out = {"type": "tool_call", "id": block.id, "name": block.name, "args": block.args}
        if block.raw_arguments is not None:
            out["raw_arguments"] = block.raw_arguments
        return out
    if isinstance(block, OpaqueBlock):
        return {"type": "opaque", "provider": block.provider, "data": block.data}
    out: Dict[str, Any] = {"type": "tool_result", "call_id": block.call_id, "content": block.content}
    if block.is_error:
        out["is_error"] = True
    return out


def block_from_dict(data: Dict[str, Any]) -> Block:
    kind = data.get("type")
    if kind == "text":
        return TextBlock(data["text"])
    if kind == "tool_call":
        return ToolCall(
            data["id"], data["name"], dict(data.get("args") or {}), data.get("raw_arguments")
        )
    if kind == "tool_result":
        return ToolResult(data["call_id"], data["content"], bool(data.get("is_error", False)))
    if kind == "opaque":
        return OpaqueBlock(data["provider"], dict(data["data"]))
    raise ValueError(f"unknown content block type: {kind!r}")


def message_to_dict(message: Message) -> Dict[str, Any]:
    return {"role": message.role, "content": [block_to_dict(b) for b in message.content]}


def message_from_dict(data: Dict[str, Any]) -> Message:
    """Build a Message from its dict form.

    A plain-string ``content`` (the pre-typed save format) is accepted and
    read as a single text block.
    """
    content = data.get("content", "")
    if isinstance(content, str):
        return Message(data["role"], (TextBlock(content),))
    return Message(data["role"], tuple(block_from_dict(b) for b in content))
