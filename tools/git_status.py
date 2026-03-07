from typing import Any, Dict

from utils.security import validate_git_operation, run_git_command


def git_status_tool() -> Dict[str, Any]:
    """
    Show repository status (staged, unstaged, untracked files).
    :return: Repository status with categorized file lists
    """
    try:
        # Validate we're in a git repo
        validate_git_operation()

        # Get porcelain status for easy parsing
        result = run_git_command(["status", "--porcelain"])

        if not result["success"]:
            return {
                "error": f"Git status failed: {result.get('stderr', 'Unknown error')}",
                "success": False,
            }

        # Parse the porcelain output
        staged = []
        unstaged = []
        untracked = []

        for line in result["stdout"].splitlines():
            if len(line) < 3:
                continue

            status_code = line[:2]
            filename = line[3:].strip()

            # First character is staged status, second is unstaged
            staged_status = status_code[0]
            unstaged_status = status_code[1]

            if staged_status in ["A", "M", "D", "R", "C"]:
                action = {
                    "A": "added",
                    "M": "modified",
                    "D": "deleted",
                    "R": "renamed",
                    "C": "copied",
                }.get(staged_status, "modified")
                staged.append({"file": filename, "action": action})

            if unstaged_status in ["M", "D"]:
                action = {"M": "modified", "D": "deleted"}.get(
                    unstaged_status, "modified"
                )
                unstaged.append({"file": filename, "action": action})

            if status_code == "??":
                untracked.append(filename)

        # Get current branch info
        branch_result = run_git_command(["branch", "--show-current"])
        current_branch = (
            branch_result["stdout"].strip() if branch_result["success"] else "unknown"
        )

        # Check if repository is clean
        is_clean = len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0

        return {
            "success": True,
            "current_branch": current_branch,
            "is_clean": is_clean,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "summary": {
                "staged_count": len(staged),
                "unstaged_count": len(unstaged),
                "untracked_count": len(untracked),
            },
        }

    except Exception as e:
        return {"error": f"Git status operation failed: {str(e)}", "success": False}
