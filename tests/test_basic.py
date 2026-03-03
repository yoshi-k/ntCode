#!/usr/bin/env python3
"""Basic tests for ntCode functionality."""

import pytest
import os
import sys
from pathlib import Path

# Add parent directory to path so we can import ntCode
sys.path.insert(0, str(Path(__file__).parent.parent))

from ntCode import (
    resolve_abs_path,
    validate_file_access,
    read_file_tool,
    list_files_tool,
    extract_tool_invocations
)


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


class TestToolInvocation:
    """Test tool invocation parsing."""
    
    def test_extract_simple_tool(self):
        """Test extracting a simple tool invocation."""
        text = 'tool: read_file({"filename": "test.txt"})'
        result = extract_tool_invocations(text)
        assert len(result) == 1
        assert result[0][0] == "read_file"
        assert result[0][1] == {"filename": "test.txt"}
    
    def test_extract_no_tools(self):
        """Test text with no tool invocations."""
        text = "This is just regular text with no tools."
        result = extract_tool_invocations(text)
        assert len(result) == 0
    
    def test_extract_invalid_json(self):
        """Test handling of malformed JSON in tool invocation."""
        text = 'tool: read_file({invalid json})'
        result = extract_tool_invocations(text)
        assert len(result) == 0  # Should skip malformed invocations
    
    def test_extract_empty_args(self):
        """Test tool invocation with empty arguments."""
        text = 'tool: git_status({})'
        result = extract_tool_invocations(text)
        assert len(result) == 1
        assert result[0][0] == "git_status"
        assert result[0][1] == {}


if __name__ == "__main__":
    pytest.main([__file__])
