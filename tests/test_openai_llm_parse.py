"""Unit tests for OpenAILLM._parse().

Covers the two response shapes the OpenAI Chat Completions API can return:

1. Plain text reply  -- choices[0].message.content is a non-empty string.
2. Native tool-call  -- choices[0].message.content is null and
   choices[0].message.tool_calls carries structured function-call data.

All tests are offline (no HTTP calls, no API key required).
OpenAILLM is instantiated only to access _parse() as a static method;
no __init__ network setup is needed for that.
"""

from __future__ import annotations

import json
import os
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from utils.openai_llm import OpenAILLM


def _raw(content, tool_calls=None, usage=None):
    """Build a minimal /chat/completions response dict."""
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _tool_call(name: str, args: dict) -> dict:
    """Build a single tool_calls entry in the OpenAI wire format."""
    return {
        "id": "call_abc",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args),
        },
    }


# ===========================================================================
# Plain text responses
# ===========================================================================

class TestParseTextReply:
    """_parse() with a normal plain-text content response."""

    def test_returns_content_string(self):
        text, _, _ = OpenAILLM._parse(_raw("Hello world!"))
        assert text == "Hello world!"

    def test_token_counts_extracted(self):
        raw = _raw("Hi", usage={"prompt_tokens": 42, "completion_tokens": 7})
        _, inp, out = OpenAILLM._parse(raw)
        assert inp == 42
        assert out == 7

    def test_missing_usage_defaults_to_zero(self):
        raw = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        _, inp, out = OpenAILLM._parse(raw)
        assert inp == 0
        assert out == 0

    def test_null_usage_defaults_to_zero(self):
        raw = _raw("ok")
        raw["usage"] = None
        _, inp, out = OpenAILLM._parse(raw)
        assert inp == 0
        assert out == 0


# ===========================================================================
# Native tool_calls responses (content == null)
# ===========================================================================

class TestParseNativeToolCalls:
    """_parse() converts tool_calls entries to ntcode text lines."""

    def test_single_tool_call_converted(self):
        raw = _raw(None, tool_calls=[_tool_call("read_file", {"filename": "README.md"})])
        text, _, _ = OpenAILLM._parse(raw)
        assert text == 'tool: read_file({"filename": "README.md"})'

    def test_multiple_tool_calls_one_per_line(self):
        raw = _raw(None, tool_calls=[
            _tool_call("git_status", {}),
            _tool_call("read_file", {"filename": "a.py"}),
        ])
        text, _, _ = OpenAILLM._parse(raw)
        lines = text.splitlines()
        assert len(lines) == 2
        assert lines[0] == "tool: git_status({})"
        assert lines[1] == 'tool: read_file({"filename": "a.py"})'

    def test_args_are_compact_json(self):
        """Arguments must be re-serialised as compact single-line JSON."""
        # Provide pretty-printed JSON as the model might return it
        pretty = json.dumps({"filename": "x.py", "flag": True}, indent=2)
        raw = _raw(None, tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": pretty},
        }])
        text, _, _ = OpenAILLM._parse(raw)
        # The line must be a single line (no embedded newlines)
        assert "\n" not in text
        assert text.startswith("tool: read_file(")

    def test_token_counts_still_extracted(self):
        raw = _raw(None,
                   tool_calls=[_tool_call("git_status", {})],
                   usage={"prompt_tokens": 20, "completion_tokens": 3})
        _, inp, out = OpenAILLM._parse(raw)
        assert inp == 20
        assert out == 3

    def test_empty_tool_calls_list_gives_empty_string(self):
        """content=null with an empty tool_calls list -> empty string."""
        raw = _raw(None, tool_calls=[])
        text, _, _ = OpenAILLM._parse(raw)
        assert text == ""

    def test_content_empty_string_also_triggers_tool_call_path(self):
        """Some models return '' instead of null for content."""
        raw = _raw("", tool_calls=[_tool_call("git_status", {})])
        text, _, _ = OpenAILLM._parse(raw)
        assert text == "tool: git_status({})"

    def test_malformed_tool_call_entry_skipped(self):
        """A tool_call with invalid JSON arguments is skipped; others kept."""
        bad = {
            "id": "call_bad",
            "type": "function",
            "function": {"name": "read_file", "arguments": "NOT JSON"},
        }
        good = _tool_call("git_status", {})
        raw = _raw(None, tool_calls=[bad, good])
        text, _, _ = OpenAILLM._parse(raw)
        # Only the good call should appear
        assert "git_status" in text
        assert "read_file" not in text

    def test_tool_call_missing_function_key_skipped(self):
        """A tool_call entry missing the 'function' key is skipped."""
        bad = {"id": "call_x", "type": "function"}  # no 'function' key
        raw = _raw(None, tool_calls=[bad])
        text, _, _ = OpenAILLM._parse(raw)
        assert text == ""


# ===========================================================================
# Error handling
# ===========================================================================

class TestParseErrors:
    """_parse() raises RuntimeError on fundamentally broken response shapes."""

    def test_missing_choices_raises(self):
        with pytest.raises(RuntimeError, match="choices"):
            OpenAILLM._parse({})

    def test_empty_choices_raises(self):
        with pytest.raises(RuntimeError):
            OpenAILLM._parse({"choices": []})

    def test_missing_message_raises(self):
        with pytest.raises(RuntimeError):
            OpenAILLM._parse({"choices": [{"finish_reason": "stop"}]})
