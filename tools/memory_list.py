from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from utils.config import logger
from utils.security import resolve_abs_path, validate_file_access

_MEMORY_DIR = Path("storage/memory")
_MAX_LIST = 50


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a memory file into its YAML-ish frontmatter dict and body."""
    meta: dict[str, str] = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()

    return meta, body


def memory_list_tool(
    tag: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    """
    List stored memories with optional tag filtering.

    Returns a summary of each memory (key, timestamp, tags, and the first
    line of the body).  Use memory_search to retrieve full content once you
    know which memory you need.

    Call this at the start of a new task to orient yourself with previously
    stored context.

    :param tag: If non-empty, only list memories that carry this tag.
    :param limit: Maximum number of entries to return (max 50).
    :return: Dict with 'memories' list sorted newest-first.
    """
    limit = max(1, min(int(limit), _MAX_LIST))
    filter_tag = tag.strip().lower()

    mem_root = resolve_abs_path(str(_MEMORY_DIR))
    if not mem_root.exists():
        return {"total": 0, "memories": [], "tag_filter": filter_tag or None}

    try:
        validate_file_access(mem_root)
    except PermissionError as exc:
        return {"error": str(exc)}

    entries: List[Dict[str, Any]] = []

    # Sort by modification time so newest appear first.
    candidates = sorted(
        mem_root.glob("*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    for mem_file in candidates:
        if len(entries) >= limit:
            break

        try:
            validate_file_access(mem_file)
            text = mem_file.read_text(encoding="utf-8")
        except (PermissionError, OSError):
            continue

        meta, body = _parse_frontmatter(text)

        # Tag filtering.
        if filter_tag:
            file_tags_raw = meta.get("tags", "")
            file_tags = {t.strip().lower() for t in re.split(r"[\[\],]", file_tags_raw) if t.strip()}
            if filter_tag not in file_tags:
                continue

        # First non-empty line of the body as a summary.
        summary = next((ln.strip() for ln in body.splitlines() if ln.strip()), "(empty)")
        if len(summary) > 120:
            summary = summary[:120] + "…"

        entries.append(
            {
                "file": mem_file.name,
                "key": meta.get("key", mem_file.stem),
                "timestamp": meta.get("timestamp", ""),
                "tags": meta.get("tags", ""),
                "summary": summary,
            }
        )

    logger.info(
        "memory_list_tool: tag_filter=%r returned=%d", filter_tag or None, len(entries)
    )

    return {
        "tag_filter": filter_tag or None,
        "total": len(entries),
        "memories": entries,
    }
