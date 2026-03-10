"""Unit tests for utils.dummy_llm.DummyLLM."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Path / import setup — keep consistent with the rest of the test suite
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub out anthropic so utils.llm can be imported without the real SDK.
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())

# Stub ANTHROPIC_API_KEY so utils.llm's module-level AnthropicLLM() doesn't
# blow up when the environment variable is absent.
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-key-for-tests")

from utils.dummy_llm import DummyLLM  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent / "dummy_responses.txt"


def _make(tmp_path: Path, lines: list[str]) -> DummyLLM:
    """Write *lines* to a temp replay file and return a DummyLLM for it."""
    p = tmp_path / "replay.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return DummyLLM(p)


# ---------------------------------------------------------------------------
# Basic replay behaviour
# ---------------------------------------------------------------------------

class TestBasicReplay(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_first_call_returns_first_line(self):
        llm = _make(self.tmp, ["alpha", "beta"])
        self.assertEqual(llm.call(system="s", messages=[]), "alpha")

    def test_calls_return_lines_in_order(self):
        lines = ["one", "two", "three"]
        llm = _make(self.tmp, lines)
        results = [llm.call("", []) for _ in lines]
        self.assertEqual(results, lines)

    def test_cycles_when_file_exhausted(self):
        llm = _make(self.tmp, ["only"])
        for _ in range(5):
            self.assertEqual(llm.call("", []), "only")

    def test_wrap_around_sequence(self):
        llm = _make(self.tmp, ["a", "b"])
        results = [llm.call("", []) for _ in range(5)]
        self.assertEqual(results, ["a", "b", "a", "b", "a"])

    def test_returns_str(self):
        llm = _make(self.tmp, ["hello"])
        result = llm.call("", [])
        self.assertIsInstance(result, str)

    def test_system_and_messages_ignored(self):
        """call() must always return the replayed line regardless of inputs."""
        llm = _make(self.tmp, ["fixed"])
        r1 = llm.call(system="system A", messages=[{"role": "user", "content": "hi"}])
        llm.reset()
        r2 = llm.call(system="system B", messages=[])
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# File filtering (blank lines and comments)
# ---------------------------------------------------------------------------

class TestFileFiltering(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, content: str) -> DummyLLM:
        p = self.tmp / "r.txt"
        p.write_text(content, encoding="utf-8")
        return DummyLLM(p)

    def test_blank_lines_skipped(self):
        llm = self._write("\nfirst\n\nsecond\n")
        self.assertEqual(llm.call("", []), "first")
        self.assertEqual(llm.call("", []), "second")

    def test_comment_lines_skipped(self):
        llm = self._write("# comment\nreal response\n")
        self.assertEqual(llm.call("", []), "real response")

    def test_only_comments_raises_value_error(self):
        p = self.tmp / "comments_only.txt"
        p.write_text("# nothing\n\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            DummyLLM(p)

    def test_empty_file_raises_value_error(self):
        p = self.tmp / "blank.txt"
        p.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            DummyLLM(p)

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            DummyLLM(self.tmp / "no_such.txt")


# ---------------------------------------------------------------------------
# reset() / reload() helpers and properties
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_reset_restarts_from_first_line(self):
        llm = _make(self.tmp, ["x", "y"])
        llm.call("", [])   # consumes "x"
        llm.reset()
        self.assertEqual(llm.call("", []), "x")

    def test_response_count(self):
        llm = _make(self.tmp, ["a", "b", "c"])
        self.assertEqual(llm.response_count, 3)

    def test_current_index_advances(self):
        llm = _make(self.tmp, ["a", "b", "c"])
        self.assertEqual(llm.current_index, 0)
        llm.call("", [])
        self.assertEqual(llm.current_index, 1)

    def test_current_index_wraps(self):
        llm = _make(self.tmp, ["a"])
        llm.call("", [])   # index becomes 1, which wraps to 0
        self.assertEqual(llm.current_index, 0)

    def test_reload_same_path_picks_up_new_content(self):
        p = self.tmp / "r.txt"
        p.write_text("original", encoding="utf-8")
        llm = DummyLLM(p)
        llm.call("", [])   # advance past first line

        p.write_text("updated", encoding="utf-8")
        llm.reload()       # re-read same file, reset index
        self.assertEqual(llm.call("", []), "updated")

    def test_reload_with_new_path(self):
        p1 = self.tmp / "r1.txt"
        p2 = self.tmp / "r2.txt"
        p1.write_text("from r1", encoding="utf-8")
        p2.write_text("from r2", encoding="utf-8")
        llm = DummyLLM(p1)
        llm.reload(p2)
        self.assertEqual(llm.call("", []), "from r2")


# ---------------------------------------------------------------------------
# LLM ABC conformance + integration with execute_llm_call
# ---------------------------------------------------------------------------

class TestLLMConformance(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_is_subclass_of_llm(self):
        from utils.llm import LLM
        self.assertTrue(issubclass(DummyLLM, LLM))

    def test_works_with_execute_llm_call(self):
        """execute_llm_call must pass the replayed string through unchanged."""
        from utils.llm import execute_llm_call
        llm = _make(self.tmp, ["great success"])
        # execute_llm_call takes a conversation list and uses the module-level
        # `llm` singleton, so we patch it temporarily.
        import utils.llm as llm_module
        original = llm_module.llm
        try:
            llm_module.llm = llm
            result = execute_llm_call(
                [{"role": "user", "content": "hello"}]
            )
        finally:
            llm_module.llm = original
        self.assertEqual(result, "great success")


# ---------------------------------------------------------------------------
# Sanity-check the shipped fixture file
# ---------------------------------------------------------------------------

class TestFixtureFile(unittest.TestCase):

    def test_fixture_file_loads(self):
        llm = DummyLLM(FIXTURE)
        self.assertGreater(llm.response_count, 0)

    def test_fixture_file_returns_non_empty_strings(self):
        llm = DummyLLM(FIXTURE)
        for _ in range(llm.response_count):
            text = llm.call("", [])
            self.assertIsInstance(text, str)
            self.assertTrue(text.strip())

    def test_fixture_file_cycles(self):
        llm = DummyLLM(FIXTURE)
        first = llm.call("", [])
        # exhaust all lines
        for _ in range(llm.response_count - 1):
            llm.call("", [])
        # next call should wrap back to the first line
        wrapped = llm.call("", [])
        self.assertEqual(first, wrapped)


if __name__ == "__main__":
    unittest.main()
