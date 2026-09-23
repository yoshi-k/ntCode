"""Tests for ConversationManager (utils/llm.py) with typed messages."""

import json

import pytest

from core.types import Message, TextBlock, ToolCall, ToolResult
from utils.llm import ConversationManager, SessionHeader


@pytest.fixture
def mgr():
    return ConversationManager(SessionHeader("system prompt", doc_paths=[]))


def _call(i):
    return Message.assistant(tool_calls=[ToolCall(f"c{i}", "git_status", {})])


def _result(i):
    return Message.tool_results([ToolResult(f"c{i}", "clean")])


def test_add_message_requires_message(mgr):
    with pytest.raises(TypeError):
        mgr.add_message({"role": "user", "content": "x"})


def test_messages_returns_copy(mgr):
    mgr.add_user("a")
    mgr.messages().append(Message.user("b"))
    assert mgr.task_message_count == 1


def test_prune_plain_text_keeps_last_messages(mgr):
    for i in range(10):
        mgr.add_user(f"u{i}")
        mgr.add_assistant(f"a{i}")
    mgr.prune_task_messages(4)
    assert [m.text for m in mgr.messages()] == ["u8", "a8", "u9", "a9"]


def test_prune_never_starts_with_assistant(mgr):
    for i in range(5):
        mgr.add_user(f"u{i}")
        mgr.add_assistant(f"a{i}")
    mgr.prune_task_messages(3)          # plain cut would start at a3
    msgs = mgr.messages()
    assert msgs[0].role == "user"
    assert [m.text for m in msgs] == ["u4", "a4"]


def test_prune_never_orphans_a_tool_result(mgr):
    mgr.add_user("task one")
    mgr.add_message(_call(1))
    mgr.add_message(_result(1))
    mgr.add_message(_call(2))
    mgr.add_message(_result(2))
    mgr.add_assistant("done one")
    mgr.add_user("task two")
    mgr.add_message(_call(3))
    mgr.add_message(_result(3))
    mgr.add_assistant("done two")
    mgr.prune_task_messages(5)          # plain cut would start at _result(2)
    msgs = mgr.messages()
    assert msgs[0].text == "task two"
    call_ids = {c.id for m in msgs for c in m.tool_calls}
    assert all(r.call_id in call_ids for m in msgs for r in m.results)


def test_prune_moves_back_when_no_clean_start_in_window(mgr):
    mgr.add_user("task")
    for i in range(6):
        mgr.add_message(_call(i))
        mgr.add_message(_result(i))
    mgr.prune_task_messages(4)          # window holds only calls and results
    msgs = mgr.messages()
    assert msgs[0].text == "task"
    assert len(msgs) == 13


def test_prune_noop_when_short(mgr):
    mgr.add_user("a")
    mgr.prune_task_messages(5)
    assert mgr.task_message_count == 1


def test_save_and_restore_are_lossless(mgr):
    mgr.add_user("task")
    mgr.add_message(Message.assistant("Reading.", [ToolCall("c1", "read_file", {"filename": "a.py"})]))
    mgr.add_message(Message.tool_results([ToolResult("c1", "boom", is_error=True)]))
    flat = json.loads(json.dumps(mgr.as_flat_conversation()))

    other = ConversationManager(SessionHeader("s", doc_paths=[]))
    other.restore_from_flat(flat)
    assert other.messages() == mgr.messages()


def test_restore_reads_old_save_format(mgr):
    mgr.restore_from_flat([
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ])
    assert mgr.messages() == [Message.user("hello"), Message.assistant("hi")]


def test_save_point_is_independent_copy(mgr):
    mgr.add_message(Message.assistant(tool_calls=[ToolCall("c1", "edit_file", {"path": "a"})]))
    mgr.save_point("p")
    # Blocks are frozen, but args is a plain dict and can still be mutated.
    mgr.messages()[0].tool_calls[0].args["path"] = "changed"
    mgr.add_user("more")
    mgr.restore("p")
    assert mgr.task_message_count == 1
    assert mgr.messages()[0].tool_calls[0].args == {"path": "a"}


def test_start_task_resets(mgr):
    mgr.add_user("old")
    mgr.start_task("new")
    assert mgr.messages() == [Message("user", (TextBlock("new"),))]


def test_save_point_overwrite_names_and_delete(mgr):
    mgr.add_user("one")
    mgr.save_point("b")
    mgr.save_point("a")
    mgr.add_user("two")
    mgr.save_point("a")                      # overwrite with the newer state
    assert mgr.save_point_names == ["a", "b"]
    mgr.restore("a")
    assert mgr.task_message_count == 2
    mgr.delete_save_point("a")
    assert mgr.save_point_names == ["b"]
    with pytest.raises(KeyError):
        mgr.restore("a")


@pytest.mark.parametrize("call", [
    lambda m: m.save_point(""),
    lambda m: m.restore("nonexistent"),
    lambda m: m.delete_save_point("nonexistent"),
])
def test_save_point_errors(mgr, call):
    with pytest.raises((ValueError, KeyError)):
        call(mgr)


def test_save_points_survive_prune_and_start_task(mgr):
    for i in range(6):
        mgr.add_user(f"u{i}")
        mgr.add_assistant(f"a{i}")
    mgr.save_point("full")
    mgr.prune_task_messages(2)
    mgr.start_task("new")
    mgr.restore("full")
    assert mgr.task_message_count == 12


def test_missing_doc_files_are_skipped(tmp_path):
    present = tmp_path / "present.md"
    present.write_text("PRESENT", encoding="utf-8")
    header = SessionHeader("sys", doc_paths=[str(tmp_path / "missing.md"), str(present)])
    assert header.system_with_docs() == "sys\n\n### present.md\nPRESENT"
