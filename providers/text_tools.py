"""Tool calling through text, for servers or models without native tools.

:class:`TextToolsProvider` wraps a provider that is used for plain text only
(normally :class:`providers.openai_chat.OpenAIChatProvider`) and speaks a
:class:`Dialect` on top of it:

* the tools are described in the system prompt, in the dialect's syntax;
* tool calls in the history are written back as the model would have
  written them, and tool results as one ``tool_result(...)`` user message
  per turn, so user and assistant turns strictly alternate (templates such
  as Gemma's and Mistral's reject anything else);
* the reply text is parsed into prose plus :class:`core.types.ToolCall`
  blocks, so the agent loop sees the same types as with native tools.

Parsing reads arguments with :meth:`json.JSONDecoder.raw_decode`, so
arguments may span several lines and may contain the call's closing
delimiter inside strings.  Arguments that are not a JSON object still
produce a call, with ``raw_arguments`` set, so the model is told what was
wrong instead of the call silently disappearing.  Calls get fresh ids.

Dialects (``CALLING_CONVENTION``):

=============  ===============================================================
``ntcode``     ``tool: NAME({...})`` at the start of a line
``xml``        ``<tool_call>{"name": ..., "arguments": {...}}</tool_call>``
               (Hermes / Qwen style)
``json_block`` a fenced ```` ```json ```` block with ``{"tool": ..., "args": {...}}``;
               other fenced JSON is left alone as ordinary code
``gemma``      ``<|tool_call>call:tool:NAME({...})<tool_call|>``, tolerating
               JS-style unquoted keys
=============  ===============================================================
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.types import (
    AssistantTurn,
    Message,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    new_call_id,
)
from providers.base import Provider

_DECODER = json.JSONDecoder()

# (start, end) of a parsed call in the reply text, and the call.
Span = Tuple[int, int, ToolCall]


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _decode_at(text: str, pos: int) -> Optional[Tuple[Any, int]]:
    """Decode one JSON value starting at *pos*; ``(value, end)`` or None."""
    try:
        return _DECODER.raw_decode(text, pos)
    except json.JSONDecodeError:
        return None


def _call(name: str, args: Any, raw: Optional[str] = None) -> ToolCall:
    """A ToolCall; anything but a JSON object becomes ``raw_arguments``."""
    if raw is None and isinstance(args, dict):
        return ToolCall(new_call_id(), name, args)
    if raw is None:
        raw = json.dumps(args, ensure_ascii=False)
    return ToolCall(new_call_id(), name, {}, raw)


def _args_json(call: ToolCall) -> str:
    if call.raw_arguments is not None:
        return call.raw_arguments
    return json.dumps(call.args, ensure_ascii=False)


# ===========================================================================
# Dialects
# ===========================================================================

class Dialect:
    """One text syntax for tool calls."""

    name = ""
    header = ""

    def render_tools(self, tools: Sequence[ToolSpec]) -> str:
        blocks = []
        for spec in tools:
            blocks.append(json.dumps(spec.to_dict(), indent=2, ensure_ascii=False))
            blocks.append("-" * 40)
        return self.header + "\n".join(blocks)

    def render_call(self, call: ToolCall) -> str:
        raise NotImplementedError

    def render_results(self, results: Sequence[ToolResult]) -> str:
        return "\n\n".join(f"tool_result({r.content})" for r in results)

    def find_calls(self, text: str) -> List[Span]:
        raise NotImplementedError

    def parse(self, text: str) -> Tuple[str, List[ToolCall]]:
        """Split a reply into prose (calls removed) and tool calls."""
        spans = self.find_calls(text)
        prose, last = [], 0
        for start, end, _ in spans:
            prose.append(text[last:start])
            last = end
        prose.append(text[last:])
        cleaned = re.sub(r"\n{3,}", "\n\n", "".join(prose)).strip()
        return cleaned, [call for _, _, call in spans]


class NtcodeDialect(Dialect):
    name = "ntcode"
    header = """\
You have access to the following tools. To call a tool, output ONLY a line
in the following format and nothing else on that line:

    tool: TOOL_NAME({"param1": "value1", "param2": "value2"})

Examples:
    tool: read_file({"filename": "README.md"})
    tool: list_files({"path": "."})
    tool: edit_file({"path": "file.txt", "old_str": "", "new_str": "hello"})
    tool: git_status({})

Rules:
- Output ONLY the tool call line — no prose before or after on that line.
- Arguments must be a valid JSON object (keys and string values double-quoted).
- If the tool takes no arguments use an empty object: {}.
- After receiving a tool_result(...) message, continue the task normally.
- If no tool is needed, respond normally.

Available tools:
"""
    _HEAD = re.compile(r"^[ \t]*tool:[ \t]*(\w+)[ \t]*\(", re.MULTILINE)
    _TAIL = re.compile(r"\)[ \t]*$", re.MULTILINE)

    def render_call(self, call: ToolCall) -> str:
        return f"tool: {call.name}({_args_json(call)})"

    def find_calls(self, text: str) -> List[Span]:
        spans: List[Span] = []
        pos = 0
        while (m := self._HEAD.search(text, pos)) is not None:
            name, start = m.group(1), m.start()
            arg = _skip_ws(text, m.end())
            if text.startswith(")", arg):
                spans.append((start, arg + 1, _call(name, {})))
                pos = arg + 1
                continue
            decoded = _decode_at(text, arg)
            if decoded is not None:
                end = _skip_ws(text, decoded[1])
                if text.startswith(")", end):
                    spans.append((start, end + 1, _call(name, decoded[0])))
                    pos = end + 1
                    continue
            tail = self._TAIL.search(text, arg)
            if tail is None:
                pos = m.end()
                continue
            spans.append((start, tail.end(), _call(name, None, text[arg:tail.start()].strip())))
            pos = tail.end()
        return spans


class XmlDialect(Dialect):
    name = "xml"
    header = """\
You have access to the following tools. To call a tool, output ONLY the
following block and nothing else on those lines:

<tool_call>
{"name": "<tool_name>", "arguments": {"param1": "value1", "param2": "value2"}}
</tool_call>

After receiving the tool result you will get a message that starts with
"tool_result(" — continue the task from there.
Do NOT output any prose on the same lines as a tool_call block.
If no tool is needed, respond normally.

Available tools:
"""
    _OPEN, _CLOSE = "<tool_call>", "</tool_call>"
    _NAME = re.compile(r'"name"\s*:\s*"([^"]*)"')

    def render_call(self, call: ToolCall) -> str:
        body = f'{{"name": {json.dumps(call.name)}, "arguments": {_args_json(call)}}}'
        return f"{self._OPEN}\n{body}\n{self._CLOSE}"

    def find_calls(self, text: str) -> List[Span]:
        spans: List[Span] = []
        pos = 0
        while (start := text.find(self._OPEN, pos)) != -1:
            body = _skip_ws(text, start + len(self._OPEN))
            decoded = _decode_at(text, body)
            if decoded is not None and isinstance(decoded[0], dict):
                end = _skip_ws(text, decoded[1])
                if text.startswith(self._CLOSE, end):
                    obj = decoded[0]
                    args = obj.get("arguments", obj.get("args", {}))
                    if isinstance(args, str):  # some models send a JSON string
                        parsed = _decode_at(args, 0)
                        args = parsed[0] if parsed and parsed[1] == len(args) else args
                    raw = args if isinstance(args, str) else None
                    spans.append((start, end + len(self._CLOSE),
                                  _call(str(obj.get("name", "")), args, raw)))
                    pos = end + len(self._CLOSE)
                    continue
            close = text.find(self._CLOSE, body)
            if close == -1:
                break
            raw_body = text[body:close].strip()
            name = self._NAME.search(raw_body)
            spans.append((start, close + len(self._CLOSE),
                          _call(name.group(1) if name else "", None, raw_body)))
            pos = close + len(self._CLOSE)
        return spans


class JsonBlockDialect(Dialect):
    name = "json_block"
    header = """\
You have access to the following tools. To call a tool, output ONLY a fenced
JSON block and nothing else on those lines:

```json
{"tool": "<tool_name>", "args": {"param1": "value1", "param2": "value2"}}
```

After receiving the tool result you will get a message starting with
"tool_result(" — continue the task from there.
Do NOT mix prose and a tool call on the same lines.
If no tool is needed, respond normally.

Available tools:
"""
    _FENCE = re.compile(r"```(?:json)?[ \t]*\n?")

    def render_call(self, call: ToolCall) -> str:
        return f'```json\n{{"tool": {json.dumps(call.name)}, "args": {_args_json(call)}}}\n```'

    def find_calls(self, text: str) -> List[Span]:
        # Only a fenced object with a "tool" key is a call; any other fenced
        # block is ordinary code in the reply and stays in the prose.
        spans: List[Span] = []
        pos = 0
        while (m := self._FENCE.search(text, pos)) is not None:
            decoded = _decode_at(text, _skip_ws(text, m.end()))
            if decoded is not None and isinstance(decoded[0], dict) \
                    and isinstance(decoded[0].get("tool"), str):
                end = _skip_ws(text, decoded[1])
                if text.startswith("```", end):
                    obj = decoded[0]
                    spans.append((m.start(), end + 3, _call(obj["tool"], obj.get("args", {}))))
                    pos = end + 3
                    continue
            close = text.find("```", m.end())
            pos = len(text) if close == -1 else close + 3
        return spans


def _fix_unquoted_keys(s: str) -> str:
    """Quote JS-style bare object keys (``{path: "."}`` -> ``{"path": "."}``)."""
    return re.sub(r'(?<=[{,])\s*(\w+)\s*:', lambda m: ' "' + m.group(1) + '":', s)


class GemmaDialect(Dialect):
    name = "gemma"
    header = """\
You have access to the following tools. To call a tool, output ONLY the
following on its own line and nothing else:

<|tool_call>call:tool:TOOL_NAME({"arg": "value"})<tool_call|>

Rules:
- Replace TOOL_NAME with the exact tool name.
- Replace the JSON object with the actual arguments as strict JSON
  (keys must be double-quoted strings).
- If the tool takes no arguments use an empty object: {}.
- Output ONLY the <|tool_call>...<tool_call|> line — no prose before or after.
- After receiving a tool_result(...) message, continue the task normally.
- If no tool is needed, respond normally without the delimiter tokens.

Available tools:
"""
    _OPEN, _CLOSE = "<|tool_call>", "<tool_call|>"
    _HEAD = re.compile(r"\s*(?:call:(?:tool:)?)?\s*(\w+)\s*\(")
    _TAIL = re.compile(r"\)\s*<tool_call\|>")

    def render_call(self, call: ToolCall) -> str:
        return f"{self._OPEN}call:tool:{call.name}({_args_json(call)}){self._CLOSE}"

    def find_calls(self, text: str) -> List[Span]:
        spans: List[Span] = []
        pos = 0
        while (start := text.find(self._OPEN, pos)) != -1:
            body = start + len(self._OPEN)
            head = self._HEAD.match(text, body)
            if head is None:
                close = text.find(self._CLOSE, body)
                pos = body if close == -1 else close + len(self._CLOSE)
                continue
            name, arg = head.group(1), _skip_ws(text, head.end())

            call: Optional[ToolCall] = None
            close_paren = -1
            if text.startswith(")", arg):
                call, close_paren = _call(name, {}), arg
            else:
                decoded = _decode_at(text, arg)
                if decoded is not None:
                    end = _skip_ws(text, decoded[1])
                    if text.startswith(")", end):
                        call, close_paren = _call(name, decoded[0]), end
            if call is None:
                tail = self._TAIL.search(text, arg)
                if tail is None:
                    break
                raw = text[arg:tail.start()].strip()
                fixed_text = _fix_unquoted_keys(raw).strip()
                fixed = _decode_at(fixed_text, 0)
                if fixed is not None and fixed[1] == len(fixed_text):
                    call = _call(name, fixed[0])
                else:
                    call = _call(name, None, raw)
                close_paren = tail.start()

            after = _skip_ws(text, close_paren + 1)
            if not text.startswith(self._CLOSE, after):
                pos = after
                continue
            spans.append((start, after + len(self._CLOSE), call))
            pos = after + len(self._CLOSE)
        return spans


DIALECTS: Dict[str, Dialect] = {
    d.name: d for d in (NtcodeDialect(), XmlDialect(), JsonBlockDialect(), GemmaDialect())
}


def get_dialect(name: str) -> Dialect:
    try:
        return DIALECTS[name]
    except KeyError:
        raise ValueError(f"unknown tool-call dialect {name!r}; known: {sorted(DIALECTS)}") from None


# ===========================================================================
# Provider wrapper
# ===========================================================================

class TextToolsProvider(Provider):
    """Tool calling in text over a provider used for plain chat only."""

    def __init__(self, inner: Provider, dialect: Dialect) -> None:
        self.inner = inner
        self.dialect = dialect
        self.name = f"{inner.name}+{dialect.name}"
        self.model = inner.model

    def to_text(self, messages: Sequence[Message]) -> List[Message]:
        """The conversation as text-only messages, strictly alternating."""
        out: List[Message] = []
        for msg in messages:
            parts: List[str] = []
            if msg.results:
                parts.append(self.dialect.render_results(msg.results))
            parts.extend(b.text for b in msg.content if isinstance(b, TextBlock) and b.text)
            parts.extend(self.dialect.render_call(c) for c in msg.tool_calls)
            text = "\n\n".join(parts)
            if not text:
                continue
            if out and out[-1].role == msg.role:
                text = out.pop().text + "\n\n" + text
            out.append(Message(msg.role, (TextBlock(text),)))
        return out

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AssistantTurn:
        if tools:
            system = f"{system}\n\n{self.dialect.render_tools(tools)}" if system \
                else self.dialect.render_tools(tools)
        turn = self.inner.complete(system, self.to_text(messages), [])

        prose, calls = self.dialect.parse(turn.message.text)
        stop = turn.stop_reason
        if calls and stop == "end_turn":
            stop = "tool_use"
        return AssistantTurn(Message.assistant(prose, calls), stop, turn.usage)

    def close(self) -> None:
        self.inner.close()

    def __repr__(self) -> str:
        return f"TextToolsProvider({self.inner!r}, dialect={self.dialect.name!r})"
