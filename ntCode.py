#!/usr/bin/python

# Implementation of The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code
# https://www.mihaileric.com/The-Emperor-Has-No-Clothes/
# by Joerg Kulbartz joerg@kulbartz.de

import inspect
import json
import os

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
        if not any(resolved_path.is_relative_to(base.resolve()) 
                  for base in ALLOWED_BASE_PATHS):
            raise PermissionError(f"Access denied: Path outside allowed directories: {path}")
        
        # Additional security checks
        if '..' in str(path):  # Prevent path traversal attempts
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
            return {"error": f"Path is not a file: {filename}", "file_path": str(full_path)}
        
        # Check file size before reading
        if full_path.stat().st_size > MAX_FILE_SIZE:
            return {"error": f"File too large (max {MAX_FILE_SIZE} bytes): {filename}", "file_path": str(full_path)}
        
        # Read file with proper encoding handling
        try:
            content = full_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            # Try with different encoding for binary files
            try:
                content = full_path.read_text(encoding='latin-1')
            except:
                return {"error": f"Unable to read file as text: {filename}", "file_path": str(full_path)}
        
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
            return {"error": f"File too large: {full_path} (max {MAX_FILE_SIZE // 1024 // 1024}MB)", "path": str(full_path)}
            
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
            name, rest = after.split("(", 1)
            name = name.strip()
            if not rest.endswith(")"):
                continue
            json_str = rest[:-1].strip()
            args = json.loads(json_str)
            invocations.append((name, args))
        except Exception:
            continue
    return invocations


def execute_llm_call(conversation: List[Dict[str, str]]):
    system_content = ""
    messages = []
    for msg in conversation:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            messages.append(msg)

    response = claude_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=system_content,
        messages=messages,
    )

    return response.content[0].text


def run_coding_agent_loop():
    print(get_full_system_prompt())
    conversation = [{"role": "system", "content": get_full_system_prompt()}]

    while True:
        try:
            user_input = input(f"{YOU_COLOR}You:{RESET_COLOR}:")
        except (KeyboardInterrupt, EOFError):
            break
        conversation.append({"role": "user", "content": user_input.strip()})
        while True:
            assistant_response = execute_llm_call(conversation)
            tool_invocations = extract_tool_invocations(assistant_response)
            print(f"Assistant Response:\n {assistant_response}\n")
            print(f"tool invocations:\n {tool_invocations}\n")
            input("Wait")
            if not tool_invocations:
                print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR}: {assistant_response}")
                conversation.append(
                    {"role": "assistant", "content": assistant_response}
                )
                break
            for name, args in tool_invocations:
                tool = TOOL_REGISTRY[name]
                resp = ""
                print(name, args)
                if name == "read_file":
                    resp = tool(args.get("filename", "."))
                elif name == "list_files":
                    resp = tool(args.get("path", "."))
                elif name == "edit_file":
                    resp = tool(
                        args.get("path", "."),
                        args.get("old_str", ""),
                        args.get("new_str", ""),
                    )
                conversation.append(
                    {"role": "user", "content": f"tool_result({json.dumps(resp)})"}
                )
                #                print(conversation)


if __name__ == "__main__":
    run_coding_agent_loop()
