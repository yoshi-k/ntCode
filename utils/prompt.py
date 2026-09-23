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
3. Replace the ``{{TOOLS}}`` placeholder with tool descriptions formatted for
   the **active provider and model**.  The format is selected by
   :func:`utils.tool_format.format_tools_for_provider`:

   * ``auto``      — infer the format from the active model name.
   * ``ntcode``    — original ``tool: NAME({...})`` protocol (Claude, GPT-*).
   * ``xml``       — ``<tool_call>`` blocks (Qwen2.5-Instruct, Qwen3).
   * ``json_block``— fenced JSON blocks (Mistral, Mixtral).
   * ``gemma``     — ``<|tool_call>...<tool_call|>`` blocks (Gemma).

Set ``CALLING_CONVENTION`` / ``NTCODE_CALLING_CONVENTION`` to override auto
routing explicitly.

With a native-tool-use provider (Claude through providers.anthropic) the
tools travel in the API request instead, and ``{{TOOLS}}`` is replaced by a
short note (:data:`NATIVE_TOOLS_NOTE`) rather than text-protocol
instructions, which would contradict the native interface.

The result is cached after the first call so that repeated calls (e.g. from
the ``/prompt`` command and the agent startup) are cheap and always return
the same string within a single process run.

To force a reload (e.g. in tests) call :func:`invalidate_cache`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from utils.config import logger, BASE_DIR
from utils import config as cfg_module

# Matches {{FILE:some/relative/path.md}}
_FILE_DIRECTIVE_RE = re.compile(r"\{\{FILE:([^}]+)\}\}")

# Module-level cache so we only build the prompt once per process; keyed by
# whether tools are native, since that changes the {{TOOLS}} block.
_cache: dict[bool, str] = {}

NATIVE_TOOLS_NOTE = (
    "## Tools\n\n"
    "Your tools are provided through native tool calling. Call them directly "
    "whenever they help; each result is returned to you before you continue."
)


def invalidate_cache() -> None:
    """Clear the cached prompt so the next call to :func:`build_system_prompt`
    re-reads all files from disk.  Useful in tests."""
    _cache.clear()


# Sentinel that stands in for literal '{{TOOLS}}' text found inside inlined
# files.  It is restored to '{{TOOLS}}' after the single legitimate injection
# has been done, so the model sees the original documentation text unchanged.
# The NUL bytes make accidental collision with real file content impossible.
_TOOLS_SENTINEL = "\x00TOOLS_PLACEHOLDER\x00"


def _resolve_file_directives(text: str, base: Path) -> str:
    """Replace every ``{{FILE:path}}`` in *text* with the content of that file.

    Paths are resolved relative to *base* (the repo root).  If a file cannot
    be read a warning is logged and a comment placeholder is left in the
    prompt so the problem is visible to the model.

    Any literal ``{{TOOLS}}`` strings found *inside* the inlined file are
    replaced with an internal sentinel so that the subsequent
    :func:`_inject_tools` step does not expand them — only the single
    ``{{TOOLS}}`` that appears directly in the stub file should be expanded.
    """
    def _replace(match: re.Match) -> str:
        rel = match.group(1).strip()
        target = (base / rel).resolve()
        try:
            content = target.read_text(encoding="utf-8")
            logger.debug("prompt: inlined %s (%d chars)", rel, len(content))
        except FileNotFoundError:
            logger.warning("prompt: {{FILE:%s}} not found — skipping", rel)
            return f"<!-- FILE NOT FOUND: {rel} -->"
        except OSError as exc:
            logger.warning("prompt: cannot read %s: %s", rel, exc)
            return f"<!-- COULD NOT READ: {rel}: {exc} -->"
        # Neutralise any {{TOOLS}} strings that appear literally in the inlined
        # file (e.g. documentation about this very placeholder) so they are not
        # treated as injection targets.
        return content.replace("{{TOOLS}}", _TOOLS_SENTINEL)

    return _FILE_DIRECTIVE_RE.sub(_replace, text)


def _build_tool_block(allowed_tools: list[str] | None = None) -> str:
    """Return the formatted tool-description block for the ``{{TOOLS}}`` placeholder.

    Delegates to :func:`utils.tool_format.format_tools_for_provider` so that
    the tool syntax in the system prompt matches what the active model expects.
    The provider and model are read from ``utils.config`` at call time so they
    reflect any runtime provider switch.

    Args:
        allowed_tools: If provided, only include these tool names in the prompt.
                       An empty list or None means all tools.
    """
    # Import here to avoid circular imports at module level.
    from tools.registry import TOOL_REGISTRY
    from utils.tool_format import format_tools_for_provider
    import os

    # Filter the tool registry if a role is active with restrictions
    if allowed_tools:
        filtered_registry = {
            name: fn for name, fn in TOOL_REGISTRY.items()
            if name in allowed_tools
        }
    else:
        filtered_registry = TOOL_REGISTRY

    # Determine the active model name.
    # Claude uses NTCODE_MODEL / DEFAULT_MODEL; OpenAILLM uses OPENAI_MODEL.
    if cfg_module.LLM_PROVIDER == "openai":
        model = cfg_module.OPENAI_MODEL
    else:
        model = os.environ.get("NTCODE_MODEL", cfg_module.DEFAULT_MODEL)

    return format_tools_for_provider(cfg_module.LLM_PROVIDER, model, filtered_registry)


def native_tools_active() -> bool:
    """True when the configured provider takes tools through its API."""
    if cfg_module.LLM_PROVIDER == "anthropic":
        return True
    from utils.tool_format import openai_tool_mode

    return openai_tool_mode() == "native"


def build_system_prompt(
    allowed_tools: list[str] | None = None,
    native_tools: bool | None = None,
) -> str:
    """Load, resolve, and return the complete system prompt.

    The result is cached *only* when no role-level tool filter is in effect.
    When a role restricts tools the prompt is rebuilt each time (the cache
    is bypassed) so that tool additions/removals are reflected immediately.

    Args:
        allowed_tools: If provided, only include these tool names in the
                       ``{{TOOLS}}`` section.  Empty list or None means all tools.
        native_tools:  True when the provider receives tools through its API;
                       ``{{TOOLS}}`` then becomes :data:`NATIVE_TOOLS_NOTE`.
                       None (default) derives it from ``LLM_PROVIDER``.

    Raises
    ------
    FileNotFoundError
        If the stub file named by ``SYSTEM_PROMPT_FILE`` does not exist.
    """
    if native_tools is None:
        native_tools = native_tools_active()

    # Only use cache when no role-level filter is active.
    if not allowed_tools and native_tools in _cache:
        return _cache[native_tools]

    stub_path = (BASE_DIR / cfg_module.SYSTEM_PROMPT_FILE).resolve()
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

    # Step 2: inject tool descriptions at the one {{TOOLS}} in the stub.
    tool_block = NATIVE_TOOLS_NOTE if native_tools else _build_tool_block(allowed_tools)
    if "{{TOOLS}}" in resolved:
        resolved = resolved.replace("{{TOOLS}}", tool_block, 1)
    else:
        logger.warning(
            "prompt: stub contains no {{TOOLS}} placeholder — tool descriptions not injected"
        )
    resolved = resolved.replace(_TOOLS_SENTINEL, "{{TOOLS}}")

    # Only cache the unfiltered prompt (no active role)
    if not allowed_tools:
        _cache[native_tools] = resolved
    logger.info("prompt: built (%d chars)", len(resolved))
    return resolved
