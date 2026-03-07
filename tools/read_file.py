from typing import Any, Dict

from utils.config import MAX_FILE_SIZE
from utils.security import resolve_abs_path, validate_file_access


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
            except Exception:
                return {
                    "error": f"Unable to read file as text: {filename}",
                    "file_path": str(full_path),
                }

        return {"file_path": str(full_path), "content": content}

    except PermissionError as e:
        return {"error": f"Access denied: {str(e)}", "file_path": filename}
    except Exception as e:
        return {"error": f"Error reading file: {str(e)}", "file_path": filename}
