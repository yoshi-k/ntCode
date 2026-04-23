from typing import Any, Dict

from utils.config import MAX_FILE_SIZE
from utils.security import resolve_abs_path, validate_file_access


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
            # Creating/overwriting file — ensure parent directories exist
            full_path.parent.mkdir(parents=True, exist_ok=True)
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
