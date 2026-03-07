from pathlib import Path
from typing import Any, Dict

from utils.security import (
    resolve_abs_path,
    validate_file_access,
    validate_git_operation,
    run_git_command,
)


def git_diff_tool(file_path: str = "", staged: bool = False) -> Dict[str, Any]:
    """
    Display file differences with optional file filtering.
    :param file_path: Optional file path to show diff for (empty for all files)
    :param staged: Whether to show staged changes (True) or unstaged changes (False)
    :return: Diff output with file changes
    """
    try:
        # Validate we're in a git repo
        validate_git_operation()

        # Build git diff command
        cmd_args = ["diff"]

        if staged:
            cmd_args.append("--cached")  # Show staged changes

        # Add file path if specified
        if file_path:
            try:
                # Validate file path is safe
                full_path = resolve_abs_path(file_path)
                validate_file_access(full_path)
                # Convert to relative path from repo root
                relative_path = str(full_path.relative_to(Path.cwd()))
                cmd_args.append(relative_path)
            except Exception as e:
                return {
                    "error": f"Invalid file path {file_path}: {str(e)}",
                    "success": False,
                }

        # Execute git diff
        result = run_git_command(cmd_args)

        if not result["success"]:
            return {
                "error": f"Git diff failed: {result.get('stderr', 'Unknown error')}",
                "success": False,
            }

        diff_output = result["stdout"]

        # Parse diff output for summary info
        files_changed = []
        lines_added = 0
        lines_removed = 0

        current_file = None
        for line in diff_output.splitlines():
            if line.startswith("diff --git"):
                # Extract filename from "diff --git a/file b/file"
                parts = line.split()
                if len(parts) >= 4:
                    current_file = parts[3][2:]  # Remove "b/" prefix
                    if current_file not in files_changed:
                        files_changed.append(current_file)
            elif line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_removed += 1

        # Determine diff scope for summary
        scope = "staged" if staged else "unstaged"
        target = f" for {file_path}" if file_path else ""

        # Check if there are any changes
        has_changes = bool(diff_output.strip())

        return {
            "success": True,
            "diff_output": diff_output,
            "has_changes": has_changes,
            "scope": scope,
            "file_path": file_path or "all files",
            "files_changed": files_changed,
            "summary": {
                "files_count": len(files_changed),
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "description": f"Showing {scope} changes{target}",
            },
        }

    except Exception as e:
        return {"error": f"Git diff operation failed: {str(e)}", "success": False}
