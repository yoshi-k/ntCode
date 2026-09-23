"""Tests for providers/text_tools.py: text dialects and TextToolsProvider."""

from __future__ import annotations

from typing import List, Sequence

import pytest

from core.types import AssistantTurn, Message, TextBlock, ToolCall, ToolResult, ToolSpec
from providers.base import Provider
from providers.text_tools import DIALECTS, TextToolsProvider, get_dialect


def _parsed(dialect: str, text: str):
    prose, calls = get_dialect(dialect).parse(text)
    return prose, [(c.name, c.args, c.raw_arguments) for c in calls]


@pytest.mark.parametrize("dialect, text, calls", [
    ("ntcode", 'tool: read_file({"filename": "a"})', [("read_file", {"filename": "a"}, None)]),
    ("ntcode", 'tool: read_file({\n  "filename": "a"\n})', [("read_file", {"filename": "a"}, None)]),
    ("ntcode", "tool: git_status()", [("git_status", {}, None)]),
    ("ntcode", "tool: read_file({bad json})", [("read_file", {}, "{bad json}")]),
    ("ntcode", "the tool: x( syntax is described above", []),
    ("xml", '<tool_call>\n{"name": "read_file", "arguments": {"filename": "a"}}\n</tool_call>',
     [("read_file", {"filename": "a"}, None)]),
    ("xml", '<tool_call>{"name": "read_file", "arguments": "{\\"filename\\": \\"a\\"}"}</tool_call>',
     [("read_file", {"filename": "a"}, None)]),
    ("xml", '<tool_call>{"name": "read_file", "arguments": {bad}}</tool_call>',
     [("read_file", {}, '{"name": "read_file", "arguments": {bad}}')]),
    ("xml", "<tool_call>{unterminated", []),
    ("json_block", '```json\n{"tool": "read_file", "args": {"filename": "a"}}\n```',
     [("read_file", {"filename": "a"}, None)]),
    ("json_block", '```python\nprint(1)\n```', []),
    ("json_block", '```json\n{"not_a_call": 1}\n```', []),
    ("gemma", '<|tool_call>call:tool:read_file({"filename": "x<tool_call|>y"})<tool_call|>',
     [("read_file", {"filename": "x<tool_call|>y"}, None)]),
    ("gemma", '<|tool_call>call:tool:list_files({path: "."})<tool_call|>', [("list_files", {"path": "."}, None)]),
    ("gemma", '<|tool_call>call:list_files({"path": "."})<tool_call|>', [("list_files", {"path": "."}, None)]),
    ("gemma", "<|tool_call>call:tool:read_file({bad!!})<tool_call|>", [("read_file", {}, "{bad!!}")]),
])
def test_parse(dialect, text, calls):
    assert _parsed(dialect, text)[1] == calls


def test_ordinary_json_code_stays_in_the_prose():
    text = 'Example:\n```json\n{"a": 1}\n```\nNow:\n```json\n{"tool": "git_status", "args": {}}\n```'
    prose, calls = _parsed("json_block", text)
    assert calls == [("git_status", {}, None)]
    assert prose == 'Example:\n```json\n{"a": 1}\n```\nNow:'


def test_prose_around_calls_is_kept_and_calls_removed():
    prose, _ = _parsed("gemma", "Checking.\n<|tool_call>call:tool:git_status({})<tool_call|>\nThen more.")
    assert prose == "Checking.\n\nThen more."


def test_parsed_calls_get_unique_ids():
    _, calls = get_dialect("ntcode").parse("tool: git_status({})\ntool: git_status({})")
    assert len({c.id for c in calls}) == 2


@pytest.mark.parametrize("name", sorted(DIALECTS))
def test_rendered_calls_parse_back(name):
    dialect = DIALECTS[name]
    call = ToolCall("id", "edit_file", {"path": "a.py", "new_str": "line1\nline2 ) }"})
    (parsed,) = dialect.parse(dialect.render_call(call))[1]
    assert (parsed.name, parsed.args) == (call.name, call.args)


@pytest.mark.parametrize("name", sorted(DIALECTS))
def test_render_tools_contains_header_and_specs(name):
    spec = ToolSpec("read_file", "Read a file.", {"type": "object", "properties": {}})
    block = DIALECTS[name].render_tools([spec])
    assert block.startswith(DIALECTS[name].header)
    assert '"name": "read_file"' in block


def test_unknown_dialect():
    with pytest.raises(ValueError):
        get_dialect("klingon")


# ---------------------------------------------------------------------------
# TextToolsProvider
# ---------------------------------------------------------------------------

class Recorder(Provider):
    name = "rec"
    model = "m"

    def __init__(self, replies: List[str]) -> None:
        self.replies = list(replies)
        self.calls: List[tuple] = []

    def complete(self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]):
        self.calls.append((system, list(messages), list(tools)))
        return AssistantTurn(Message.assistant(self.replies.pop(0)), "end_turn")


SPEC = ToolSpec("git_status", "Show git status.", {"type": "object", "properties": {}})


def test_tools_go_into_the_system_prompt_not_the_request():
    inner = Recorder(["hi"])
    TextToolsProvider(inner, get_dialect("gemma")).complete("You are ntCode.", [Message.user("q")], [SPEC])
    system, _, tools = inner.calls[0]
    assert tools == []
    assert system.startswith("You are ntCode.\n\n") and "<|tool_call>" in system and "git_status" in system


def test_no_tools_leaves_the_system_prompt_alone():
    inner = Recorder(["hi"])
    TextToolsProvider(inner, get_dialect("gemma")).complete("sys", [Message.user("q")], [])
    assert inner.calls[0][0] == "sys"


def test_reply_is_split_into_prose_and_calls():
    inner = Recorder(["On it.\n<|tool_call>call:tool:git_status({})<tool_call|>"])
    turn = TextToolsProvider(inner, get_dialect("gemma")).complete("", [Message.user("q")], [SPEC])
    assert turn.message.text == "On it."
    assert [c.name for c in turn.message.tool_calls] == ["git_status"]
    assert turn.stop_reason == "tool_use"


def test_history_is_rendered_as_alternating_text():
    history = [
        Message.user("status and readme?"),
        Message.assistant("Both.", [ToolCall("a", "git_status", {}), ToolCall("b", "read_file", {"filename": "R"})]),
        Message.tool_results([ToolResult("a", "clean"), ToolResult("b", "# R", True)]),
        Message.user("and then?"),
    ]
    text = TextToolsProvider(Recorder([]), get_dialect("ntcode")).to_text(history)
    assert [m.role for m in text] == ["user", "assistant", "user"]
    assert all(len(m.content) == 1 and isinstance(m.content[0], TextBlock) for m in text)
    assert text[1].text == 'Both.\n\ntool: git_status({})\n\ntool: read_file({"filename": "R"})'
    assert text[2].text == "tool_result(clean)\n\ntool_result(# R)\n\nand then?"
