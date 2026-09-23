"""Unit tests for utils.dummy_llm.DummyProvider."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path / import setup — keep consistent with the rest of the test suite
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub ANTHROPIC_API_KEY so utils.llm's module-level provider doesn't
# blow up when the environment variable is absent.
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-key-for-tests")

from utils.dummy_llm import DummyProvider  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent / "dummy_responses.txt"


def _make(tmp_path: Path, lines: list[str]) -> DummyProvider:
    """Write *lines* to a temp replay file and return a DummyProvider for it."""
    p = tmp_path / "replay.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return DummyProvider(p)


def _text(provider: DummyProvider, *_args, **_kwargs) -> str:
    """Next reply's text; the arguments are ignored, as by complete()."""
    return provider.complete("", [], []).message.text


# ---------------------------------------------------------------------------
# Basic replay behaviour
# ---------------------------------------------------------------------------

class TestBasicReplay(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_first_call_returns_first_line(self):
        llm = _make(self.tmp, ["alpha", "beta"])
        self.assertEqual(_text(llm, system="s", messages=[]), "alpha")

    def test_calls_return_lines_in_order(self):
        lines = ["one", "two", "three"]
        llm = _make(self.tmp, lines)
        results = [_text(llm, "", []) for _ in lines]
        self.assertEqual(results, lines)

    def test_cycles_when_file_exhausted(self):
        llm = _make(self.tmp, ["only"])
        for _ in range(5):
            self.assertEqual(_text(llm, "", []), "only")

    def test_wrap_around_sequence(self):
        llm = _make(self.tmp, ["a", "b"])
        results = [_text(llm, "", []) for _ in range(5)]
        self.assertEqual(results, ["a", "b", "a", "b", "a"])

    def test_returns_str(self):
        llm = _make(self.tmp, ["hello"])
        result = _text(llm, "", [])
        self.assertIsInstance(result, str)

    def test_system_and_messages_ignored(self):
        """call() must always return the replayed line regardless of inputs."""
        llm = _make(self.tmp, ["fixed"])
        r1 = _text(llm, system="system A", messages=[{"role": "user", "content": "hi"}])
        llm.reset()
        r2 = _text(llm, system="system B", messages=[])
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# File filtering (blank lines and comments)
# ---------------------------------------------------------------------------

class TestFileFiltering(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, content: str) -> DummyProvider:
        p = self.tmp / "r.txt"
        p.write_text(content, encoding="utf-8")
        return DummyProvider(p)

    def test_blank_lines_skipped(self):
        llm = self._write("\nfirst\n\nsecond\n")
        self.assertEqual(_text(llm, "", []), "first")
        self.assertEqual(_text(llm, "", []), "second")

    def test_comment_lines_skipped(self):
        llm = self._write("# comment\nreal response\n")
        self.assertEqual(_text(llm, "", []), "real response")

    def test_only_comments_raises_value_error(self):
        p = self.tmp / "comments_only.txt"
        p.write_text("# nothing\n\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            DummyProvider(p)

    def test_empty_file_raises_value_error(self):
        p = self.tmp / "blank.txt"
        p.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            DummyProvider(p)

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            DummyProvider(self.tmp / "no_such.txt")


# ---------------------------------------------------------------------------
# reset() / reload() helpers and properties
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_reset_restarts_from_first_line(self):
        llm = _make(self.tmp, ["x", "y"])
        _text(llm, "", [])   # consumes "x"
        llm.reset()
        self.assertEqual(_text(llm, "", []), "x")

    def test_response_count(self):
        llm = _make(self.tmp, ["a", "b", "c"])
        self.assertEqual(llm.response_count, 3)

    def test_current_index_advances(self):
        llm = _make(self.tmp, ["a", "b", "c"])
        self.assertEqual(llm.current_index, 0)
        _text(llm, "", [])
        self.assertEqual(llm.current_index, 1)

    def test_current_index_wraps(self):
        llm = _make(self.tmp, ["a"])
        _text(llm, "", [])   # index becomes 1, which wraps to 0
        self.assertEqual(llm.current_index, 0)

    def test_reload_same_path_picks_up_new_content(self):
        p = self.tmp / "r.txt"
        p.write_text("original", encoding="utf-8")
        llm = DummyProvider(p)
        _text(llm, "", [])   # advance past first line

        p.write_text("updated", encoding="utf-8")
        llm.reload()       # re-read same file, reset index
        self.assertEqual(_text(llm, "", []), "updated")

    def test_reload_with_new_path(self):
        p1 = self.tmp / "r1.txt"
        p2 = self.tmp / "r2.txt"
        p1.write_text("from r1", encoding="utf-8")
        p2.write_text("from r2", encoding="utf-8")
        llm = DummyProvider(p1)
        llm.reload(p2)
        self.assertEqual(_text(llm, "", []), "from r2")


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class TestProviderConformance(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_is_a_provider(self):
        from providers.base import Provider
        self.assertTrue(issubclass(DummyProvider, Provider))

    def test_tool_lines_become_tool_calls(self):
        llm = _make(self.tmp, ['tool: read_file({"filename": "a.py"})', "done"])
        turn = llm.complete("", [], [])
        self.assertEqual(turn.stop_reason, "tool_use")
        (call,) = turn.message.tool_calls
        self.assertEqual((call.name, call.args), ("read_file", {"filename": "a.py"}))
        self.assertEqual(llm.complete("", [], []).stop_reason, "end_turn")


# ---------------------------------------------------------------------------
# Sanity-check the shipped fixture file
# ---------------------------------------------------------------------------

class TestFixtureFile(unittest.TestCase):

    def test_fixture_file_loads(self):
        llm = DummyProvider(FIXTURE)
        self.assertGreater(llm.response_count, 0)

    def test_fixture_file_replies_have_text_or_tool_calls(self):
        llm = DummyProvider(FIXTURE)
        for _ in range(llm.response_count):
            message = llm.complete("", [], []).message
            self.assertTrue(message.text.strip() or message.tool_calls)

    def test_fixture_file_cycles(self):
        llm = DummyProvider(FIXTURE)
        first = _text(llm, "", [])
        # exhaust all lines
        for _ in range(llm.response_count - 1):
            _text(llm, "", [])
        # next call should wrap back to the first line
        wrapped = _text(llm, "", [])
        self.assertEqual(first, wrapped)


if __name__ == "__main__":
    unittest.main()
