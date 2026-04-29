"""Tests for memory_store, memory_search, memory_list, and search_codebase.

All memory tests use tmp_path so they never touch the real storage/memory/
directory and leave no side-effects on the repo.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


# ---------------------------------------------------------------------------
# Helper: redirect _MEMORY_DIR in all three memory modules to tmp_path/memory
# ---------------------------------------------------------------------------

def _mem_patches(mem_dir: Path):
    """Return list of patch objects pointing all memory modules at mem_dir."""
    targets = [
        "tools.memory_store._MEMORY_DIR",
        "tools.memory_search._MEMORY_DIR",
        "tools.memory_list._MEMORY_DIR",
    ]
    return [patch(t, mem_dir) for t in targets]


# ===========================================================================
# memory_store
# ===========================================================================

class TestMemoryStore:
    def test_store_creates_file(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        with _mem_patches(mem)[0]:
            result = memory_store_tool("proj_convention", "Use type hints everywhere.", ["python", "style"])
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
        with _mem_patches(mem)[0]:
            result = memory_store_tool("bare", "No tags here.")
        assert "stored" in result
        assert result["tags"] == []

    def test_store_invalid_key_spaces(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        with _mem_patches(mem)[0]:
            result = memory_store_tool("bad key with spaces", "content")
        assert "error" in result

    def test_store_invalid_key_empty(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        with _mem_patches(mem)[0]:
            result = memory_store_tool("", "content")
        assert "error" in result

    def test_store_empty_content_rejected(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        with _mem_patches(mem)[0]:
            result = memory_store_tool("key", "   ")
        assert "error" in result

    def test_store_hyphens_and_underscores_ok(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        with _mem_patches(mem)[0]:
            result = memory_store_tool("my-key_v2", "Valid key format.")
        assert "stored" in result

    def test_store_multiple_writes_distinct_files(self, tmp_path):
        """Two calls with the same key produce two distinct timestamped files."""
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_store import memory_store_tool
        import time
        with _mem_patches(mem)[0]:
            memory_store_tool("dup_key", "First write.")
            time.sleep(1.1)  # ensure different second in filename
            memory_store_tool("dup_key", "Second write.")
        files = list(mem.glob("dup_key_*.md"))
        assert len(files) == 2


# ===========================================================================
# memory_search
# ===========================================================================

class TestMemorySearch:
    def _populate(self, mem: Path):
        """Write two memory files directly for search tests."""
        (mem / "pref_20240101_120000.md").write_text(
            "---\ntimestamp: 2024-01-01T12:00:00\ntags: [python, style]\nkey: pref\n---\n"
            "User prefers snake_case variable names.\n",
            encoding="utf-8",
        )
        (mem / "arch_20240102_120000.md").write_text(
            "---\ntimestamp: 2024-01-02T12:00:00\ntags: [architecture]\nkey: arch\n---\n"
            "The project uses a three-layer architecture: frontend, middleware, backend.\n",
            encoding="utf-8",
        )

    def test_search_finds_match(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("snake_case")
        assert result["result_count"] == 1
        assert result["results"][0]["key"] == "pref"

    def test_search_case_insensitive(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("SNAKE_CASE")
        assert result["result_count"] == 1

    def test_search_no_match(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("nonexistentterm_xyz")
        assert result["result_count"] == 0
        assert result["results"] == []

    def test_search_tag_filter_matches(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("architecture", tags=["architecture"])
        assert result["result_count"] == 1
        assert result["results"][0]["key"] == "arch"

    def test_search_tag_filter_excludes(self, tmp_path):
        """Tag filter that doesn't match the file with the keyword → empty."""
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            # 'snake_case' is in pref file (tag: python/style) but we filter for 'architecture'
            result = memory_search_tool("snake_case", tags=["architecture"])
        assert result["result_count"] == 0

    def test_search_empty_dir(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("anything")
        assert result["result_count"] == 0

    def test_search_nonexistent_dir_returns_empty(self, tmp_path):
        """If storage/memory doesn't exist yet, return empty not an error."""
        missing = tmp_path / "does_not_exist"
        from tools.memory_search import memory_search_tool
        with patch("tools.memory_search._MEMORY_DIR", missing):
            result = memory_search_tool("query")
        assert result["result_count"] == 0
        assert "error" not in result

    def test_search_empty_query_returns_error(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("")
        assert "error" in result

    def test_search_invalid_regex_returns_error(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("[unclosed bracket")
        assert "error" in result

    def test_search_result_has_expected_fields(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_search import memory_search_tool
        with _mem_patches(mem)[1]:
            result = memory_search_tool("snake_case")
        r = result["results"][0]
        for field in ("file", "key", "timestamp", "tags", "snippet"):
            assert field in r, f"missing field: {field}"


# ===========================================================================
# memory_list
# ===========================================================================

class TestMemoryList:
    def _populate(self, mem: Path):
        """Write three memory files with known content."""
        (mem / "aaa_20240101_000000.md").write_text(
            "---\ntimestamp: 2024-01-01T00:00:00\ntags: [python]\nkey: aaa\n---\nOldest memory.\n",
            encoding="utf-8",
        )
        (mem / "bbb_20240102_000000.md").write_text(
            "---\ntimestamp: 2024-01-02T00:00:00\ntags: [architecture, python]\nkey: bbb\n---\nMiddle memory.\n",
            encoding="utf-8",
        )
        (mem / "ccc_20240103_000000.md").write_text(
            "---\ntimestamp: 2024-01-03T00:00:00\ntags: [style]\nkey: ccc\n---\nNewest memory.\n",
            encoding="utf-8",
        )

    def test_list_all(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        with _mem_patches(mem)[2]:
            result = memory_list_tool()
        assert result["total"] == 3
        keys = {m["key"] for m in result["memories"]}
        assert keys == {"aaa", "bbb", "ccc"}

    def test_list_tag_filter(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        with _mem_patches(mem)[2]:
            result = memory_list_tool(tag="python")
        assert result["total"] == 2
        keys = {m["key"] for m in result["memories"]}
        assert keys == {"aaa", "bbb"}

    def test_list_tag_filter_no_match(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        with _mem_patches(mem)[2]:
            result = memory_list_tool(tag="nonexistent_tag")
        assert result["total"] == 0

    def test_list_limit(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        with _mem_patches(mem)[2]:
            result = memory_list_tool(limit=2)
        assert result["total"] == 2

    def test_list_summary_present(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        with _mem_patches(mem)[2]:
            result = memory_list_tool()
        for m in result["memories"]:
            assert "summary" in m
            assert len(m["summary"]) > 0

    def test_list_empty_dir(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        from tools.memory_list import memory_list_tool
        with _mem_patches(mem)[2]:
            result = memory_list_tool()
        assert result["total"] == 0
        assert result["memories"] == []

    def test_list_nonexistent_dir_returns_empty(self, tmp_path):
        """If storage/memory doesn't exist yet, return empty not an error."""
        missing = tmp_path / "does_not_exist"
        from tools.memory_list import memory_list_tool
        with patch("tools.memory_list._MEMORY_DIR", missing):
            result = memory_list_tool()
        assert result["total"] == 0
        assert "error" not in result

    def test_list_result_has_expected_fields(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        self._populate(mem)
        from tools.memory_list import memory_list_tool
        with _mem_patches(mem)[2]:
            result = memory_list_tool()
        for m in result["memories"]:
            for field in ("file", "key", "timestamp", "tags", "summary"):
                assert field in m, f"missing field: {field}"


# ===========================================================================
# search_codebase
# ===========================================================================

class TestSearchCodebase:
    def _make_tree(self, tmp_path: Path) -> Path:
        """Create a small synthetic source tree for search tests."""
        root = tmp_path / "src"
        root.mkdir()
        (root / "alpha.py").write_text(
            "def hello_world():\n    print('Hello, world!')\n",
            encoding="utf-8",
        )
        (root / "beta.py").write_text(
            "class MyClass:\n    def method(self):\n        pass\n",
            encoding="utf-8",
        )
        sub = root / "sub"
        sub.mkdir()
        (sub / "gamma.py").write_text(
            "# gamma module\nHELLO = 'hello_world'\n",
            encoding="utf-8",
        )
        # Binary file — must be silently skipped, not crash.
        (root / "data.bin").write_bytes(bytes(range(256)))
        return root

    def test_find_function_name(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("hello_world", path=str(root))
        assert "error" not in result, result
        assert result["match_count"] >= 2  # alpha.py def + gamma.py string
        files_hit = {m["file"] for m in result["matches"]}
        assert "alpha.py" in files_hit

    def test_case_insensitive_default(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("HELLO_WORLD", path=str(root))
        assert result["match_count"] >= 1

    def test_case_sensitive_flag(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            # 'HELLO_WORLD' uppercase only in gamma.py (HELLO = 'hello_world')
            # alpha.py has 'hello_world' lowercase — should NOT match
            result = search_codebase_tool(
                "HELLO_WORLD", path=str(root), case_sensitive=True
            )
        files_hit = {m["file"] for m in result["matches"]}
        assert "alpha.py" not in files_hit

    def test_glob_filter(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool(
                "hello", path=str(root), glob="alpha.py"
            )
        # Only alpha.py matches the glob — gamma.py is in sub/ and excluded
        assert all(m["file"] == "alpha.py" for m in result["matches"])

    def test_no_match_returns_empty(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("zzz_no_such_term_xyz", path=str(root))
        assert result["match_count"] == 0
        assert result["matches"] == []

    def test_empty_query_returns_error(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("", path=str(root))
        assert "error" in result

    def test_invalid_regex_returns_error(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("[bad regex", path=str(root))
        assert "error" in result

    def test_max_results_capped(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool(".", path=str(root), max_results=2)
        assert result["match_count"] <= 2
        assert result["truncated"] is True

    def test_result_has_line_number(self, tmp_path):
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("hello_world", path=str(root))
        for m in result["matches"]:
            assert "line" in m
            assert isinstance(m["line"], int)
            assert m["line"] >= 1

    def test_binary_file_skipped(self, tmp_path):
        """Binary data.bin must be skipped silently — no crash, no error key."""
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("hello", path=str(root))
        assert "error" not in result
        assert result["files_skipped"] >= 1  # data.bin counted as skipped

    def test_subdirectory_searched_recursively(self, tmp_path):
        """Files in sub/ should be found with the default ** glob."""
        from tools.search_codebase import search_codebase_tool
        root = self._make_tree(tmp_path)
        with patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path]):
            result = search_codebase_tool("gamma", path=str(root))
        files_hit = {m["file"] for m in result["matches"]}
        assert any("gamma" in f for f in files_hit)

    def test_path_outside_sandbox_returns_error(self, tmp_path):
        """Paths outside ALLOWED_BASE_PATHS should return an error, not crash."""
        from tools.search_codebase import search_codebase_tool
        # ALLOWED_BASE_PATHS stays at cwd — /tmp is outside it
        result = search_codebase_tool("hello", path="/tmp")
        assert "error" in result
