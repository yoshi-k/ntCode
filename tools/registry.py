import inspect
from typing import Any, Callable, Dict, List

from utils.config import logger
from tools.read_file import read_file_tool
from tools.list_files import list_files_tool
from tools.edit_file import edit_file_tool
from tools.git_add import git_add_tool
from tools.git_commit import git_commit_tool
from tools.git_status import git_status_tool
from tools.git_diff import git_diff_tool
from tools.git_log import git_log_tool
from tools.search_web import search_web_tool
from tools.read_web import read_web_tool
from tools.search_codebase import search_codebase_tool
from tools.memory_store import memory_store_tool
from tools.memory_search import memory_search_tool
from tools.memory_list import memory_list_tool

TOOL_REGISTRY: Dict[str, Callable] = {
    "read_file": read_file_tool,
    "list_files": list_files_tool,
    "edit_file": edit_file_tool,
    "git_add": git_add_tool,
    "git_commit": git_commit_tool,
    "git_status": git_status_tool,
    "git_diff": git_diff_tool,
    "git_log": git_log_tool,
    "search_web": search_web_tool,
    "read_web": read_web_tool,
    "search_codebase": search_codebase_tool,
    "memory_store": memory_store_tool,
    "memory_search": memory_search_tool,
    "memory_list": memory_list_tool,
}


def register_tool(name: str, fn: Callable) -> None:
    """Dynamically register a new tool under *name*."""
    TOOL_REGISTRY[name] = fn


def get_tool_str_representation(tool_name: str) -> str:
    """Return a human-readable description of one registered tool.

    Used by the ``/tools`` command and by tests.  The format is the
    original ntCode text-protocol layout (name / description / signature).
    The system-prompt tool block is built by
    :func:`utils.tool_format.format_tools_for_provider` which selects the
    appropriate format for the active provider/model.
    """
    tool = TOOL_REGISTRY[tool_name]
    return f"""
    Name: {tool_name}
    Description: {tool.__doc__}
    Signature: {inspect.signature(tool)}
    """


def get_full_system_prompt(allowed_tools: list[str] | None = None) -> str:
    """Return the complete system prompt.

    Delegates to :func:`utils.prompt.build_system_prompt`, which loads the
    stub file, resolves ``{{FILE:...}}`` directives, and injects tool
    descriptions into the ``{{TOOLS}}`` placeholder.  The result is cached
    so repeated calls are cheap.

    Args:
        allowed_tools: If provided, only include these tool names in the
                       ``{{TOOLS}}`` section.  Empty list or None means all tools.
    """
    from utils.prompt import build_system_prompt

    return build_system_prompt(allowed_tools=allowed_tools)


def execute_tool_safely(
    name: str, tool: Callable, args: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Safely execute a tool with proper parameter validation and error handling.

    Before dispatching the tool, checks the active role's tool allowlist (if
    any role is loaded).  Returns a descriptive error dict — rather than raising
    — so the LLM receives the message and can respond gracefully.

    :param name: Tool name for error reporting
    :param tool: Tool function to execute
    :param args: Arguments dictionary from JSON
    :return: Tool execution result
    """
    # --- Role-based access control ---
    try:
        from utils.roles import is_tool_allowed, get_active_role
        if not is_tool_allowed(name):
            active = get_active_role()
            role_name = active.name if active else "unknown"
            allowed = ", ".join(active.tools) if active and active.tools else "none"
            logger.warning(
                "roles: tool '%s' blocked by active role '%s'", name, role_name
            )
            return {
                "error": (
                    f"Tool '{name}' is not available in the current role "
                    f"('{role_name}').  Permitted tools: {allowed}."
                ),
                "success": False,
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("roles: access-control check failed (%s); proceeding", exc)

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
                logger.warning(
                    f"Missing required parameter '{param_name}' for tool '{name}'"
                )
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
