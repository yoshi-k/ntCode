"""Tests for providers/openai_chat.py beyond the wire-contract fixtures."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import openai
import pytest

from core.types import Message, OpaqueBlock, TextBlock, ToolCall, ToolResult, ToolSpec
from providers.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)
from providers.openai_chat import OpenAIChatProvider
from tests.wire_backends import sdk_http_module

HTTP = sdk_http_module("openai")
ASK = [Message.user("hi")]


def _reply(message: Dict[str, Any], finish: str = "stop", usage: Dict[str, Any] | None = None):
    body: Dict[str, Any] = {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": finish,
                     "message": {"role": "assistant", **message}}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _provider(respond: Callable[[Any], Any], captured: List[Any] | None = None, **kw) -> OpenAIChatProvider:
    def handler(request):
        if captured is not None:
            captured.append(json.loads(request.content))
        return respond(request)

    client = openai.OpenAI(
        api_key="k", base_url="http://wire.test/v1",
        http_client=HTTP.Client(transport=HTTP.MockTransport(handler)), max_retries=0,
    )
    return OpenAIChatProvider("m", client=client, **kw)


def _ok(message, **kw):
    return lambda _req: HTTP.Response(200, json=_reply(message, **kw))


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

def test_max_tokens_and_temperature_only_when_set():
    req = _provider(_ok({"content": "x"})).build_request("", ASK, [])
    assert "max_tokens" not in req and "temperature" not in req
    req = _provider(_ok({"content": "x"}), max_tokens=100, temperature=0.2).build_request("", ASK, [])
    assert req["max_tokens"] == 100 and req["temperature"] == 0.2


def test_results_become_tool_messages_before_user_text():
    msg = Message("user", (TextBlock("and also"), ToolResult("a", "1"), ToolResult("b", "2", True)))
    req = _provider(_ok({})).build_request("", [msg], [])
    assert req["messages"] == [
        {"role": "tool", "tool_call_id": "a", "content": "1"},
        {"role": "tool", "tool_call_id": "b", "content": "2"},
        {"role": "user", "content": "and also"},
    ]


def test_empty_assistant_and_foreign_opaque_blocks_are_dropped():
    msgs = [Message.user("q"),
            Message("assistant", (OpaqueBlock("anthropic", {"type": "thinking"}),)),
            Message.user("again")]
    req = _provider(_ok({})).build_request("", msgs, [])
    assert [m["role"] for m in req["messages"]] == ["user", "user"]


def test_invalid_arguments_are_sent_back_verbatim():
    call = ToolCall("c1", "echo", {}, raw_arguments='{"text": ')
    req = _provider(_ok({})).build_request("", [Message.user("q"), Message.assistant(tool_calls=[call])], [])
    assert req["messages"][1]["tool_calls"][0]["function"]["arguments"] == '{"text": '


def test_tools_are_function_definitions():
    spec = ToolSpec("t", "does t", {"type": "object", "properties": {}})
    req = _provider(_ok({})).build_request("", ASK, [spec])
    assert req["tools"] == [{"type": "function", "function": {
        "name": "t", "description": "does t", "parameters": {"type": "object", "properties": {}}}}]
    assert "tool_choice" not in req


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("finish, stop", [
    ("stop", "end_turn"), ("tool_calls", "tool_use"), ("length", "max_tokens"),
    ("content_filter", "refusal"), ("something_new", "something_new"),
])
def test_finish_reason_mapping(finish, stop):
    assert _provider(_ok({"content": "x"}, finish=finish)).complete("", ASK, []).stop_reason == stop


def test_usage_including_cached_tokens():
    usage = {"prompt_tokens": 50, "completion_tokens": 7, "total_tokens": 57,
             "prompt_tokens_details": {"cached_tokens": 40}}
    turn = _provider(_ok({"content": "x"}, usage=usage)).complete("", ASK, [])
    assert (turn.usage.input_tokens, turn.usage.output_tokens, turn.usage.cache_read_tokens) == (50, 7, 40)


def test_missing_usage_is_zero():
    assert _provider(_ok({"content": "x"})).complete("", ASK, []).usage.input_tokens == 0


def _call(id_, name, arguments):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": arguments}}


def test_invalid_or_non_object_arguments_keep_the_raw_text():
    calls = [_call("a", "echo", '{"text": "unterminated'), _call("b", "echo", '["list"]'),
             _call("c", "echo", "")]
    turn = _provider(_ok({"content": None, "tool_calls": calls}, finish="tool_calls")).complete("", ASK, [])
    a, b, c = turn.message.tool_calls
    assert (a.args, a.raw_arguments) == ({}, '{"text": "unterminated')
    assert (b.args, b.raw_arguments) == ({}, '["list"]')
    assert (c.args, c.raw_arguments) == ({}, None)


def test_missing_call_id_gets_one():
    calls = [_call("", "echo", "{}")]
    turn = _provider(_ok({"content": None, "tool_calls": calls})).complete("", ASK, [])
    assert turn.message.tool_calls[0].id.startswith("call_")


def test_reasoning_content_is_not_mixed_into_text():
    turn = _provider(_ok({"content": "answer", "reasoning_content": "thoughts"})).complete("", ASK, [])
    assert turn.message.text == "answer"


def test_empty_content_gives_no_text_block():
    turn = _provider(_ok({"content": ""})).complete("", ASK, [])
    assert turn.message.content == ()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def _status(code: int, headers: Dict[str, str] | None = None):
    body = {"error": {"message": f"status {code}", "type": "x"}}
    return lambda _req: HTTP.Response(code, json=body, headers=headers or {})


@pytest.mark.parametrize("code, error", [
    (400, ProviderRequestError), (401, ProviderAuthError), (403, ProviderAuthError),
    (404, ProviderRequestError), (422, ProviderRequestError), (429, ProviderRateLimitError),
    (500, ProviderServerError), (503, ProviderServerError),
])
def test_status_errors_are_translated(code, error):
    with pytest.raises(error) as info:
        _provider(_status(code)).complete("", ASK, [])
    assert info.value.status == code and info.value.provider == "openai"


def test_retry_after_is_kept():
    with pytest.raises(ProviderRateLimitError) as info:
        _provider(_status(429, {"retry-after": "3"})).complete("", ASK, [])
    assert info.value.retry_after == 3.0


def test_timeout_and_connection_errors():
    def timeout(req):
        raise HTTP.ReadTimeout("slow", request=req)

    def refused(req):
        raise HTTP.ConnectError("refused", request=req)

    with pytest.raises(ProviderTimeoutError):
        _provider(timeout).complete("", ASK, [])
    with pytest.raises(ProviderConnectionError):
        _provider(refused).complete("", ASK, [])


def test_constructs_without_api_key():
    provider = OpenAIChatProvider("m", base_url="http://localhost:8080/v1")
    assert provider.model == "m"
