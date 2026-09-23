"""Tests for providers/anthropic.py beyond the wire-contract fixtures."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import anthropic
import pytest

from core.types import (
    Message,
    OpaqueBlock,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    message_from_dict,
    message_to_dict,
)
from providers.anthropic import AnthropicProvider
from providers.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)
from tests.wire_backends import anthropic_http_module

HTTP = anthropic_http_module()


def _reply(content: List[Dict[str, Any]], stop: str = "end_turn", **usage: int) -> Dict[str, Any]:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6",
        "content": content, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5, **usage},
    }


def _provider(respond: Callable[[Any], Any], captured: List[Any] | None = None) -> AnthropicProvider:
    def handler(request):
        if captured is not None:
            captured.append(request)
        return respond(request)

    client = anthropic.Anthropic(
        api_key="test-key",
        http_client=HTTP.Client(transport=HTTP.MockTransport(handler)),
        max_retries=0,
    )
    return AnthropicProvider("claude-sonnet-4-6", client=client)


def _ok(content, **kw):
    return lambda _req: HTTP.Response(200, json=_reply(content, **kw))


ASK = [Message.user("hi")]


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

def test_request_uses_automatic_and_system_cache_breakpoints():
    req = _provider(_ok([])).build_request("sys", ASK, [])
    assert req["cache_control"] == {"type": "ephemeral"}
    assert req["system"] == [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]


def test_empty_system_and_no_tools_are_omitted():
    req = _provider(_ok([])).build_request("", ASK, [])
    assert "system" not in req and "tools" not in req


def test_tool_results_come_before_text_and_is_error_only_when_true():
    msg = Message("user", (TextBlock("also this"), ToolResult("t1", "ok"), ToolResult("t2", "bad", True)))
    req = _provider(_ok([])).build_request("", [msg], [])
    assert req["messages"][0]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "bad", "is_error": True},
        {"type": "text", "text": "also this"},
    ]


def test_empty_text_and_empty_messages_are_dropped():
    msgs = [Message.user("hi"), Message("assistant", (TextBlock(""),)), Message.user("again")]
    req = _provider(_ok([])).build_request("", msgs, [])
    assert [m["role"] for m in req["messages"]] == ["user", "user"]


def test_empty_tool_result_content_is_omitted():
    req = _provider(_ok([])).build_request("", [Message.tool_results([ToolResult("t1", "")])], [])
    assert req["messages"][0]["content"] == [{"type": "tool_result", "tool_use_id": "t1"}]


def test_opaque_blocks_from_other_providers_are_not_sent():
    msg = Message("assistant", (OpaqueBlock("openai", {"x": 1}), TextBlock("hi")))
    req = _provider(_ok([])).build_request("", [Message.user("q"), msg], [])
    assert req["messages"][1]["content"] == [{"type": "text", "text": "hi"}]


def test_tools_use_input_schema():
    spec = ToolSpec("t", "does t", {"type": "object", "properties": {}})
    req = _provider(_ok([])).build_request("", ASK, [spec])
    assert req["tools"] == [{"name": "t", "description": "does t",
                             "input_schema": {"type": "object", "properties": {}}}]


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

def test_usage_and_stop_reason():
    turn = _provider(_ok([{"type": "text", "text": "hey"}], cache_read_input_tokens=7,
                         cache_creation_input_tokens=3)).complete("", ASK, [])
    assert turn.stop_reason == "end_turn"
    assert (turn.usage.input_tokens, turn.usage.output_tokens) == (10, 5)
    assert (turn.usage.cache_read_tokens, turn.usage.cache_write_tokens) == (7, 3)


def test_thinking_block_round_trips_unchanged():
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    content = [thinking,
               {"type": "tool_use", "id": "toolu_1", "name": "git_status", "input": {}}]
    captured: List[Any] = []
    provider = _provider(_ok(content, stop="tool_use"), captured)

    turn = provider.complete("", ASK, [])
    assert isinstance(turn.message.content[0], OpaqueBlock)
    assert turn.message.tool_calls == [ToolCall("toolu_1", "git_status", {})]

    # Survives a save/load round trip, then goes back out unchanged.
    saved = message_from_dict(message_to_dict(turn.message))
    history = [Message.user("hi"), saved, Message.tool_results([ToolResult("toolu_1", "clean")])]
    provider.complete("", history, [])
    assistant = json.loads(captured[-1].content)["messages"][1]
    assert assistant["content"][0] == thinking
    assert assistant["content"][1]["type"] == "tool_use"


def test_refusal_is_returned_not_raised():
    turn = _provider(_ok([], stop="refusal")).complete("", ASK, [])
    assert turn.stop_reason == "refusal"
    assert turn.message.content == ()


def test_no_beta_header_is_sent():
    captured: List[Any] = []
    _provider(_ok([{"type": "text", "text": "x"}]), captured).complete("s", ASK, [])
    assert "anthropic-beta" not in {k.lower() for k in captured[0].headers}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def _status(code: int, headers: Dict[str, str] | None = None):
    body = {"type": "error", "error": {"type": "x", "message": f"status {code}"}}
    return lambda _req: HTTP.Response(code, json=body, headers=headers or {})


@pytest.mark.parametrize("code, error", [
    (400, ProviderRequestError),
    (401, ProviderAuthError),
    (403, ProviderAuthError),
    (404, ProviderRequestError),
    (413, ProviderRequestError),
    (429, ProviderRateLimitError),
    (500, ProviderServerError),
    (529, ProviderServerError),
])
def test_status_errors_are_translated(code, error):
    with pytest.raises(error) as info:
        _provider(_status(code)).complete("", ASK, [])
    assert info.value.status == code
    assert info.value.provider == "anthropic"
    assert info.value.user_message()


def test_retry_after_is_kept():
    with pytest.raises(ProviderRateLimitError) as info:
        _provider(_status(429, {"retry-after": "12"})).complete("", ASK, [])
    assert info.value.retry_after == 12.0


def test_timeout_and_connection_errors():
    def timeout(req):
        raise HTTP.ReadTimeout("slow", request=req)

    def refused(req):
        raise HTTP.ConnectError("refused", request=req)

    with pytest.raises(ProviderTimeoutError):
        _provider(timeout).complete("", ASK, [])
    with pytest.raises(ProviderConnectionError):
        _provider(refused).complete("", ASK, [])


def test_rate_limiter_is_used():
    calls: List[Any] = []

    class Limiter:
        def wait_for_capacity(self, estimate):
            calls.append(("wait", estimate))
            return 1

        def record_actual(self, reservation, tokens):
            calls.append(("record", reservation, tokens))

    provider = _provider(_ok([{"type": "text", "text": "x"}]))
    provider._rate_limiter = Limiter()
    provider.complete("sys", ASK, [])
    assert calls[0][0] == "wait" and calls[0][1] > provider.max_tokens
    assert calls[1] == ("record", 1, 15)


def test_foreign_tool_ids_are_made_valid_consistently():
    call = ToolCall("functions.read_file:0", "read_file", {})
    msgs = [Message.user("q"), Message.assistant(tool_calls=[call]),
            Message.tool_results([ToolResult("functions.read_file:0", "ok")])]
    req = _provider(_ok([])).build_request("", msgs, [])
    use = req["messages"][1]["content"][0]
    result = req["messages"][2]["content"][0]
    assert use["id"] == result["tool_use_id"] == "functions_read_file_0"
