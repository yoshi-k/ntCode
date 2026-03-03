#!/usr/bin/python

# Implementation of The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code
# https://www.mihaileric.com/The-Emperor-Has-No-Clothes/
# by Joerg Kulbartz joerg@kulbartz.de

import inspect
import json
import logging
import os
import subprocess
import shlex
import sys
import time
from datetime import datetime

import anthropic
from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List, Tuple


YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET_COLOR = "\u001b[0m"

load_dotenv()
claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Security Configuration
ALLOWED_BASE_PATHS = [Path.cwd()]  # Only allow current directory and subdirectories
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit

# Debug Configuration
DEBUG_MODE = os.environ.get("NTCODE_DEBUG", "false").lower() in ["true", "1", "yes"]
VERBOSE_MODE = os.environ.get("NTCODE_VERBOSE", "false").lower() in ["true", "1", "yes"]
LOG_CONVERSATIONS = os.environ.get("NTCODE_LOG_CONVERSATIONS", "true").lower() in ["true", "1", "yes"]

# Configure logging
log_handlers = []
if DEBUG_MODE:
    log_handlers.append(logging.StreamHandler(sys.stdout))
if LOG_CONVERSATIONS:
    log_handlers.append(logging.FileHandler('ntcode.log', mode='a'))
if not log_handlers:  # If no logging enabled, use null handler
    log_handlers.append(logging.NullHandler())

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger('ntCode')


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

        # Sanitize command arguments to prevent injection
        safe_args = [shlex.quote(str(arg)) for arg in cmd_args]
        full_cmd = ["git"] + cmd_args  # Don't quote the actual command, just args

        result = subprocess.run(
            full_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,  # Prevent hanging
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


# Read Files
def read_file_tool(filename: str) -> Dict[str, Any]:
    """
    Gets the full content of a file provided by the user.
    :param filename: The name of the file to read.
    :return: The full content of the file.
    """
    try:
        full_path = resolve_abs_path(filename)
        validate_file_access(full_path)

        # Check if file exists and is actually a file
        if not full_path.exists():
            return {"error": f"File not found: {filename}", "file_path": str(full_path)}

        if not full_path.is_file():
            return {
                "error": f"Path is not a file: {filename}",
                "file_path": str(full_path),
            }

        # Check file size before reading
        if full_path.stat().st_size > MAX_FILE_SIZE:
            return {
                "error": f"File too large (max {MAX_FILE_SIZE} bytes): {filename}",
                "file_path": str(full_path),
            }

        # Read file with proper encoding handling
        try:
            content = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Try with different encoding for binary files
            try:
                content = full_path.read_text(encoding="latin-1")
            except:
                return {
                    "error": f"Unable to read file as text: {filename}",
                    "file_path": str(full_path),
                }

        return {"file_path": str(full_path), "content": content}

    except PermissionError as e:
        return {"error": f"Access denied: {str(e)}", "file_path": filename}
    except Exception as e:
        return {"error": f"Error reading file: {str(e)}", "file_path": filename}


# List files
def list_files_tool(path: str) -> Dict[str, Any]:
    """
    Lists the files in a directory provided by the user.
    :param path: The path to a directory to list files from.
    :return: A list of files in the directory.
    """
    try:
        full_path = resolve_abs_path(path)
        validate_file_access(full_path)

        # Check if path exists and is a directory
        if not full_path.exists():
            return {"error": f"Directory not found: {path}", "path": str(full_path)}

        if not full_path.is_dir():
            return {"error": f"Path is not a directory: {path}", "path": str(full_path)}

        all_files = []
        for item in full_path.iterdir():
            try:
                # Only include items that would pass validation
                validate_file_access(item)
                all_files.append(
                    {"filename": item.name, "type": "file" if item.is_file() else "dir"}
                )
            except PermissionError:
                # Skip files/dirs that are outside allowed paths
                continue

        return {"path": str(full_path), "files": all_files}

    except PermissionError as e:
        return {"error": f"Access denied: {str(e)}", "path": path}
    except Exception as e:
        return {"error": f"Error listing directory: {str(e)}", "path": path}


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
                        commit_message = f"Update {len(files_changed)} files: {', '.join(files_changed[:3])}{'...' if len(files_changed) > 3 else ''}"
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
                "success": False
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
            
            if staged_status in ['A', 'M', 'D', 'R', 'C']:
                action = {'A': 'added', 'M': 'modified', 'D': 'deleted', 'R': 'renamed', 'C': 'copied'}.get(staged_status, 'modified')
                staged.append({"file": filename, "action": action})
            
            if unstaged_status in ['M', 'D']:
                action = {'M': 'modified', 'D': 'deleted'}.get(unstaged_status, 'modified')
                unstaged.append({"file": filename, "action": action})
            
            if status_code == '??':
                untracked.append(filename)
        
        # Get current branch info
        branch_result = run_git_command(["branch", "--show-current"])
        current_branch = branch_result["stdout"].strip() if branch_result["success"] else "unknown"
        
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
                "untracked_count": len(untracked)
            }
        }
        
    except Exception as e:
        return {"error": f"Git status operation failed: {str(e)}", "success": False}


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
                    "success": False
                }
        
        # Execute git diff
        result = run_git_command(cmd_args)
        
        if not result["success"]:
            return {
                "error": f"Git diff failed: {result.get('stderr', 'Unknown error')}",
                "success": False
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
                "description": f"Showing {scope} changes{target}"
            }
        }
        
    except Exception as e:
        return {"error": f"Git diff operation failed: {str(e)}", "success": False}


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
        cmd_args = ["log", f"--max-count={max_entries}", "--pretty=format:%H|%an|%ae|%ad|%s", "--date=iso"]
        
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
                    "success": False
                }
        
        # Execute git log
        result = run_git_command(cmd_args)
        
        if not result["success"]:
            return {
                "error": f"Git log failed: {result.get('stderr', 'Unknown error')}",
                "success": False
            }
        
        log_output = result["stdout"].strip()
        
        # Parse log output into structured data
        commits = []
        if log_output:
            for line in log_output.splitlines():
                if not line.strip():
                    continue
                
                parts = line.split('|')
                if len(parts) >= 5:
                    commit = {
                        "hash": parts[0],
                        "hash_short": parts[0][:8],
                        "author_name": parts[1],
                        "author_email": parts[2],
                        "date": parts[3],
                        "message": '|'.join(parts[4:])  # Join back in case message contained '|'
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
                "description": f"Showing last {len(commits)} commit(s){scope}"
            }
        }
        
    except Exception as e:
        return {"error": f"Git log operation failed: {str(e)}", "success": False}


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


# Edit files
def edit_file_tool(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """
    Replaces first occurence of old_str with new_str in file. If old_str is empy create/overwrite file with new_str.
    :param path: The path to the file to edit.
    :param old_str: The string to replace.
    :param new_str: The string to replace old_str with.
    :return: A dictionary with the path to the file and the action taken.
    """
    try:
        full_path = resolve_abs_path(path)
        validate_file_access(full_path)

        if old_str == "":
            # Creating/overwriting file
            full_path.write_text(new_str, encoding="utf-8")
            return {"path": str(full_path), "action": "created_file"}

        # Check file size before reading (for editing existing files)
        if full_path.exists() and full_path.stat().st_size > MAX_FILE_SIZE:
            return {
                "error": f"File too large: {full_path} (max {MAX_FILE_SIZE // 1024 // 1024}MB)",
                "path": str(full_path),
            }

        original = full_path.read_text(encoding="utf-8")
        if original.find(old_str) == -1:
            return {"path": str(full_path), "action": "old_str not found"}

        edited = original.replace(old_str, new_str, 1)
        full_path.write_text(edited, encoding="utf-8")
        return {"path": str(full_path), "action": "edited"}

    except PermissionError as e:
        return {"error": f"Access denied: {e}", "path": path}
    except FileNotFoundError:
        return {"error": f"File not found: {path}", "path": path}
    except Exception as e:
        return {"error": f"Error editing file: {e}", "path": path}


TOOL_REGISTRY = {
    "read_file": read_file_tool,
    "list_files": list_files_tool,
    "edit_file": edit_file_tool,
    "git_add": git_add_tool,
    "git_commit": git_commit_tool,
    "git_status": git_status_tool,
    "git_diff": git_diff_tool,
    "git_log": git_log_tool,
}


def get_tool_str_representation(tool_name: str) -> str:
    tool = TOOL_REGISTRY[tool_name]
    return f"""
    Name: {tool_name}
    Description: {tool.__doc__}
    Signature: {inspect.signature(tool)}
    """


SYSTEM_PROMPT = """
You are a coding assistant whose goal it is to help us solve coding tasks. You have access to a series of tools you can execute. Here are the tools

{tool_list_repr}

When you want to use a tool, reply with exactly one line in the format: 'tool: TOOL_NAME({{JSON_ARGS}})' and nothing else.
Use compact single-line JSON with double quotes. After receiving a tool_result(...) message, continue the task.
If no tool is needed, respond normally.
Do not respond with a line starting with "tool:" if you do not intent to use that tool.
"""


def get_full_system_prompt():
    tool_str_repr = ""
    for tool_name in TOOL_REGISTRY:
        tool_str_repr += "TOOL\n===" + get_tool_str_representation(tool_name)
        tool_str_repr += f"\n{'='*15}\n"
    return SYSTEM_PROMPT.format(tool_list_repr=tool_str_repr)


def extract_tool_invocations(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Return list of (tool_name, args) requested in 'tool: name({...}) lines.
    The parser expects single-line, compact JSON in the parentheses.
    """
    invocations = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("tool:"):
            continue
        try:
            after = line[len("tool:") :].strip()
            if "(" not in after:
                logger.warning(f"Invalid tool invocation format (missing parentheses): {line}")
                continue
            
            name, rest = after.split("(", 1)
            name = name.strip()
            
            if not name:
                logger.warning(f"Invalid tool invocation format (empty tool name): {line}")
                continue
                
            if not rest.endswith(")"):
                logger.warning(f"Invalid tool invocation format (missing closing parenthesis): {line}")
                continue
                
            json_str = rest[:-1].strip()
            
            # Handle empty JSON case
            if not json_str:
                args = {}
            else:
                try:
                    args = json.loads(json_str)
                    # Validate that args is a dictionary
                    if not isinstance(args, dict):
                        logger.warning(f"Tool arguments must be a dictionary, got {type(args).__name__}: {line}")
                        continue
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON in tool invocation: {json_str} - Error: {str(e)}")
                    continue
                except Exception as e:
                    logger.warning(f"Unexpected error parsing JSON in tool invocation: {json_str} - Error: {str(e)}")
                    continue
            
            # Validate tool name exists
            if name not in TOOL_REGISTRY:
                logger.warning(f"Unknown tool name: {name}")
                continue
                
            invocations.append((name, args))
            logger.debug(f"Successfully parsed tool invocation: {name} with args {args}")
            
        except ValueError as e:
            logger.warning(f"Error parsing tool invocation format: {line} - Error: {str(e)}")
            continue
        except Exception as e:
            logger.warning(f"Unexpected error parsing tool invocation: {line} - Error: {str(e)}")
            continue
    
    if DEBUG_MODE and invocations:
        logger.debug(f"Extracted {len(invocations)} tool invocations: {[name for name, _ in invocations]}")
    
    return invocations


def execute_llm_call(conversation: List[Dict[str, str]]):
    system_content = ""
    messages = []
    for msg in conversation:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            messages.append(msg)

    # Implement conversation pruning if it gets too long
    MAX_CONVERSATION_LENGTH = 50  # Maximum number of messages to keep
    if len(messages) > MAX_CONVERSATION_LENGTH:
        logger.info(f"Conversation too long ({len(messages)} messages), pruning to last {MAX_CONVERSATION_LENGTH}")
        # Keep system message and last MAX_CONVERSATION_LENGTH messages
        messages = messages[-MAX_CONVERSATION_LENGTH:]

    if LOG_CONVERSATIONS:
        logger.info(f"Sending {len(messages)} messages to LLM")
        if DEBUG_MODE:
            logger.debug(f"Messages: {json.dumps(messages, indent=2)}")

    try:
        start_time = time.time()
        
        response = claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            system=system_content,
            messages=messages,
        )
        
        end_time = time.time()
        response_time = end_time - start_time
        
        response_text = response.content[0].text
        
        if LOG_CONVERSATIONS:
            logger.info(f"Received response ({len(response_text)} chars) in {response_time:.2f}s")
            if DEBUG_MODE:
                logger.debug(f"Response: {response_text}")
        
        return response_text
        
    except anthropic.APITimeoutError as e:
        logger.error(f"API timeout error: {str(e)}")
        raise Exception(f"Request timed out. Try breaking your request into smaller parts.")
    except anthropic.APIConnectionError as e:
        logger.error(f"API connection error: {str(e)}")
        raise Exception(f"Failed to connect to Claude API. Check your internet connection.")
    except anthropic.APIError as e:
        logger.error(f"API error: {str(e)}")
        raise Exception(f"Claude API error: {str(e)}")
    except Exception as e:
        logger.error(f"LLM call failed: {str(e)}")
        raise Exception(f"Unexpected error calling Claude: {str(e)}")


def execute_tool_safely(name: str, tool: callable, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safely execute a tool with proper parameter validation and error handling.
    :param name: Tool name for error reporting
    :param tool: Tool function to execute
    :param args: Arguments dictionary from JSON
    :return: Tool execution result
    """
    try:
        # Get function signature for parameter validation
        sig = inspect.signature(tool)
        
        # Map arguments to function parameters
        bound_args = {}
        for param_name, param in sig.parameters.items():
            if param_name in args:
                bound_args[param_name] = args[param_name]
            elif param.default is not inspect.Parameter.empty:
                # Use default value
                bound_args[param_name] = param.default
            else:
                # Required parameter missing
                logger.warning(f"Missing required parameter '{param_name}' for tool '{name}'")
                # Try to provide reasonable defaults based on type hints
                if param.annotation == str:
                    bound_args[param_name] = ""
                elif param.annotation == List[str]:
                    bound_args[param_name] = []
                elif param.annotation == bool:
                    bound_args[param_name] = False
                elif param.annotation == int:
                    bound_args[param_name] = 0
                else:
                    bound_args[param_name] = None
        
        # Execute the tool with validated parameters
        return tool(**bound_args)
        
    except TypeError as e:
        logger.error(f"Parameter validation failed for tool '{name}': {str(e)}")
        return {"error": f"Invalid parameters for {name}: {str(e)}", "success": False}
    except Exception as e:
        logger.error(f"Tool execution error for '{name}': {str(e)}")
        return {"error": f"Tool execution failed: {str(e)}", "success": False}


def run_coding_agent_loop():
    if DEBUG_MODE:
        print("=== ntCode AI Assistant ===\n")
        print("Available tools:", ", ".join(TOOL_REGISTRY.keys()))
        print(f"Debug Mode: {DEBUG_MODE}, Verbose Mode: {VERBOSE_MODE}")
        print(f"Logging: {LOG_CONVERSATIONS}\n")
    else:
        print("ntCode AI Assistant - Ready!\n")
    
    conversation = [{"role": "system", "content": get_full_system_prompt()}]

    while True:
        try:
            user_input = input(f"{YOU_COLOR}You:{RESET_COLOR}:")
        except (KeyboardInterrupt, EOFError):
            break
        conversation.append({"role": "user", "content": user_input.strip()})
        while True:
            try:
                assistant_response = execute_llm_call(conversation)
                tool_invocations = extract_tool_invocations(assistant_response)
                
                if DEBUG_MODE:
                    print(f"Assistant Response:\n {assistant_response}\n")
                    print(f"tool invocations:\n {tool_invocations}\n")
                
                if VERBOSE_MODE and tool_invocations:
                    print(f"\nFound {len(tool_invocations)} tool invocation(s): {[name for name, _ in tool_invocations]}")
                    confirm = input("Execute these tools? (y/N): ").lower().strip()
                    if confirm not in ['y', 'yes']:
                        print("Tool execution cancelled by user.")
                        conversation.append({"role": "assistant", "content": assistant_response})
                        break
                
                if not tool_invocations:
                    print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {assistant_response}")
                    conversation.append({"role": "assistant", "content": assistant_response})
                    break
                
                # Execute tools with improved error handling
                for name, args in tool_invocations:
                    if name not in TOOL_REGISTRY:
                        logger.error(f"Unknown tool: {name}")
                        continue
                        
                    tool = TOOL_REGISTRY[name]
                    try:
                        if DEBUG_MODE:
                            print(f"Executing tool: {name} with args: {args}")
                        
                        # Execute tool with dynamic parameter mapping
                        resp = execute_tool_safely(name, tool, args)
                        
                        if DEBUG_MODE:
                            print(f"Tool result: {resp}")
                        
                        # Add tool result to conversation
                        conversation.append({
                            "role": "user", 
                            "content": f"tool_result({json.dumps(resp, ensure_ascii=False)})"
                        })
                        
                    except Exception as e:
                        logger.error(f"Tool execution failed for {name}: {str(e)}")
                        error_result = {
                            "error": f"Tool execution failed: {str(e)}",
                            "tool_name": name,
                            "success": False
                        }
                        conversation.append({
                            "role": "user", 
                            "content": f"tool_result({json.dumps(error_result)})"
                        })
                        
            except Exception as e:
                logger.error(f"Assistant loop error: {str(e)}")
                print(f"{ASSISTANT_COLOR}Error:{RESET_COLOR} {str(e)}")
                print("Please try again with a shorter or simpler request.")
                break
                #                print(conversation)


if __name__ == "__main__":
    run_coding_agent_loop()
