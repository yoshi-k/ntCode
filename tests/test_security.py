"""Unit tests for path security validation."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from utils.security import validate_file_access, resolve_abs_path
from tools.read_file import read_file_tool
from tools.edit_file import edit_file_tool


# ---------------------------------------------------------------------------
# validate_file_access tests
# ---------------------------------------------------------------------------

def test_current_dir_is_allowed():
    """A path inside cwd should pass validation without raising."""
    safe_path = Path.cwd() / "ntCode.py"
    try:
        validate_file_access(safe_path)
    except PermissionError:
        assert False, "cwd path should be allowed"


def test_path_outside_cwd_is_rejected():
    """A path outside cwd should raise PermissionError."""
    outside_path = Path("/tmp/secret.txt")
    try:
        validate_file_access(outside_path)
        assert False, "Should have raised PermissionError"
    except PermissionError:
        pass  # expected


def test_path_traversal_attempt_rejected():
    """Paths with '..' components should be rejected."""
    traversal = Path("subdir/../../etc/passwd")
    try:
        validate_file_access(traversal)
        assert False, "Should have raised PermissionError"
    except PermissionError:
        pass  # expected


# ---------------------------------------------------------------------------
# resolve_abs_path tests
# ---------------------------------------------------------------------------

def test_relative_path_resolved_to_absolute():
    result = resolve_abs_path("ntCode.py")
    assert result.is_absolute()
    assert result == Path.cwd() / "ntCode.py"


def test_absolute_path_unchanged():
    abs_path = "/tmp/something.txt"
    result = resolve_abs_path(abs_path)
    assert result.is_absolute()
    assert str(result) == abs_path


# ---------------------------------------------------------------------------
# read_file_tool security tests
# ---------------------------------------------------------------------------

def test_read_file_outside_cwd_returns_error():
    result = read_file_tool("/etc/passwd")
    assert "error" in result
    assert "content" not in result


def test_read_file_nonexistent_returns_error():
    result = read_file_tool("this_file_does_not_exist_xyz.py")
    assert "error" in result


# ---------------------------------------------------------------------------
# edit_file_tool security tests
# ---------------------------------------------------------------------------

def test_edit_file_outside_cwd_returns_error():
    result = edit_file_tool("/tmp/evil.py", "", "malicious code")
    assert "error" in result


def test_edit_file_within_cwd_works():
    """Creating and cleaning up a temp file within cwd should succeed."""
    tmp_name = "_test_temp_edit_file.txt"
    tmp_path = Path.cwd() / tmp_name
    try:
        result = edit_file_tool(tmp_name, "", "hello world")
        assert result.get("action") == "created_file", f"Unexpected result: {result}"
        assert tmp_path.read_text() == "hello world"
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_current_dir_is_allowed,
        test_path_outside_cwd_is_rejected,
        test_path_traversal_attempt_rejected,
        test_relative_path_resolved_to_absolute,
        test_absolute_path_unchanged,
        test_read_file_outside_cwd_returns_error,
        test_read_file_nonexistent_returns_error,
        test_edit_file_outside_cwd_returns_error,
        test_edit_file_within_cwd_works,
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
