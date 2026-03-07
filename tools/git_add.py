from pathlib import Path
from typing import Any, Dict, List

from utils.security import (
    resolve_abs_path,
    validate_file_access,
    validate_git_operation,
    run_git_command,
)


def git_add_tool(file_paths: List[str]) -> Dict[str, Any]:
    """
    Stage files for commit with validation.
    :param file_paths: List of file paths to stage for commit
    :return: Result of git add operation with staged files info
    """
    try:
        # Validate we're in a git repo
        validate_git_operation()

        if not file_paths:
            return {"error": "No file paths provided", "success": False}

        # Validate all file paths are safe
        validated_paths = []
        for file_path in file_paths:
            try:
                full_path = resolve_abs_path(file_path)
                validate_file_access(full_path)
                validated_paths.append(str(full_path.relative_to(Path.cwd())))
            except PermissionError as e:
                return {
                    "error": f"Access denied for {file_path}: {str(e)}",
                    "success": False,
                }
            except Exception as e:
                return {
                    "error": f"Invalid path {file_path}: {str(e)}",
                    "success": False,
                }

        # Execute git add command
        cmd_args = ["add"] + validated_paths
        result = run_git_command(cmd_args)

        if not result["success"]:
            return {
                "error": f"Git add failed: {result.get('stderr', 'Unknown error')}",
                "success": False,
            }

        # Get status to show what was staged
        status_result = run_git_command(["status", "--porcelain"])
        staged_files = []
        if status_result["success"]:
            for line in status_result["stdout"].splitlines():
                if (
                    line.startswith("A ")
                    or line.startswith("M ")
                    or line.startswith("D ")
                ):
                    staged_files.append(line[3:].strip())

        return {
            "success": True,
            "staged_files": staged_files,
            "message": f"Successfully staged {len(validated_paths)} file(s)",
            "files_requested": validated_paths,
        }

    except Exception as e:
        return {"error": f"Git add operation failed: {str(e)}", "success": False}
