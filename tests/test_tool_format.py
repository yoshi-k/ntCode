"""Tests for utils/tool_format.py.

Covers:
- _detect_family()  : model-name routing
- _parse_ntcode()   : original text-protocol parser
- _parse_xml()      : <tool_call> block parser
- _parse_json_block(): fenced-JSON parser
- format_tools_for_provider(): smoke-tests each formatter produces key strings
- get_parser_for_provider()  : returns the right callable

All tests are offline (no LLM calls, no file I/O).
The TOOL_REGISTRY is patched with a minimal two-tool stub so tests are
independent of the real tool implementations.
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import patch

import utils.config as cfg_module

import pytest

# ---------------------------------------------------------------------------
# Minimal stub tool registry used throughout
# ---------------------------------------------------------------------------

def _stub_read(filename: str) -> Dict[str, Any]:
    """Stub: read a file."""
    return {"content": ""}


def _stub_git_status() -> Dict[str, Any]:
    """Stub: show git status."""
    return {"staged": []}


_STUB_REGISTRY = {
    "read_file": _stub_read,
    "git_status": _stub_git_status,
}


# ---------------------------------------------------------------------------
# Helper: patch TOOL_REGISTRY inside tool_format parsers
# ---------------------------------------------------------------------------

_REGISTRY_PATH = "tools.registry.TOOL_REGISTRY"


# ===========================================================================
# _detect_family
# ===========================================================================

class TestDetectFamily:
    """Unit tests for the model-name -> family routing."""

    def _call(self, provider: str, model: str) -> str:
        from utils.tool_format import _detect_family
        with patch.object(cfg_module, "CALLING_CONVENTION", ""):
            return _detect_family(provider, model)

    # ---- Anthropic Claude -------------------------------------------------
    def test_claude_sonnet(self):
        assert self._call("anthropic", "claude-sonnet-4-6") == "ntcode"

    def test_claude_opus(self):
        assert self._call("anthropic", "claude-opus-4-5") == "ntcode"

    # ---- OpenAI-compatible ------------------------------------------------
    def test_gpt4o(self):
        assert self._call("openai", "gpt-4o") == "ntcode"

    def test_llama(self):
        assert self._call("openai", "llama3") == "ntcode"

    def test_phi(self):
        assert self._call("openai", "phi-3-mini") == "ntcode"

    def test_gemma(self):
        assert self._call("openai", "gemma-2-9b") == "gemma"

    def test_gemma3(self):
        assert self._call("openai", "google/gemma-3-27b-it") == "gemma"

    def test_gemma4(self):
        assert self._call("openai", "gemma-4") == "gemma"

    def test_gemma_uppercase(self):
        assert self._call("openai", "GEMMA-3-27B") == "gemma"

    # ---- Qwen ---------------------------------------------------------------
    def test_qwen3_27b(self):
        assert self._call("openai", "Qwen/Qwen3-27B") == "xml"

    def test_qwen25_coder(self):
        assert self._call("openai", "qwen2.5-coder:7b") == "xml"

    def test_qwen_uppercase(self):
        # Detection must be case-insensitive
        assert self._call("openai", "QWEN3-32B") == "xml"

    # ---- DeepSeek -----------------------------------------------------------
    # DeepSeek models (v3, v4, R1, etc.) emit <tool_call>...</tool_call> blocks
    # when prompted correctly, same as Qwen.
    def test_deepseek_v4_pro(self):
        assert self._call("openai", "deepseek/deepseek-v4-pro") == "xml"

    def test_deepseek_v3(self):
        assert self._call("openai", "deepseek/deepseek-v3") == "xml"

    def test_deepseek_r1(self):
        assert self._call("openai", "deepseek-r1") == "xml"

    def test_deepseek_uppercase(self):
        # Detection must be case-insensitive
        assert self._call("openai", "DEEPSEEK-V4-PRO") == "xml"

    # ---- Mistral / Mixtral --------------------------------------------------
    def test_mistral_7b(self):
        assert self._call("openai", "mistral-7b-instruct") == "json_block"

    def test_mixtral(self):
        assert self._call("openai", "mixtral-8x7b") == "json_block"

    def test_mistral_large(self):
        assert self._call("openai", "mistral-large-latest") == "json_block"

    @pytest.mark.parametrize("convention", ["ntcode", "xml", "json_block", "gemma"])
    def test_calling_convention_override_wins(self, convention):
        from utils.tool_format import _detect_family
        with patch.object(cfg_module, "CALLING_CONVENTION", convention):
            assert _detect_family("openai", "some-unknown-model") == convention

    def test_calling_convention_auto_uses_model_detection(self):
        from utils.tool_format import _detect_family
        with patch.object(cfg_module, "CALLING_CONVENTION", "auto"):
            assert _detect_family("openai", "Qwen/Qwen3-27B") == "xml"


# ===========================================================================
# ntcode parser
# ===========================================================================

class TestParseNtcode:
    """Tests for _parse_ntcode()."""

    def _parse(self, text: str):
        from utils.tool_format import _parse_ntcode
        with patch(_REGISTRY_PATH, _STUB_REGISTRY):
            return _parse_ntcode(text)

    def test_single_call_with_args(self):
        result = self._parse('tool: read_file({"filename": "README.md"})')
        assert result == [("read_file", {"filename": "README.md"})]

    def test_single_call_no_args(self):
        result = self._parse("tool: git_status({})")
        assert result == [("git_status", {})]

    def test_multiple_calls(self):
        text = (
            'tool: read_file({"filename": "a.py"})\n'
            "tool: git_status({})"
        )
        result = self._parse(text)
        assert result == [
            ("read_file", {"filename": "a.py"}),
            ("git_status", {}),
        ]

    def test_prose_lines_ignored(self):
        text = "Here is my plan.\ntool: git_status({})\nDone."
        result = self._parse(text)
        assert result == [("git_status", {})]

    def test_unknown_tool_skipped(self):
        result = self._parse('tool: no_such_tool({"x": 1})')
        assert result == []

    def test_malformed_json_skipped(self):
        result = self._parse("tool: read_file({bad json})")
        assert result == []

    def test_missing_parens_skipped(self):
        result = self._parse("tool: read_file")
        assert result == []

    def test_non_dict_args_skipped(self):
        # JSON array instead of object
        result = self._parse("tool: read_file([1, 2, 3])")
        assert result == []

    def test_empty_tool_name_skipped(self):
        result = self._parse('tool: ({"x": 1})')
        assert result == []


# ===========================================================================
# xml parser
# ===========================================================================

class TestParseXml:
    """Tests for _parse_xml()."""

    def _parse(self, text: str):
        from utils.tool_format import _parse_xml
        with patch(_REGISTRY_PATH, _STUB_REGISTRY):
            return _parse_xml(text)

    def test_single_call(self):
        text = (
            "<tool_call>\n"
            '{"name": "git_status", "arguments": {}}\n'
            "</tool_call>"
        )
        assert self._parse(text) == [("git_status", {})]

    def test_call_with_args(self):
        text = (
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"filename": "x.py"}}\n'
            "</tool_call>"
        )
        assert self._parse(text) == [("read_file", {"filename": "x.py"})]

    def test_accepts_args_key_alias(self):
        """Some models emit 'args' instead of 'arguments'."""
        text = (
            "<tool_call>\n"
            '{"name": "git_status", "args": {}}\n'
            "</tool_call>"
        )
        assert self._parse(text) == [("git_status", {})]

    def test_multiple_blocks(self):
        text = (
            "<tool_call>\n"
            '{"name": "git_status", "arguments": {}}\n'
            "</tool_call>\n"
            "Some prose in between.\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"filename": "b.py"}}\n'
            "</tool_call>"
        )
        result = self._parse(text)
        assert result == [
            ("git_status", {}),
            ("read_file", {"filename": "b.py"}),
        ]

    def test_prose_ignored(self):
        text = "Thinking…\n<tool_call>\n{\"name\": \"git_status\", \"arguments\": {}}\n</tool_call>\nDone."
        assert self._parse(text) == [("git_status", {})]

    def test_unknown_tool_skipped(self):
        text = (
            "<tool_call>\n"
            '{"name": "no_such_tool", "arguments": {}}\n'
            "</tool_call>"
        )
        assert self._parse(text) == []

    def test_malformed_json_skipped(self):
        text = "<tool_call>\nnot json\n</tool_call>"
        assert self._parse(text) == []

    def test_missing_name_skipped(self):
        text = (
            "<tool_call>\n"
            '{"arguments": {}}\n'
            "</tool_call>"
        )
        assert self._parse(text) == []

    def test_no_blocks_returns_empty(self):
        assert self._parse("Just a plain response.") == []


# ===========================================================================
# json_block parser
# ===========================================================================

class TestParseJsonBlock:
    """Tests for _parse_json_block()."""

    def _parse(self, text: str):
        from utils.tool_format import _parse_json_block
        with patch(_REGISTRY_PATH, _STUB_REGISTRY):
            return _parse_json_block(text)

    def test_single_call(self):
        text = '```json\n{"tool": "git_status", "args": {}}\n```'
        assert self._parse(text) == [("git_status", {})]

    def test_call_with_args(self):
        text = '```json\n{"tool": "read_file", "args": {"filename": "z.py"}}\n```'
        assert self._parse(text) == [("read_file", {"filename": "z.py"})]

    def test_fence_without_language_tag(self):
        """``` without 'json' tag should also match."""
        text = '```\n{"tool": "git_status", "args": {}}\n```'
        assert self._parse(text) == [("git_status", {})]

    def test_multiple_blocks(self):
        text = (
            '```json\n{"tool": "git_status", "args": {}}\n```\n'
            "Some prose.\n"
            '```json\n{"tool": "read_file", "args": {"filename": "c.py"}}\n```'
        )
        result = self._parse(text)
        assert result == [
            ("git_status", {}),
            ("read_file", {"filename": "c.py"}),
        ]

    def test_prose_ignored(self):
        text = 'Sure!\n```json\n{"tool": "git_status", "args": {}}\n```\nDone.'
        assert self._parse(text) == [("git_status", {})]

    def test_unknown_tool_skipped(self):
        text = '```json\n{"tool": "no_such_tool", "args": {}}\n```'
        assert self._parse(text) == []

    def test_malformed_json_skipped(self):
        text = "```json\nnot json\n```"
        assert self._parse(text) == []

    def test_missing_tool_key_skipped(self):
        text = '```json\n{"args": {}}\n```'
        assert self._parse(text) == []

    def test_no_blocks_returns_empty(self):
        assert self._parse("Plain response.") == []


# ===========================================================================
# format_tools_for_provider
# ===========================================================================

class TestFormatToolsForProvider:
    """Smoke-tests that each formatter produces the expected key strings."""

    def _format(self, provider: str, model: str) -> str:
        from utils.tool_format import format_tools_for_provider
        return format_tools_for_provider(provider, model, _STUB_REGISTRY)

    def test_ntcode_contains_tool_name(self):
        out = self._format("anthropic", "claude-sonnet-4-6")
        assert "read_file" in out
        assert "git_status" in out

    def test_ntcode_contains_signature(self):
        out = self._format("anthropic", "claude-sonnet-4-6")
        assert "filename" in out

    def test_xml_contains_tool_call_instruction(self):
        out = self._format("openai", "Qwen/Qwen3-27B")
        assert "<tool_call>" in out
        assert "read_file" in out

    def test_xml_contains_json_schema(self):
        out = self._format("openai", "qwen2.5-coder:7b")
        # JSON schema entries for each tool
        assert '"name"' in out
        assert '"description"' in out
        assert '"parameters"' in out

    def test_json_block_contains_fence_instruction(self):
        out = self._format("openai", "mistral-7b-instruct")
        assert "```json" in out
        assert "read_file" in out

    def test_json_block_contains_json_schema(self):
        out = self._format("openai", "mixtral-8x7b")
        assert '"name"' in out
        assert '"description"' in out

    def test_unknown_model_falls_back_to_ntcode(self):
        out = self._format("openai", "some-unknown-model-xyz")
        # Should fall back to ntcode format (contains TOOL header)
        assert "TOOL" in out
        assert "read_file" in out

    # --- Regression: double-brace bug ----------------------------------------
    # The XML and json_block prompt headers are plain string literals, NOT
    # f-strings.  If {{ / }} are used they appear literally in the prompt,
    # causing models to copy the malformed example instead of valid JSON.

    def test_xml_header_example_has_no_doubled_braces(self):
        """The <tool_call> example block must contain valid single-brace JSON."""
        import re
        out = self._format("openai", "qwen3:1.7b")
        # Match ONLY the first example block (the one in the header),
        # stopping at the first "</tool_call>" to avoid greedily consuming
        # tool-schema JSON later in the output.
        match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", out)
        assert match is not None, "No <tool_call> example found in XML format output"
        example = match.group(1).strip()
        assert "{{" not in example, f"XML header example contains '{{{{' (doubled-brace bug): {example!r}"
        assert "}}" not in example, f"XML header example contains '}}}}' (doubled-brace bug): {example!r}"

    def test_json_block_header_example_has_no_doubled_braces(self):
        """The ```json example block must contain valid single-brace JSON."""
        import re
        out = self._format("openai", "mistral-7b-instruct")
        # Match ONLY the first ```json block (the example in the header)
        # to avoid greedily consuming tool-schema JSON later in the output.
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", out)
        assert match is not None, "No ```json example found in json_block format output"
        example = match.group(1).strip()
        assert "{{" not in example, f"json_block header example contains '{{{{' (doubled-brace bug): {example!r}"
        assert "}}" not in example, f"json_block header example contains '}}}}' (doubled-brace bug): {example!r}"


# ===========================================================================
# get_parser_for_provider
# ===========================================================================

class TestGetParserForProvider:
    """Tests that the right parser callable is returned."""

    def _get(self, provider: str, model: str):
        from utils.tool_format import get_parser_for_provider
        return get_parser_for_provider(provider, model)

    def test_anthropic_returns_ntcode_parser(self):
        from utils.tool_format import _parse_ntcode
        assert self._get("anthropic", "claude-sonnet-4-6") is _parse_ntcode

    def test_gpt4o_returns_ntcode_parser(self):
        from utils.tool_format import _parse_ntcode
        assert self._get("openai", "gpt-4o") is _parse_ntcode

    def test_qwen_returns_xml_parser(self):
        from utils.tool_format import _parse_xml
        assert self._get("openai", "Qwen/Qwen3-27B") is _parse_xml

    def test_mistral_returns_json_block_parser(self):
        from utils.tool_format import _parse_json_block
        assert self._get("openai", "mistral-7b-instruct") is _parse_json_block

    def test_mixtral_returns_json_block_parser(self):
        from utils.tool_format import _parse_json_block
        assert self._get("openai", "mixtral-8x7b") is _parse_json_block

    def test_returned_parser_is_callable(self):
        parser = self._get("openai", "llama3")
        assert callable(parser)

    def test_parser_returns_list(self):
        parser = self._get("anthropic", "claude-sonnet-4-6")
        with patch(_REGISTRY_PATH, _STUB_REGISTRY):
            result = parser("No tool calls here.")
        assert isinstance(result, list)

    def test_gemma_returns_gemma_parser(self):
        from utils.tool_format import _parse_gemma
        assert self._get("openai", "gemma-3-27b-it") is _parse_gemma


# ===========================================================================
# gemma parser
# ===========================================================================

class TestParseGemma:
    """Tests for _parse_gemma()."""

    def _parse(self, text: str):
        from utils.tool_format import _parse_gemma
        with patch(_REGISTRY_PATH, _STUB_REGISTRY):
            return _parse_gemma(text)

    def test_single_call_no_args(self):
        text = "<|tool_call>call:tool:git_status({})<tool_call|>"
        assert self._parse(text) == [("git_status", {})]

    def test_single_call_with_quoted_args(self):
        text = '<|tool_call>call:tool:read_file({"filename": "README.md"})<tool_call|>'
        assert self._parse(text) == [("read_file", {"filename": "README.md"})]

    def test_unquoted_keys_fixed(self):
        """JS-style unquoted keys should be accepted."""
        text = '<|tool_call>call:tool:read_file({filename: "README.md"})<tool_call|>'
        assert self._parse(text) == [("read_file", {"filename": "README.md"})]

    def test_without_call_tool_prefix(self):
        """Delimiter body without the call:tool: prefix should also parse."""
        text = '<|tool_call>git_status({})<tool_call|>'
        assert self._parse(text) == [("git_status", {})]

    def test_multiple_blocks(self):
        text = (
            '<|tool_call>call:tool:git_status({})<tool_call|>\n'
            'Some prose.\n'
            '<|tool_call>call:tool:read_file({"filename": "a.py"})<tool_call|>'
        )
        result = self._parse(text)
        assert result == [
            ("git_status", {}),
            ("read_file", {"filename": "a.py"}),
        ]

    def test_prose_ignored(self):
        text = 'Thinking...\n<|tool_call>call:tool:git_status({})<tool_call|>\nDone.'
        assert self._parse(text) == [("git_status", {})]

    def test_unknown_tool_skipped(self):
        text = "<|tool_call>call:tool:no_such_tool({})<tool_call|>"
        assert self._parse(text) == []

    def test_malformed_json_skipped(self):
        text = "<|tool_call>call:tool:read_file({bad!!! json})<tool_call|>"
        assert self._parse(text) == []

    def test_missing_parens_skipped(self):
        text = "<|tool_call>call:tool:git_status<tool_call|>"
        assert self._parse(text) == []

    def test_no_blocks_returns_empty(self):
        assert self._parse("Just a plain response.") == []

    def test_delimiter_in_json_value(self):
        """Regression: closing <tool_call|> inside a JSON string value must
        not prematurely terminate the block match.

        This was the bug reported in tool_fail.json: when the model emitted
        an edit_file call whose new_str contained the literal text
        '<tool_call|>', the non-greedy .*? regex stopped at the embedded
        token instead of the real closing delimiter, truncating the body and
        triggering the 'Missing closing )' warning.
        """
        # Simulated Gemma output where the JSON value contains the closing
        # delimiter sequence as a literal string.
        inner = '<tool_call|>'
        text = (
            '<|tool_call>call:tool:read_file({"filename": "'
            + inner
            + '"})<tool_call|>'
        )
        result = self._parse(text)
        assert result == [("read_file", {"filename": inner})]

    def test_multiline_new_str_with_delimiter_in_value(self):
        """Regression: multi-line new_str containing <tool_call|> and newlines
        (the exact pattern from the failing session log) must parse correctly.
        """
        import json as _json
        args = {
            "path": "utils/tool_format.py",
            "old_str": "_GEMMA_BLOCK_RE = re.compile(",
            "new_str": '_GEMMA_BLOCK_RE = re.compile(\n    r"<|tool_call>call:tool:(.*?)\n',
        }
        # Build the full Gemma-style tool call string
        args_json = _json.dumps(args)
        text = f"<|tool_call>call:tool:read_file({args_json})<tool_call|>"
        result = self._parse(text)
        assert result == [("read_file", args)]

    def test_actual_gemma4_output(self):
        """Regression test using the exact output captured from Gemma4."""
        text = '<|tool_call>call:tool:read_file({path: "."})<tool_call|>'
        # Note: read_file not list_files here since stub only has read_file
        # Use list_files-style: patch with a registry that has list_files
        from utils.tool_format import _parse_gemma
        stub = {
            "list_files": _stub_git_status,  # reuse stub fn, name is what matters
            "read_file": _stub_read,
        }
        with patch(_REGISTRY_PATH, stub):
            result = _parse_gemma('<|tool_call>call:tool:list_files({path: "."})<tool_call|>')
        assert result == [("list_files", {"path": "."})]


# ===========================================================================
# gemma formatter
# ===========================================================================

class TestFormatGemma:
    """Smoke-tests for the Gemma tool-description formatter."""

    def _format(self, model: str) -> str:
        from utils.tool_format import format_tools_for_provider
        return format_tools_for_provider("openai", model, _STUB_REGISTRY)

    def test_contains_delimiter_instruction(self):
        out = self._format("gemma-3-27b-it")
        assert "<|tool_call>" in out
        assert "<tool_call|>" in out

    def test_contains_tool_names(self):
        out = self._format("gemma-3-27b-it")
        assert "read_file" in out
        assert "git_status" in out

    def test_contains_json_schema_fields(self):
        out = self._format("google/gemma-4")
        assert '"name"' in out
        assert '"description"' in out
        assert '"parameters"' in out

    def test_gemma4_model_name_detected(self):
        """format_tools_for_provider selects gemma family for gemma-4."""
        from utils.tool_format import _detect_family
        assert _detect_family("openai", "gemma-4") == "gemma"
