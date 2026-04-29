from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from utils.config import logger
from utils.security import resolve_abs_path, validate_file_access

_MEMORY_DIR = Path("storage/memory")
_SNIPPET_CONTEXT = 2   # lines of context around each match
_MAX_RESULTS = 20


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


def _snippet(lines: List[str], match_idx: int, context: int = _SNIPPET_CONTEXT) -> str:
    """Return a few lines around *match_idx* as a single string."""
    start = max(0, match_idx - context)
    end = min(len(lines), match_idx + context + 1)
    return "\n".join(lines[start:end]).strip()


def memory_search_tool(
    query: str,
    tags: List[str] | None = None,
    max_results: int = 10,
) -> Dict[str, Any]:
    """
    Search stored memories by keyword.

    Scans all files under storage/memory/ for lines that contain *query*
    (case-insensitive).  Optionally filters to memories that carry at least
    one of the requested *tags*.  Returns matching memories with a content
    snippet around each match.

    :param query: Keyword or regex to search for.
    :param tags: If provided, only search memories tagged with one of these.
    :param max_results: Maximum number of results to return (max 20).
    :return: Dict with 'results' list and summary metadata.
    """
    if not query or not query.strip():
        return {"error": "query must not be empty"}

    max_results = max(1, min(int(max_results), _MAX_RESULTS))
    filter_tags = {t.strip().lower() for t in (tags or []) if t.strip()}

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error as exc:
        return {"error": f"Invalid regex pattern: {exc}"}

    mem_root = resolve_abs_path(str(_MEMORY_DIR))
    if not mem_root.exists():
        return {"query": query, "result_count": 0, "results": []}

    try:
        validate_file_access(mem_root)
    except PermissionError as exc:
        return {"error": str(exc)}

    results: List[Dict[str, Any]] = []

    for mem_file in sorted(mem_root.glob("*.md"), reverse=True):  # newest first
        if len(results) >= max_results:
            break

        try:
            validate_file_access(mem_file)
            text = mem_file.read_text(encoding="utf-8")
        except (PermissionError, OSError):
            continue

        meta, body = _parse_frontmatter(text)

        # Tag filtering — check if any requested tag appears in the file's tags.
        if filter_tags:
            file_tags_raw = meta.get("tags", "")
            file_tags = {t.strip().lower() for t in re.split(r"[\[\],]", file_tags_raw) if t.strip()}
            if not filter_tags.intersection(file_tags):
                continue

        # Search frontmatter values + body.
        searchable = text
        lines = body.splitlines()

        matched_snippets: List[str] = []
        for idx, line in enumerate(lines):
            if pattern.search(line):
                matched_snippets.append(_snippet(lines, idx))
                break  # one snippet per file is enough

        # Also match on key/tags in frontmatter even if body has no hit.
        if not matched_snippets and pattern.search(meta.get("key", "") + " " + meta.get("tags", "")):
            matched_snippets.append(body[:300].strip() if body else "(no body)")

        if not matched_snippets:
            continue

        results.append(
            {
                "file": mem_file.name,
                "key": meta.get("key", mem_file.stem),
                "timestamp": meta.get("timestamp", ""),
                "tags": meta.get("tags", ""),
                "snippet": matched_snippets[0],
            }
        )

    logger.info(
        "memory_search_tool: query=%r found=%d", query, len(results)
    )

    return {
        "query": query,
        "filter_tags": list(filter_tags),
        "result_count": len(results),
        "results": results,
    }
