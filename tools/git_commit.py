from typing import Any, Dict

from utils.security import validate_git_operation, run_git_command


# Git Tools
def git_commit_tool(message: str = "", auto_generate: bool = False) -> Dict[str, Any]:
    """
    Smart commit with optional LLM-generated messages.
    :param message: Commit message to use (optional if auto_generate is True)
    :param auto_generate: Whether to auto-generate commit message based on staged changes
    :return: Result of git commit operation with commit info
    """
    try:
        # Validate we're in a git repo
        validate_git_operation()

        # Check if there are staged changes
        status_result = run_git_command(["status", "--porcelain"])
        if not status_result["success"]:
            return {
                "error": f"Failed to check git status: {status_result.get('stderr', 'Unknown error')}",
                "success": False,
            }

        staged_changes = []
        for line in status_result["stdout"].splitlines():
            # Look for staged changes (index status is not ' ' or '?')
            if len(line) >= 2 and line[0] in "AMDRC":
                staged_changes.append(line)

        if not staged_changes:
            return {
                "error": "No staged changes to commit",
                "success": False,
                "suggestion": "Use git_add to stage files first",
            }

        # Generate commit message if requested
        commit_message = message
        if auto_generate and not message:
            try:
                # Get diff of staged changes
                diff_result = run_git_command(["diff", "--cached"])
                if diff_result["success"] and diff_result["stdout"].strip():
                    # Simple auto-generation based on file changes
                    files_changed = [change[3:].strip() for change in staged_changes]
                    if len(files_changed) == 1:
                        commit_message = f"Update {files_changed[0]}"
                    else:
                        commit_message = (
                            f"Update {len(files_changed)} files: "
                            f"{', '.join(files_changed[:3])}"
                            f"{'...' if len(files_changed) > 3 else ''}"
                        )
                else:
                    commit_message = "Update staged changes"
            except Exception:
                commit_message = "Update staged changes"

        if not commit_message:
            return {
                "error": "No commit message provided and auto_generate is False",
                "success": False,
            }

        # Execute git commit
        cmd_args = ["commit", "-m", commit_message]
        result = run_git_command(cmd_args)

        if not result["success"]:
            return {
                "error": f"Git commit failed: {result.get('stderr', 'Unknown error')}",
                "success": False,
            }

        # Parse commit info from output
        commit_info = result["stdout"].strip()

        return {
            "success": True,
            "message": commit_message,
            "staged_files": [change[3:].strip() for change in staged_changes],
            "commit_output": commit_info,
            "files_committed": len(staged_changes),
        }

    except Exception as e:
        return {"error": f"Git commit operation failed: {str(e)}", "success": False}
