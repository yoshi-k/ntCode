"""Tests for core/types.py: the provider-neutral conversation types."""

import copy
import json
from pathlib import Path

import pytest

from core.types import (
    Message,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    message_from_dict,
    message_to_dict,
    new_call_id,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "wire"


def test_user_and_assistant_constructors():
    assert Message.user("hi").content == (TextBlock("hi"),)
    call = ToolCall("c1", "read_file", {"filename": "a.py"})
    msg = Message.assistant("Reading.", [call])
    assert msg.text == "Reading."
    assert msg.tool_calls == [call]
    assert Message.assistant(tool_calls=[call]).content == (call,)


def test_content_is_stored_as_tuple():
    msg = Message("user", [TextBlock("a")])
    assert isinstance(msg.content, tuple)


def test_tool_results_message():
    results = [ToolResult("c1", "ok"), ToolResult("c2", "boom", is_error=True)]
    msg = Message.tool_results(results)
    assert msg.role == "user"
    assert msg.results == results
    assert msg.text == ""


@pytest.mark.parametrize("role, block", [
    ("user", ToolCall("c1", "read_file", {})),
    ("assistant", ToolResult("c1", "ok")),
])
def test_blocks_must_be_in_the_right_role(role, block):
    with pytest.raises(ValueError):
        Message(role, (block,))


def test_rejects_unknown_role_and_block():
    with pytest.raises(ValueError):
        Message("system", (TextBlock("x"),))
    with pytest.raises(TypeError):
        Message("user", ({"type": "text", "text": "x"},))


def test_messages_are_immutable():
    msg = Message.user("hi")
    with pytest.raises(AttributeError):
        msg.role = "assistant"


def test_new_call_id_is_unique():
    ids = {new_call_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(i.startswith("call_") for i in ids)


def test_dict_round_trip():
    messages = [
        Message.user("What does README.md say?"),
        Message.assistant("Reading.", [ToolCall("c1", "read_file", {"filename": "README.md"})]),
        Message.tool_results([ToolResult("c1", "# ntCode"), ToolResult("c2", "no", is_error=True)]),
    ]
    data = json.loads(json.dumps([message_to_dict(m) for m in messages]))
    assert [message_from_dict(d) for d in data] == messages


def test_is_error_only_serialised_when_true():
    assert "is_error" not in message_to_dict(Message.tool_results([ToolResult("c", "ok")]))["content"][0]


def test_old_string_content_format_is_accepted():
    assert message_from_dict({"role": "assistant", "content": "hello"}) == Message.assistant("hello")


def test_unknown_block_type_rejected():
    with pytest.raises(ValueError):
        message_from_dict({"role": "user", "content": [{"type": "image"}]})


def test_every_fixture_conversation_parses():
    """The fixture message format and core.types must stay the same format."""
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        for data in fixture.get("messages", []):
            assert message_to_dict(message_from_dict(data))["role"] == data["role"], path.name


def test_tool_spec_to_dict():
    spec = ToolSpec("t", "does t", {"type": "object", "properties": {}})
    assert spec.to_dict() == {"name": "t", "description": "does t",
                              "parameters": {"type": "object", "properties": {}}}


def test_deepcopy_keeps_messages_independent():
    call = ToolCall("c1", "edit_file", {"path": "a"})
    msgs = [Message.assistant(tool_calls=[call])]
    copied = copy.deepcopy(msgs)
    copied[0].tool_calls[0].args["path"] = "b"
    assert call.args["path"] == "a"
