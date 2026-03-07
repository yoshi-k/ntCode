import subprocess
import shlex
from pathlib import Path
from typing import Any, Dict, List

from utils.config import ALLOWED_BASE_PATHS, GIT_TIMEOUT, logger


def validate_file_access(path: Path) -> None:
    """
    Validates that the given path is within allowed directories and safe to access.
    :param path: The path to validate
    :raises PermissionError: If path is outside allowed directories
    :raises ValueError: If path has security issues
    """
    try:
        resolved_path = path.resolve()

        # Check if path is within allowed base paths
        if not any(
            resolved_path.is_relative_to(base.resolve()) for base in ALLOWED_BASE_PATHS
        ):
            raise PermissionError(
                f"Access denied: Path outside allowed directories: {path}"
            )

        # Additional security checks
        if ".." in str(path):  # Prevent path traversal attempts
            raise ValueError(f"Path traversal attempt detected: {path}")

        # Check for symbolic links that might escape the allowed paths
        if resolved_path.is_symlink():
            link_target = resolved_path.readlink()
            if link_target.is_absolute():
                validate_file_access(link_target)

    except Exception as e:
        raise PermissionError(f"Path validation failed for {path}: {str(e)}")


def resolve_abs_path(path_str: str) -> Path:
    """
    file.py -> `pwd`/file.py
    """
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def validate_git_operation(repo_path: Path = None) -> None:
    """
    Validates git operations are safe and within allowed repository bounds.
    :param repo_path: Repository path to validate (defaults to current)
    :raises PermissionError: If operation is outside allowed scope
    """
    if repo_path is None:
        repo_path = Path.cwd()

    # Ensure we're in a git repository
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        raise PermissionError("Not in a git repository")

    # Use existing security validation
    validate_file_access(repo_path)


def run_git_command(cmd_args: List[str], cwd: Path = None) -> Dict[str, Any]:
    """
    Safely execute a git command with proper error handling.
    :param cmd_args: Git command arguments (e.g., ['status', '--porcelain'])
    :param cwd: Working directory (defaults to current)
    :return: Command result with stdout, stderr, and return code
    """
    if cwd is None:
        cwd = Path.cwd()

    try:
        validate_git_operation(cwd)

        # subprocess.run with a list (not shell=True) does not perform shell
        # expansion, so no quoting is needed.  shlex is kept imported for any
        # future shell-string usage elsewhere in the module.
        full_cmd = ["git"] + cmd_args

        result = subprocess.run(
            full_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,  # Prevent hanging
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "success": result.returncode == 0,
        }

    except subprocess.TimeoutExpired:
        return {"error": "Git command timed out", "success": False}
    except PermissionError as e:
        return {"error": str(e), "success": False}
    except Exception as e:
        return {"error": f"Git command failed: {str(e)}", "success": False}
