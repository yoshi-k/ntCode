"""Agent loop with a native-tool-use provider (providers.base.Provider).

A scripted provider stands in for Claude, so these tests check what the loop
sends, stores and publishes without any network access.
"""

from __future__ import annotations

import json
import threading
from typing import Any, List, Sequence
from unittest.mock import patch

import pytest

import utils.llm as llm_module
from core.types import AssistantTurn, Message, ToolCall, ToolSpec
from providers.base import Provider
from providers.errors import ProviderRateLimitError
from utils.agent import run_agent
from utils.connector import Connector
from utils.llm import SessionHeader
from utils.prompt import NATIVE_TOOLS_NOTE, build_system_prompt


def echo_tool(text: str) -> dict:
    """Echo the text back.

    :param text: What to echo.
    """
    return {"echo": text}


def failing_tool() -> dict:
    """Always fails."""
    return {"error": "it broke", "success": False}


class ScriptedProvider(Provider):
    name = "scripted"
    model = "scripted-model"

    def __init__(self, script: List[Any]) -> None:
        self.script = list(script)
        self.calls: List[tuple] = []

    def complete(self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]):
        self.calls.append((system, list(messages), list(tools)))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _turn(text: str = "", calls: Sequence[ToolCall] = (), stop: str = "end_turn") -> AssistantTurn:
    return AssistantTurn(Message.assistant(text, calls), stop_reason=stop)


def _run(provider: ScriptedProvider, sends: List[Any], replies: int) -> List[str]:
    """Run the agent, send each item (text or ("control", cmd, payload)), collect replies."""
    connector = Connector()
    registry = {"echo": echo_tool, "failing": failing_tool}
    with patch.object(llm_module, "llm", provider), \
            patch.dict("tools.registry.TOOL_REGISTRY", registry):
        thread = threading.Thread(target=run_agent, args=(connector,), daemon=True)
        thread.start()
        for item in sends:
            if isinstance(item, tuple):
                connector.send_control(item[1], item[2])
            else:
                connector.send_user(item)
        out = []
        for _ in range(replies):
            msg = connector.receive_assistant_blocking(timeout=5)
            assert msg is not None, f"agent sent only {len(out)} of {replies} replies: {out}"
            out.append(msg["content"])
        connector.shutdown()
        thread.join(timeout=5)
    return out


def test_tool_call_round_trip():
    call = ToolCall("toolu_1", "echo", {"text": "hi"})
    provider = ScriptedProvider([_turn("Echoing.", [call], "tool_use"), _turn("Done: hi")])

    assert _run(provider, ["please echo hi"], 1) == ["Done: hi"]

    system, messages, tools = provider.calls[1]
    assert [m.role for m in messages] == ["user", "assistant", "user"]
    assert messages[1].tool_calls == [call]
    (result,) = messages[2].results
    assert result.call_id == "toolu_1" and not result.is_error
    assert json.loads(result.content) == {"echo": "hi"}
    assert "echo" in [t.name for t in tools]
    assert NATIVE_TOOLS_NOTE in system
    assert "tool: TOOL_NAME(" not in system


def test_parallel_calls_get_one_results_message_in_order():
    calls = [ToolCall("a", "echo", {"text": "1"}), ToolCall("b", "echo", {"text": "2"})]
    provider = ScriptedProvider([_turn(calls=calls, stop="tool_use"), _turn("ok")])
    _run(provider, ["go"], 1)
    results = provider.calls[1][1][2].results
    assert [r.call_id for r in results] == ["a", "b"]


def test_unknown_and_failing_tools_still_get_results():
    calls = [ToolCall("a", "no_such_tool", {}), ToolCall("b", "failing", {})]
    provider = ScriptedProvider([_turn(calls=calls, stop="tool_use"), _turn("sorry")])
    assert _run(provider, ["go"], 1) == ["sorry"]
    results = provider.calls[1][1][2].results
    assert [(r.call_id, r.is_error) for r in results] == [("a", True), ("b", True)]
    assert "Unknown tool" in results[0].content


def test_provider_error_is_published_and_not_stored():
    provider = ScriptedProvider([
        ProviderRateLimitError("slow down", provider="scripted", status=429),
        _turn("second try works"),
    ])
    replies = _run(provider, ["first", "second"], 2)
    assert replies[0].startswith("❌") and "rate limiting" in replies[0]
    assert replies[1] == "second try works"
    # The failed turn left only the user message behind.
    assert [m.text for m in provider.calls[1][1]] == ["first", "second"]


def test_refusal_is_published_and_not_stored():
    provider = ScriptedProvider([_turn(stop="refusal"), _turn("fine")])
    replies = _run(provider, ["bad", "good"], 2)
    assert "declined" in replies[0]
    assert [m.role for m in provider.calls[1][1]] == ["user", "user"]


def test_max_tokens_is_flagged():
    provider = ScriptedProvider([_turn("partial", stop="max_tokens")])
    assert "cut off" in _run(provider, ["go"], 1)[0]


def test_bare_savepoint_does_not_call_the_model():
    """Regression: usage errors in control commands fell through to a model call."""
    provider = ScriptedProvider([_turn("hello")])
    replies = _run(provider, [("control", "savepoint", ""), "hi"], 2)
    assert "Usage" in replies[0]
    assert replies[1] == "hello"
    assert len(provider.calls) == 1


def test_system_with_docs_does_not_repeat_inlined_docs(tmp_path):
    inlined = tmp_path / "a.md"
    inlined.write_text("INLINED DOC BODY", encoding="utf-8")
    extra = tmp_path / "b.md"
    extra.write_text("EXTRA DOC BODY", encoding="utf-8")
    header = SessionHeader("prompt with INLINED DOC BODY", doc_paths=[str(inlined), str(extra)])
    system = header.system_with_docs()
    assert system.count("INLINED DOC BODY") == 1
    assert "### b.md\nEXTRA DOC BODY" in system


@pytest.mark.parametrize("native", [True, False])
def test_prompt_tool_block_depends_on_mode(native):
    prompt = build_system_prompt(native_tools=native)
    assert (NATIVE_TOOLS_NOTE in prompt) is native
    assert ("You have access to the following tools" in prompt) is not native


def test_real_anthropic_provider_through_the_agent_loop():
    """AnthropicProvider + run_agent over a mock HTTP transport, end to end."""
    import anthropic

    from providers.anthropic import AnthropicProvider
    from tests.wire_backends import anthropic_http_module

    http = anthropic_http_module()
    bodies: List[dict] = []
    replies = [
        [{"type": "text", "text": "Echoing."},
         {"type": "tool_use", "id": "toolu_9", "name": "echo", "input": {"text": "hey"}}],
        [{"type": "text", "text": "It said hey."}],
    ]

    def handler(request):
        bodies.append(json.loads(request.content))
        content = replies[len(bodies) - 1]
        return http.Response(200, json={
            "id": f"msg_{len(bodies)}", "type": "message", "role": "assistant",
            "model": "claude-sonnet-4-6", "content": content,
            "stop_reason": "tool_use" if len(bodies) == 1 else "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    client = anthropic.Anthropic(
        api_key="k", http_client=http.Client(transport=http.MockTransport(handler)), max_retries=0,
    )
    provider = AnthropicProvider("claude-sonnet-4-6", client=client)

    connector = Connector()
    with patch.object(llm_module, "llm", provider), \
            patch.dict("tools.registry.TOOL_REGISTRY", {"echo": echo_tool}):
        thread = threading.Thread(target=run_agent, args=(connector,), daemon=True)
        thread.start()
        connector.send_user("echo hey")
        reply = connector.receive_assistant_blocking(timeout=5)
        connector.shutdown()
        thread.join(timeout=5)

    assert reply["content"] == "It said hey."
    second = bodies[1]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][1]["content"][1] == {
        "type": "tool_use", "id": "toolu_9", "name": "echo", "input": {"text": "hey"},
    }
    result = second["messages"][2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_9"
    assert json.loads(result["content"]) == {"echo": "hey"}
    assert second["cache_control"] == {"type": "ephemeral"}
    assert "echo" in [t["name"] for t in second["tools"]]


def test_invalid_arguments_get_an_error_result_without_running_the_tool():
    ran: List[str] = []

    call = ToolCall("a", "echo", {}, raw_arguments='{"text": ')
    provider = ScriptedProvider([_turn(calls=[call], stop="tool_use"), _turn("retrying")])
    with patch("utils.agent.execute_tool_safely", side_effect=lambda *a: ran.append(a[0])):
        assert _run(provider, ["go"], 1) == ["retrying"]
    (result,) = provider.calls[1][1][2].results
    assert result.is_error and "not a valid JSON object" in result.content
    assert ran == []


def test_real_openai_provider_through_the_agent_loop():
    """OpenAIChatProvider + run_agent over a mock HTTP transport, end to end."""
    import openai

    from providers.openai_chat import OpenAIChatProvider
    from tests.wire_backends import sdk_http_module

    http = sdk_http_module("openai")
    bodies: List[dict] = []
    replies = [
        {"content": "", "tool_calls": [{"id": "uQFY90n5", "type": "function",
                                        "function": {"name": "echo", "arguments": '{"text":"hey"}'}}]},
        {"content": "It said hey."},
    ]

    def handler(request):
        bodies.append(json.loads(request.content))
        message = replies[len(bodies) - 1]
        return http.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "gemma-4",
            "choices": [{"index": 0, "message": {"role": "assistant", **message},
                         "finish_reason": "tool_calls" if len(bodies) == 1 else "stop"}],
        })

    client = openai.OpenAI(api_key="k", base_url="http://llama.test/v1",
                           http_client=http.Client(transport=http.MockTransport(handler)), max_retries=0)
    provider = OpenAIChatProvider("gemma-4", client=client)

    connector = Connector()
    with patch.object(llm_module, "llm", provider), \
            patch.dict("tools.registry.TOOL_REGISTRY", {"echo": echo_tool}):
        thread = threading.Thread(target=run_agent, args=(connector,), daemon=True)
        thread.start()
        connector.send_user("echo hey")
        reply = connector.receive_assistant_blocking(timeout=5)
        connector.shutdown()
        thread.join(timeout=5)

    assert reply["content"] == "It said hey."
    first, second = bodies
    assert "echo" in [t["function"]["name"] for t in first["tools"]]
    assert NATIVE_TOOLS_NOTE in first["messages"][0]["content"]
    assert [m["role"] for m in second["messages"]] == ["system", "user", "assistant", "tool"]
    assert second["messages"][2]["tool_calls"][0]["id"] == "uQFY90n5"
    assert second["messages"][3]["tool_call_id"] == "uQFY90n5"
    assert json.loads(second["messages"][3]["content"]) == {"echo": "hey"}
