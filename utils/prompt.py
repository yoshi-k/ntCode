"""System-prompt builder for ntCode.

This module is the single source of truth for the system prompt that is sent
to the LLM on every request and displayed by the ``/prompt`` command.

How it works
------------
1. Load the stub file named by ``SYSTEM_PROMPT_FILE`` (default:
   ``system_prompt.md`` at the repo root).
2. Resolve every ``{{FILE:relative/path}}`` directive by reading the named
   file and inlining its content.  Missing files produce a warning comment
   rather than crashing.
3. Replace the ``{{TOOLS}}`` placeholder with the formatted descriptions of
   every tool currently registered in ``TOOL_REGISTRY``.

The result is cached after the first call so that repeated calls (e.g. from
the ``/prompt`` command and the agent startup) are cheap and always return
the same string within a single process run.

To force a reload (e.g. in tests) call :func:`invalidate_cache`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from utils.config import logger, BASE_DIR, SYSTEM_PROMPT_FILE

# Matches {{FILE:some/relative/path.md}}
_FILE_DIRECTIVE_RE = re.compile(r"\{\{FILE:([^}]+)\}\}")

# Module-level cache so we only build the prompt once per process.
_cache: Optional[str] = None


def invalidate_cache() -> None:
    """Clear the cached prompt so the next call to :func:`build_system_prompt`
    re-reads all files from disk.  Useful in tests."""
    global _cache
    _cache = None


def _resolve_file_directives(text: str, base: Path) -> str:
    """Replace every ``{{FILE:path}}`` in *text* with the content of that file.

    Paths are resolved relative to *base* (the repo root).  If a file cannot
    be read a warning is logged and a comment placeholder is left in the
    prompt so the problem is visible to the model.
    """
    def _replace(match: re.Match) -> str:
        rel = match.group(1).strip()
        target = (base / rel).resolve()
        try:
            content = target.read_text(encoding="utf-8")
            logger.debug("prompt: inlined %s (%d chars)", rel, len(content))
            return content
        except FileNotFoundError:
            logger.warning("prompt: {{FILE:%s}} not found — skipping", rel)
            return f"<!-- FILE NOT FOUND: {rel} -->"
        except OSError as exc:
            logger.warning("prompt: cannot read %s: %s", rel, exc)
            return f"<!-- COULD NOT READ: {rel}: {exc} -->"

    return _FILE_DIRECTIVE_RE.sub(_replace, text)


def _build_tool_block() -> str:
    """Return the formatted tool-description block for the ``{{TOOLS}}`` placeholder."""
    # Import here to avoid a circular import at module level
    # (registry imports config; prompt imports registry only at call time).
    from tools.registry import TOOL_REGISTRY, get_tool_str_representation

    parts: list[str] = []
    for name in TOOL_REGISTRY:
        parts.append("TOOL\n===\n" + get_tool_str_representation(name))
        parts.append("=" * 15)
    return "\n".join(parts)


def build_system_prompt() -> str:
    """Load, resolve, and return the complete system prompt.

    The result is cached; call :func:`invalidate_cache` to force a rebuild.

    Raises
    ------
    FileNotFoundError
        If the stub file named by ``SYSTEM_PROMPT_FILE`` does not exist.
    """
    global _cache
    if _cache is not None:
        return _cache

    stub_path = (BASE_DIR / SYSTEM_PROMPT_FILE).resolve()
    logger.info("prompt: loading stub from %s", stub_path)

    try:
        stub = stub_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"System prompt stub not found: {stub_path}\n"
            f"Set NTCODE_SYSTEM_PROMPT_FILE to point at your stub, or create {stub_path}."
        )

    # Step 1: inline {{FILE:...}} directives
    resolved = _resolve_file_directives(stub, BASE_DIR)

    # Step 2: inject tool descriptions
    tool_block = _build_tool_block()
    if "{{TOOLS}}" in resolved:
        resolved = resolved.replace("{{TOOLS}}", tool_block)
    else:
        logger.warning(
            "prompt: stub contains no {{TOOLS}} placeholder — tool descriptions not injected"
        )

    _cache = resolved
    logger.info("prompt: built (%d chars)", len(_cache))
    return _cache
