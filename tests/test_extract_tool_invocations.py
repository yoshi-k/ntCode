"""Unit tests for extract_tool_invocations() in ntCode.py"""

import sys
import os

# Allow importing ntCode from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub out anthropic and dotenv so ntCode can be imported without credentials
import types

anthropicmod = types.ModuleType("anthropic")
class _FakeAnthropic:
    def __init__(self, **kwargs): pass
anthropicmod.Anthropic = _FakeAnthropic
anthropicmod.APITimeoutError = Exception
anthropicmod.RateLimitError = Exception
anthropicmod.APIConnectionError = Exception
anthropicmod.AuthenticationError = Exception
anthropicmod.APIError = Exception
sys.modules["anthropic"] = anthropicmod

dotenvmod = types.ModuleType("dotenv")
dotenvmod.load_dotenv = lambda: None
sys.modules["dotenv"] = dotenvmod

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from ntCode import extract_tool_invocations  # noqa: E402


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_single_valid_invocation():
    text = 'tool: read_file({"filename": "foo.py"})'
    result = extract_tool_invocations(text)
    assert len(result) == 1
    name, args = result[0]
    assert name == "read_file"
    assert args == {"filename": "foo.py"}


def test_multiple_invocations_only_first_line_counts():
    text = (
        'tool: read_file({"filename": "a.py"})\n'
        'tool: list_files({"path": "."})')
    result = extract_tool_invocations(text)
    assert len(result) == 2
    assert result[0][0] == "read_file"
    assert result[1][0] == "list_files"


def test_empty_args():
    text = "tool: git_status({})"
    result = extract_tool_invocations(text)
    assert len(result) == 1
    assert result[0][0] == "git_status"
    assert result[0][1] == {}


def test_boolean_and_int_args():
    text = 'tool: git_log({"max_entries": 5, "file_path": ""})'
    result = extract_tool_invocations(text)
    assert len(result) == 1
    _, args = result[0]
    assert args["max_entries"] == 5


def test_no_tool_lines():
    text = "Just a normal response with no tools."
    result = extract_tool_invocations(text)
    assert result == []


def test_tool_line_mixed_with_prose():
    """Lines not starting with 'tool:' should be ignored."""
    text = (
        "Sure, I will read the file for you.\n"
        'tool: read_file({"filename": "bar.py"})\n'
        "That should do it."
    )
    result = extract_tool_invocations(text)
    assert len(result) == 1
    assert result[0][0] == "read_file"


# ---------------------------------------------------------------------------
# Malformed / adversarial input tests
# ---------------------------------------------------------------------------

def test_malformed_json_returns_empty():
    text = "tool: read_file({filename: missing_quotes})"
    result = extract_tool_invocations(text)
    assert result == [], "Malformed JSON should be skipped, not crash"


def test_missing_closing_paren_returns_empty():
    text = 'tool: read_file({"filename": "x.py"}'
    result = extract_tool_invocations(text)
    assert result == []


def test_missing_opening_paren_returns_empty():
    text = 'tool: read_file {"filename": "x.py"}'
    result = extract_tool_invocations(text)
    assert result == []


def test_unknown_tool_name_returns_empty():
    text = 'tool: delete_everything({"path": "/"})'
    result = extract_tool_invocations(text)
    assert result == [], "Unknown tools should be silently skipped"


def test_non_dict_json_returns_empty():
    """JSON array instead of object should be rejected."""
    text = 'tool: read_file(["filename"])'
    result = extract_tool_invocations(text)
    assert result == []


def test_empty_tool_name_returns_empty():
    text = 'tool: ({"filename": "x.py"})'
    result = extract_tool_invocations(text)
    assert result == []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_single_valid_invocation,
        test_multiple_invocations_only_first_line_counts,
        test_empty_args,
        test_boolean_and_int_args,
        test_no_tool_lines,
        test_tool_line_mixed_with_prose,
        test_malformed_json_returns_empty,
        test_missing_closing_paren_returns_empty,
        test_missing_opening_paren_returns_empty,
        test_unknown_tool_name_returns_empty,
        test_non_dict_json_returns_empty,
        test_empty_tool_name_returns_empty,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
