from pathlib import Path
from typing import Any, Dict

from utils.security import (
    resolve_abs_path,
    validate_file_access,
    validate_git_operation,
    run_git_command,
)


def git_log_tool(max_entries: int = 10, file_path: str = "") -> Dict[str, Any]:
    """
    Show commit history with filtering options.
    :param max_entries: Maximum number of log entries to return (default 10)
    :param file_path: Optional file path to show history for (empty for all commits)
    :return: Commit history with detailed information
    """
    try:
        # Validate we're in a git repo
        validate_git_operation()

        # Validate max_entries parameter
        if max_entries < 1:
            max_entries = 1
        elif max_entries > 100:  # Reasonable upper limit
            max_entries = 100

        # Build git log command
        cmd_args = [
            "log",
            f"--max-count={max_entries}",
            "--pretty=format:%H|%an|%ae|%ad|%s",
            "--date=iso",
        ]

        # Add file path if specified
        if file_path:
            try:
                # Validate file path is safe
                full_path = resolve_abs_path(file_path)
                validate_file_access(full_path)
                # Convert to relative path from repo root
                relative_path = str(full_path.relative_to(Path.cwd()))
                cmd_args.append("--")
                cmd_args.append(relative_path)
            except Exception as e:
                return {
                    "error": f"Invalid file path {file_path}: {str(e)}",
                    "success": False,
                }

        # Execute git log
        result = run_git_command(cmd_args)

        if not result["success"]:
            return {
                "error": f"Git log failed: {result.get('stderr', 'Unknown error')}",
                "success": False,
            }

        log_output = result["stdout"].strip()

        # Parse log output into structured data
        commits = []
        if log_output:
            for line in log_output.splitlines():
                if not line.strip():
                    continue

                parts = line.split("|")
                if len(parts) >= 5:
                    commit = {
                        "hash": parts[0],
                        "hash_short": parts[0][:8],
                        "author_name": parts[1],
                        "author_email": parts[2],
                        "date": parts[3],
                        "message": "|".join(
                            parts[4:]
                        ),  # Join back in case message contained '|'
                    }
                    commits.append(commit)

        # Get additional statistics if not filtering by file
        total_commits = len(commits)
        if not file_path and commits:
            # Get total commit count for repository
            count_result = run_git_command(["rev-list", "--count", "HEAD"])
            if count_result["success"]:
                try:
                    total_commits = int(count_result["stdout"].strip())
                except ValueError:
                    total_commits = len(commits)

        # Determine scope for summary
        scope = f" for {file_path}" if file_path else ""

        return {
            "success": True,
            "commits": commits,
            "file_path": file_path or "all files",
            "max_entries": max_entries,
            "entries_returned": len(commits),
            "has_more": len(commits) == max_entries and total_commits > max_entries,
            "summary": {
                "total_commits_in_repo": total_commits if not file_path else "unknown",
                "entries_shown": len(commits),
                "description": f"Showing last {len(commits)} commit(s){scope}",
            },
        }

    except Exception as e:
        return {"error": f"Git log operation failed: {str(e)}", "success": False}
