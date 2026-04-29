from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any, Dict, List

from utils.config import logger
from utils.security import resolve_abs_path, validate_file_access

# All memories live under this directory (relative to cwd / sandbox root).
_MEMORY_DIR = Path("storage/memory")

# Key names must be safe for use as part of a filename.
_VALID_KEY = re.compile(r"^[a-zA-Z0-9_\-]{1,80}$")


def _memory_dir() -> Path:
    """Return the resolved, validated memory directory, creating it if needed."""
    d = resolve_abs_path(str(_MEMORY_DIR))
    validate_file_access(d.parent)  # validate parent (storage/) is in sandbox
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_store_tool(
    key: str,
    content: str,
    tags: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Store a memory or note to persistent storage.

    Writes *content* as a Markdown file under storage/memory/.  Files survive
    across sessions and can be retrieved with memory_search or memory_list.
    The LLM should call this whenever it learns something durable about the
    project or user (preferences, conventions, recurring tasks, decisions).

    :param key: Short identifier for this memory (alphanumeric, hyphens,
                underscores; max 80 chars).  Used as part of the filename.
    :param content: The memory content to store (plain text or Markdown).
    :param tags: Optional list of tag strings for later filtering.
    :return: Dict with the path of the stored file and metadata.
    """
    if not key or not _VALID_KEY.match(key):
        return {
            "error": (
                "key must be 1-80 characters, alphanumeric with hyphens/underscores only"
            )
        }

    if not content or not content.strip():
        return {"error": "content must not be empty"}

    tags = [str(t).strip() for t in (tags or []) if str(t).strip()]

    try:
        mem_dir = _memory_dir()
    except PermissionError as exc:
        return {"error": str(exc)}

    timestamp = datetime.datetime.now()
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
    filename = mem_dir / f"{key}_{ts_str}.md"

    tag_line = ", ".join(tags) if tags else ""
    body = (
        f"---\n"
        f"timestamp: {timestamp.isoformat()}\n"
        f"tags: [{tag_line}]\n"
        f"key: {key}\n"
        f"---\n"
        f"{content.strip()}\n"
    )

    try:
        filename.write_text(body, encoding="utf-8")
    except OSError as exc:
        logger.error("memory_store_tool: failed to write %s: %s", filename, exc)
        return {"error": f"Failed to write memory file: {exc}"}

    logger.info("memory_store_tool: stored key=%r at %s", key, filename)
    return {
        "stored": str(filename),
        "key": key,
        "tags": tags,
        "timestamp": timestamp.isoformat(),
    }
