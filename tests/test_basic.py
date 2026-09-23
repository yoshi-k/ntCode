#!/usr/bin/env python3
"""Basic tests for ntCode functionality."""

import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from utils.security import resolve_abs_path, validate_file_access
from tools.read_file import read_file_tool
from tools.list_files import list_files_tool


class TestPathHandling:
    """Test path resolution and validation."""
    
    def test_resolve_abs_path_relative(self):
        """Test that relative paths are resolved correctly."""
        result = resolve_abs_path("test.txt")
        assert result.is_absolute()
        assert result.name == "test.txt"
    
    def test_resolve_abs_path_absolute(self):
        """Test that absolute paths are handled correctly."""
        abs_path = "/tmp/test.txt"
        result = resolve_abs_path(abs_path)
        assert str(result) == abs_path
    
    def test_validate_file_access_current_dir(self):
        """Test that current directory access is allowed."""
        current_file = Path(__file__)
        try:
            validate_file_access(current_file)
            # Should not raise exception
            assert True
        except PermissionError:
            pytest.fail("Should allow access to current directory")


class TestFileOperations:
    """Test file operation tools."""
    
    def test_read_file_existing(self):
        """Test reading an existing file."""
        # Read this test file itself
        result = read_file_tool(__file__)
        assert "error" not in result
        assert "content" in result
        assert "test_read_file_existing" in result["content"]
    
    def test_read_file_nonexistent(self):
        """Test reading a non-existent file."""
        result = read_file_tool("nonexistent_file_12345.txt")
        assert "error" in result
        assert "not found" in result["error"].lower()
    
    def test_list_files_current_dir(self):
        """Test listing files in current directory."""
        result = list_files_tool(".")
        assert "error" not in result
        assert "files" in result
        # Should contain at least some expected files
        filenames = [f["filename"] for f in result["files"]]
        assert "ntCode.py" in filenames



if __name__ == "__main__":
    pytest.main([__file__])
