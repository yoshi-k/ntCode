from typing import Any, Dict

from utils.security import resolve_abs_path, validate_file_access


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
