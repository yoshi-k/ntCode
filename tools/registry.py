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


TOOL_REGISTRY: Dict[str, Callable] = {
    "read_file": read_file_tool,
    "list_files": list_files_tool,
    "edit_file": edit_file_tool,
    "git_add": git_add_tool,
    "git_commit": git_commit_tool,
    "git_status": git_status_tool,
    "git_diff": git_diff_tool,
    "git_log": git_log_tool,
}


def register_tool(name: str, fn: Callable) -> None:
    """Dynamically register a new tool under *name*."""
    TOOL_REGISTRY[name] = fn


def get_tool_str_representation(tool_name: str) -> str:
    tool = TOOL_REGISTRY[tool_name]
    return f"""
    Name: {tool_name}
    Description: {tool.__doc__}
    Signature: {inspect.signature(tool)}
    """


def get_full_system_prompt() -> str:
    """Return the complete system prompt.

    Delegates to :func:`utils.prompt.build_system_prompt`, which loads the
    stub file, resolves ``{{FILE:...}}`` directives, and injects tool
    descriptions into the ``{{TOOLS}}`` placeholder.  The result is cached
    so repeated calls are cheap.
    """
    from utils.prompt import build_system_prompt
    return build_system_prompt()


def execute_tool_safely(
    name: str, tool: Callable, args: Dict[str, Any]
) -> Dict[str, Any]:
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
