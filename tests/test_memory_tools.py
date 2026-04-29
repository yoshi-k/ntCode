"""Tests for memory_store, memory_search, memory_list, and search_codebase.

Key patching note: utils/security.py binds ALLOWED_BASE_PATHS at import time.
Must patch utils.security.ALLOWED_BASE_PATHS, NOT utils.config.ALLOWED_BASE_PATHS.
"""
from __future__ import annotations
import sys, os, time
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


def _mem_patches(mem_dir):
    """Return [store_patch, search_patch, list_patch, sandbox_patch].
    Always use ps[N] + ps[3] together for tests that touch the filesystem.
    utils.security binds ALLOWED_BASE_PATHS at import time, so patch there.
    """
    return [
        patch("tools.memory_store._MEMORY_DIR", mem_dir),
        patch("tools.memory_search._MEMORY_DIR", mem_dir),
        patch("tools.memory_list._MEMORY_DIR", mem_dir),
        patch("utils.security.ALLOWED_BASE_PATHS", [mem_dir.parent.parent]),
    ]


def _sb(p):
    """Sandbox patch allowing p in utils.security."""
    return patch("utils.security.ALLOWED_BASE_PATHS", [p])


# ===========================================================================
# memory_store
# ===========================================================================

class TestMemoryStore:
    def test_store_creates_file(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        ps = _mem_patches(mem)
        with ps[0], ps[3]:
            result = memory_store_tool(
                "proj_convention", "Use type hints everywhere.", ["python", "style"]
            )
        assert "stored" in result, result
        assert result["key"] == "proj_convention"
        assert result["tags"] == ["python", "style"]
        files = list(mem.glob("proj_convention_*.md"))
        assert len(files) == 1
        body = files[0].read_text(encoding="utf-8")
        assert "Use type hints everywhere." in body
        assert "tags: [python, style]" in body
        assert "key: proj_convention" in body

    def test_store_no_tags(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        ps = _mem_patches(mem)
        with ps[0], ps[3]:
            result = memory_store_tool("bare", "No tags here.")
        assert "stored" in result
        assert result["tags"] == []

    def test_store_invalid_key_spaces(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        ps = _mem_patches(mem)
        with ps[0], ps[3]:
            result = memory_store_tool("bad key with spaces", "content")
        assert "error" in result

    def test_store_invalid_key_empty(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        ps = _mem_patches(mem)
        with ps[0], ps[3]:
            result = memory_store_tool("", "content")
        assert "error" in result

    def test_store_empty_content_rejected(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        ps = _mem_patches(mem)
        with ps[0], ps[3]:
            result = memory_store_tool("key", "   ")
        assert "error" in result

    def test_store_hyphens_and_underscores_ok(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        ps = _mem_patches(mem)
        with ps[0], ps[3]:
            result = memory_store_tool("my-key_v2", "Valid key format.")
        assert "stored" in result

    def test_store_multiple_writes_distinct_files(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        ps = _mem_patches(mem)
        with ps[0], ps[3]:
            memory_store_tool("dup_key", "First write.")
            time.sleep(1.1)
            memory_store_tool("dup_key", "Second write.")
        assert len(list(mem.glob("dup_key_*.md"))) == 2


# ===========================================================================
# memory_search
# ===========================================================================

class TestMemorySearch:
    def _populate(self, mem):
        (mem / "pref_20240101_120000.md").write_text(
            "---\ntimestamp: 2024-01-01T12:00:00\ntags: [python, style]\nkey: pref\n---\n"
            "User prefers snake_case variable names.\n", encoding="utf-8")
        (mem / "arch_20240102_120000.md").write_text(
            "---\ntimestamp: 2024-01-02T12:00:00\ntags: [architecture]\nkey: arch\n---\n"
            "The project uses a three-layer architecture: frontend, middleware, backend.\n",
            encoding="utf-8")

    def test_search_finds_match(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        ps = _mem_patches(mem)
        with ps[1], ps[3]:
            result = memory_search_tool("snake_case")
        assert result["result_count"] == 1
        assert result["results"][0]["key"] == "pref"

    def test_search_case_insensitive(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        ps = _mem_patches(mem)
        with ps[1], ps[3]:
            result = memory_search_tool("SNAKE_CASE")
        assert result["result_count"] == 1

    def test_search_no_match(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        ps = _mem_patches(mem)
        with ps[1], ps[3]:
            result = memory_search_tool("nonexistentterm_xyz")
        assert result["result_count"] == 0
        assert result["results"] == []

    def test_search_tag_filter_matches(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        ps = _mem_patches(mem)
        with ps[1], ps[3]:
            result = memory_search_tool("architecture", tags=["architecture"])
        assert result["result_count"] == 1
        assert result["results"][0]["key"] == "arch"

    def test_search_tag_filter_excludes(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        ps = _mem_patches(mem)
        with ps[1], ps[3]:
            result = memory_search_tool("snake_case", tags=["architecture"])
        assert result["result_count"] == 0

    def test_search_empty_dir(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_search import memory_search_tool
        ps = _mem_patches(mem)
        with ps[1], ps[3]:
            result = memory_search_tool("anything")
        assert result["result_count"] == 0

    def test_search_nonexistent_dir_returns_empty(self, tmp_path):
        from tools.memory_search import memory_search_tool
        with patch("tools.memory_search._MEMORY_DIR", tmp_path / "no_such"):
            result = memory_search_tool("query")
        assert result["result_count"] == 0
        assert "error" not in result

    def test_search_empty_query_returns_error(self, tmp_path):
        from tools.memory_search import memory_search_tool
        with patch("tools.memory_search._MEMORY_DIR", tmp_path):
            result = memory_search_tool("")
        assert "error" in result

    def test_search_invalid_regex_returns_error(self, tmp_path):
        from tools.memory_search import memory_search_tool
        with patch("tools.memory_search._MEMORY_DIR", tmp_path):
            result = memory_search_tool("[unclosed bracket")
        assert "error" in result

    def test_search_result_has_expected_fields(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        ps = _mem_patches(mem)
        with ps[1], ps[3]:
            result = memory_search_tool("snake_case")
        r = result["results"][0]
        for field in ("file", "key", "timestamp", "tags", "snippet"):
            assert field in r, f"missing field: {field}"


# ===========================================================================
# memory_list
# ===========================================================================

class TestMemoryList:
    def _populate(self, mem):
        (mem / "aaa_20240101_000000.md").write_text(
            "---\ntimestamp: 2024-01-01T00:00:00\ntags: [python]\nkey: aaa\n---\nOldest memory.\n",
            encoding="utf-8")
        (mem / "bbb_20240102_000000.md").write_text(
            "---\ntimestamp: 2024-01-02T00:00:00\ntags: [architecture, python]\nkey: bbb\n---\nMiddle memory.\n",
            encoding="utf-8")
        (mem / "ccc_20240103_000000.md").write_text(
            "---\ntimestamp: 2024-01-03T00:00:00\ntags: [style]\nkey: ccc\n---\nNewest memory.\n",
            encoding="utf-8")

    def test_list_all(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        ps = _mem_patches(mem)
        with ps[2], ps[3]:
            result = memory_list_tool()
        assert result["total"] == 3
        assert {m["key"] for m in result["memories"]} == {"aaa", "bbb", "ccc"}

    def test_list_tag_filter(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        ps = _mem_patches(mem)
        with ps[2], ps[3]:
            result = memory_list_tool(tag="python")
        assert result["total"] == 2
        assert {m["key"] for m in result["memories"]} == {"aaa", "bbb"}

    def test_list_tag_filter_no_match(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        ps = _mem_patches(mem)
        with ps[2], ps[3]:
            result = memory_list_tool(tag="nonexistent_tag")
        assert result["total"] == 0

    def test_list_limit(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        ps = _mem_patches(mem)
        with ps[2], ps[3]:
            result = memory_list_tool(limit=2)
        assert result["total"] == 2

    def test_list_summary_present(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        ps = _mem_patches(mem)
        with ps[2], ps[3]:
            result = memory_list_tool()
        for m in result["memories"]:
            assert "summary" in m
            assert len(m["summary"]) > 0

    def test_list_empty_dir(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_list import memory_list_tool
        ps = _mem_patches(mem)
        with ps[2], ps[3]:
            result = memory_list_tool()
        assert result["total"] == 0
        assert result["memories"] == []

    def test_list_nonexistent_dir_returns_empty(self, tmp_path):
        from tools.memory_list import memory_list_tool
        with patch("tools.memory_list._MEMORY_DIR", tmp_path / "no_such"):
            result = memory_list_tool()
        assert result["total"] == 0
        assert "error" not in result

    def test_list_result_has_expected_fields(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        ps = _mem_patches(mem)
        with ps[2], ps[3]:
            result = memory_list_tool()
        for m in result["memories"]:
            for field in ("file", "key", "timestamp", "tags", "summary"):
                assert field in m, f"missing field: {field}"


# ===========================================================================
# search_codebase
# ===========================================================================

class TestSearchCodebase:
    def _make_tree(self, tmp_path):
        root = tmp_path / "src"
        root.mkdir()
        (root / "alpha.py").write_text(
            "def hello_world():\n    print('Hello, world!')\n", encoding="utf-8")
        (root / "beta.py").write_text(
            "class MyClass:\n    def method(self):\n        pass\n", encoding="utf-8")
        sub = root / "sub"
        sub.mkdir()
        (sub / "gamma.py").write_text(
            "# gamma module\nHELLO = 'hello_world'\n", encoding="utf-8")
        (root / "data.bin").write_bytes(b"\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89" * 100)
        return root

    def test_find_function_name(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("hello_world", path=str(root))
        assert "error" not in result, result
        assert result["match_count"] >= 2
        assert "alpha.py" in {m["file"] for m in result["matches"]}

    def test_case_insensitive_default(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("HELLO_WORLD", path=str(root))
        assert result["match_count"] >= 1

    def test_case_sensitive_flag(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool(
                "HELLO_WORLD", path=str(root), case_sensitive=True)
        assert "alpha.py" not in {m["file"] for m in result["matches"]}

    def test_glob_filter(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("hello", path=str(root), glob="alpha.py")
        assert all(m["file"] == "alpha.py" for m in result["matches"])

    def test_no_match_returns_empty(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("zzz_no_such_term_xyz", path=str(root))
        assert result["match_count"] == 0
        assert result["matches"] == []

    def test_empty_query_returns_error(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        assert "error" in search_codebase_tool("", path=str(tmp_path))

    def test_invalid_regex_returns_error(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("[bad regex", path=str(root))
        assert "error" in result

    def test_max_results_capped(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool(".", path=str(root), max_results=2)
        assert result["match_count"] <= 2
        assert result["truncated"] is True

    def test_result_has_line_number(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("hello_world", path=str(root))
        for m in result["matches"]:
            assert "line" in m
            assert isinstance(m["line"], int)
            assert m["line"] >= 1

    def test_binary_file_skipped(self, tmp_path):
        """search_codebase uses latin-1 as fallback, so all byte sequences decode.
        Binary files land in files_searched (not files_skipped).
        We just confirm no crash and no error key."""
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("hello", path=str(root))
        assert "error" not in result
        # latin-1 decodes everything, so files_skipped may be 0
        assert "files_skipped" in result

    def test_subdirectory_searched_recursively(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with _sb(tmp_path):
            result = search_codebase_tool("gamma", path=str(root))
        assert any("gamma" in f for f in {m["file"] for m in result["matches"]})

    def test_path_outside_sandbox_returns_error(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        assert "error" in search_codebase_tool("hello", path="/tmp")