from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from utils.config import logger
from utils.security import resolve_abs_path, validate_file_access

# Hard cap on matches returned to avoid flooding the context window.
_MAX_MATCHES = 200
# Maximum characters shown around a match (one line).
_SNIPPET_MAX = 200


def search_codebase_tool(
    query: str,
    path: str = ".",
    glob: str = "**/*",
    case_sensitive: bool = False,
    max_results: int = 40,
) -> Dict[str, Any]:
    """
    Search file contents for a keyword or regex pattern.

    Walks the directory tree rooted at *path*, reads every file that matches
    *glob*, and returns lines that contain *query*.  Binary files and files
    that cannot be decoded as UTF-8 / latin-1 are silently skipped.

    :param query: Search string or regex pattern (case-insensitive by default).
    :param path: Root directory to search (default: current directory).
    :param glob: File glob pattern (default: all files).  Examples:
                 ``**/*.py``, ``**/*.md``, ``tools/*.py``.
    :param case_sensitive: Set True to make the match case-sensitive.
    :param max_results: Maximum number of matching lines to return (max 200).
    :return: Dict with 'matches' list and summary metadata.
    """
    if not query or not query.strip():
        return {"error": "query must not be empty"}

    max_results = max(1, min(int(max_results), _MAX_MATCHES))

    try:
        root = resolve_abs_path(path)
        validate_file_access(root)
    except PermissionError as exc:
        return {"error": str(exc)}

    if not root.is_dir():
        return {"error": f"Path is not a directory: {path}"}

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags)
    except re.error as exc:
        return {"error": f"Invalid regex pattern: {exc}"}

    matches: List[Dict[str, Any]] = []
    files_searched = 0
    files_skipped = 0
    truncated = False

    for file_path in sorted(root.rglob(glob)):
        if not file_path.is_file():
            continue

        # Skip files outside the sandbox.
        try:
            validate_file_access(file_path)
        except PermissionError:
            files_skipped += 1
            continue

        # Try to read as text; skip binary files.
        text: str | None = None
        for encoding in ("utf-8", "latin-1"):
            try:
                text = file_path.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, OSError):
                continue

        if text is None:
            files_skipped += 1
            continue

        files_searched += 1

        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                # Trim very long lines so the context window isn't flooded.
                snippet = line.strip()
                if len(snippet) > _SNIPPET_MAX:
                    snippet = snippet[:_SNIPPET_MAX] + "…"

                # Store a path relative to the search root for readability.
                try:
                    rel = str(file_path.relative_to(root))
                except ValueError:
                    rel = str(file_path)

                matches.append(
                    {"file": rel, "line": lineno, "text": snippet}
                )

                if len(matches) >= max_results:
                    truncated = True
                    break

            if truncated:
                break

        if truncated:
            break

    logger.info(
        "search_codebase_tool: query=%r files_searched=%d matches=%d truncated=%s",
        query,
        files_searched,
        len(matches),
        truncated,
    )

    return {
        "query": query,
        "path": str(root),
        "glob": glob,
        "files_searched": files_searched,
        "files_skipped": files_skipped,
        "match_count": len(matches),
        "truncated": truncated,
        "matches": matches,
    }
