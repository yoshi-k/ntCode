import shutil
import datetime
from pathlib import Path
from typing import Any, Dict
import os
from utils.config import MAX_FILE_SIZE
from utils.security import resolve_abs_path, validate_file_access

# Directory to store file backups
BACKUP_DIR = Path("backups")


def _create_backup(full_path: Path) -> str:
    """Creates a timestamped backup of the file at full_path."""
    if not full_path.exists():
        return ""

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    # Sanitize path to create a flat filename for the backup
    # e.g., src/main.py -> src_main.py_2023...
    relative_part = full_path.relative_to(full_path.anchor)
    safe_name = str(relative_part).replace(os.sep, "_").replace(":", "")
    backup_filename = f"{safe_name}_{timestamp}.bak"
    backup_path = BACKUP_DIR / backup_filename

    shutil.copy2(full_path, backup_path)
    return str(backup_path)


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

        backup_path = ""
        if full_path.exists():
            backup_path = _create_backup(full_path)

        if old_str == "":
            # Creating/overwriting file — ensure parent directories exist
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_str, encoding="utf-8")
            return {
                "path": str(full_path),
                "action": "created_file",
                "backup": backup_path,
            }

        # Check file size before reading (for editing existing files)
        if full_path.stat().st_size > MAX_FILE_SIZE:
            return {
                "error": f"File too large: {full_path} (max {MAX_FILE_SIZE // 1024 // 1024}MB)",
                "path": str(full_path),
            }

        original = full_path.read_text(encoding="utf-8")
        if original.find(old_str) == -1:
            return {
                "path": str(full_path),
                "action": "old_str not found",
                "backup": backup_path,
            }

        edited = original.replace(old_str, new_str, 1)
        full_path.write_text(edited, encoding="utf-8")
        return {"path": str(full_path), "action": "edited", "backup": backup_path}

    except PermissionError as e:
        return {"error": f"Access denied: {e}", "path": path}
    except FileNotFoundError:
        return {"error": f"File not found: {path}", "path": path}
    except Exception as e:
        return {"error": f"Error editing file: {e}", "path": path}
