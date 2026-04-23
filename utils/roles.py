"""
utils/roles.py — Role loader, validator, and active-role state.

A *role* is a named configuration bundle stored as a TOML file under the
``roles/`` directory.  It can specify:

* ``[role]``          — name, description, optional system_prompt_file override
* ``tools``           — exhaustive allowlist of tool names (absent / empty = all tools)
* ``[config]``        — config-manager key/value overrides
* ``[rag]``           — RAG source definitions (placeholder; consumed by future RAG subsystem)

Public API
----------
load_role(name_or_path)  -> RoleDefinition   load + activate a role
unload_role()                                revert to defaults
list_roles()             -> list[str]        names of all available roles
get_active_role()        -> RoleDefinition | None
is_tool_allowed(name)    -> bool             honour the active tool allowlist

All state is held in module-level variables so it is shared across imports.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

logger = logging.getLogger("ntcode")

# ---------------------------------------------------------------------------
# Repo root — roles/ lives here
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.resolve()
_ROLES_DIR = _REPO_ROOT / "roles"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RagSource:
    """A single RAG knowledge-base entry (consumed by future RAG subsystem)."""
    type: str                        # e.g. "local_dir", "url", "vector_db"
    path: str = ""                   # local path (if applicable)
    url: str = ""                    # remote URL (if applicable)
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # forward-compat catch-all


@dataclass
class RoleDefinition:
    """Parsed, validated representation of one role TOML file."""
    name: str
    description: str = ""

    # System-prompt override.  None → use the default system_prompt.md.
    system_prompt_file: str | None = None

    # Tool allowlist.  Empty list → all tools allowed.
    tools: list[str] = field(default_factory=list)

    # Config key/value pairs to apply when the role is loaded.
    config_overrides: dict[str, str] = field(default_factory=dict)

    # RAG sources (placeholder for future use).
    rag_sources: list[RagSource] = field(default_factory=list)

    # Path to the TOML file this role was loaded from.
    source_path: str = ""

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    def allows_tool(self, tool_name: str) -> bool:
        """Return True if *tool_name* is usable in this role."""
        if not self.tools:          # empty list = all tools allowed
            return True
        return tool_name in self.tools

    def summary(self) -> str:
        """One-line human-readable summary."""
        tool_str = ", ".join(self.tools) if self.tools else "all"
        return (
            f"Role '{self.name}': {self.description}\n"
            f"  tools      : {tool_str}\n"
            f"  sys-prompt : {self.system_prompt_file or '(default)'}\n"
            f"  config     : {self.config_overrides or '(none)'}\n"
            f"  rag sources: {len(self.rag_sources)}"
        )


# ---------------------------------------------------------------------------
# Active-role state (module-level singleton)
# ---------------------------------------------------------------------------

_active_role: RoleDefinition | None = None
_saved_config_values: dict[str, Any] = {}   # values before role was loaded
_saved_prompt_file: str | None = None        # SYSTEM_PROMPT_FILE before load


def get_active_role() -> RoleDefinition | None:
    """Return the currently active role, or None if none is loaded."""
    return _active_role


def is_tool_allowed(tool_name: str) -> bool:
    """
    Return True if *tool_name* may be called in the current role context.

    If no role is active every tool is allowed.
    """
    if _active_role is None:
        return True
    return _active_role.allows_tool(tool_name)


# ---------------------------------------------------------------------------
# TOML parsing helpers
# ---------------------------------------------------------------------------

def _require_tomllib() -> None:
    if tomllib is None:
        raise ImportError(
            "Role files require a TOML parser. "
            "On Python < 3.11 install 'tomli': pip install tomli"
        )


def _parse_toml_file(path: Path) -> dict[str, Any]:
    _require_tomllib()
    with path.open("rb") as fh:
        return tomllib.load(fh)  # type: ignore[union-attr]


def _resolve_path(raw: str) -> str:
    """
    Resolve a path string from a TOML field.

    * Absolute paths are returned as-is.
    * Relative paths are resolved from the repository root.
    """
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str(_REPO_ROOT / p)


def _parse_role_dict(data: dict[str, Any], source_path: str = "") -> RoleDefinition:
    """
    Convert a raw parsed TOML dict into a :class:`RoleDefinition`.

    Raises ``ValueError`` on structural problems.
    """
    role_section = data.get("role", {})
    if not role_section:
        raise ValueError("TOML file is missing the required [role] section")

    name = role_section.get("name", "")
    if not name:
        raise ValueError("[role] section must contain a non-empty 'name' field")

    description = role_section.get("description", "")

    # system_prompt_file — optional
    raw_sp = role_section.get("system_prompt_file", None)
    system_prompt_file: str | None = None
    if raw_sp:
        resolved = _resolve_path(raw_sp)
        if not Path(resolved).exists():
            raise ValueError(
                f"system_prompt_file '{raw_sp}' not found (resolved to '{resolved}')"
            )
        system_prompt_file = resolved

    # tools — optional list of strings at the top level or under [role]
    tools_raw = data.get("tools", role_section.get("tools", []))
    if not isinstance(tools_raw, list):
        raise ValueError("'tools' must be a TOML array of strings")
    tools = [str(t) for t in tools_raw]

    # [config] — optional table of string overrides
    config_section = data.get("config", {})
    if not isinstance(config_section, dict):
        raise ValueError("[config] must be a TOML table")
    config_overrides = {k: str(v) for k, v in config_section.items()}

    # [rag] — optional, forward-compatible
    rag_section = data.get("rag", {})
    rag_sources: list[RagSource] = []
    if isinstance(rag_section, dict):
        raw_sources = rag_section.get("sources", [])
        if isinstance(raw_sources, list):
            for entry in raw_sources:
                if not isinstance(entry, dict):
                    continue
                src_type = entry.get("type", "unknown")
                rag_sources.append(RagSource(
                    type=src_type,
                    path=entry.get("path", ""),
                    url=entry.get("url", ""),
                    description=entry.get("description", ""),
                    extra={k: v for k, v in entry.items()
                           if k not in ("type", "path", "url", "description")},
                ))

    return RoleDefinition(
        name=name,
        description=description,
        system_prompt_file=system_prompt_file,
        tools=tools,
        config_overrides=config_overrides,
        rag_sources=rag_sources,
        source_path=source_path,
    )


# ---------------------------------------------------------------------------
# Public: list / load / unload
# ---------------------------------------------------------------------------

def list_roles() -> list[str]:
    """
    Return a sorted list of role names available in the ``roles/`` directory.

    Only ``.toml`` files directly under ``roles/`` are scanned (not subdirs).
    Files that fail to parse are skipped with a warning.
    """
    if not _ROLES_DIR.exists():
        return []
    names: list[str] = []
    for p in sorted(_ROLES_DIR.glob("*.toml")):
        try:
            data = _parse_toml_file(p)
            role_section = data.get("role", {})
            n = role_section.get("name", p.stem)
            names.append(n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("roles: skipping '%s': %s", p.name, exc)
    return names


def load_role(name_or_path: str) -> RoleDefinition:
    """
    Load and activate a role by name or path.

    1. Resolve the TOML file (name → ``roles/<name>.toml``; path used as-is).
    2. Parse and validate the definition.
    3. Apply config overrides via ``utils.config_manager``.
    4. Override the system-prompt file if specified.
    5. Invalidate the prompt cache so the new prompt is picked up immediately.

    Returns the activated :class:`RoleDefinition`.
    Raises ``FileNotFoundError`` or ``ValueError`` on problems.
    """
    global _active_role, _saved_config_values, _saved_prompt_file

    path = _resolve_role_path(name_or_path)
    data = _parse_toml_file(path)
    role = _parse_role_dict(data, source_path=str(path))

    # ------------------------------------------------------------------
    # Save current state so unload_role() can restore it
    # ------------------------------------------------------------------
    from utils import config as cfg_module  # avoid circular import
    from utils.config_manager import config as cfg_mgr
    from utils.prompt import invalidate_cache

    _saved_config_values = {}
    for key in role.config_overrides:
        try:
            _saved_config_values[key] = cfg_mgr.get(key)
        except KeyError:
            pass  # unknown key — we won't try to restore it

    _saved_prompt_file = cfg_module.SYSTEM_PROMPT_FILE

    # ------------------------------------------------------------------
    # Apply config overrides
    # ------------------------------------------------------------------
    config_errors: list[str] = []
    for key, value in role.config_overrides.items():
        try:
            cfg_mgr.set(key, value)
        except (KeyError, ValueError) as exc:
            config_errors.append(f"  {key}: {exc}")

    if config_errors:
        # Restore what we changed so far before raising
        _restore_config()
        raise ValueError(
            f"Role '{role.name}' has invalid config overrides:\n"
            + "\n".join(config_errors)
        )

    # ------------------------------------------------------------------
    # Override system-prompt file
    # ------------------------------------------------------------------
    if role.system_prompt_file:
        cfg_module.SYSTEM_PROMPT_FILE = role.system_prompt_file

    # Invalidate the cached prompt so the new file is read on next use
    invalidate_cache()

    _active_role = role
    logger.info("roles: activated '%s' from %s", role.name, path)
    return role


def unload_role() -> None:
    """
    Deactivate the current role and restore pre-role defaults.

    * Config overrides are reversed via ``config_manager``.
    * The system-prompt file reverts to its previous value.
    * The prompt cache is invalidated.

    Safe to call when no role is active (no-op).
    """
    global _active_role, _saved_config_values, _saved_prompt_file

    if _active_role is None:
        return

    from utils import config as cfg_module
    from utils.prompt import invalidate_cache

    name = _active_role.name
    _restore_config()

    if _saved_prompt_file is not None:
        cfg_module.SYSTEM_PROMPT_FILE = _saved_prompt_file

    invalidate_cache()

    _active_role = None
    _saved_config_values = {}
    _saved_prompt_file = None
    logger.info("roles: unloaded '%s', defaults restored", name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_role_path(name_or_path: str) -> Path:
    """
    Turn a name like ``"researcher"`` into ``roles/researcher.toml``.
    A string containing a path separator or ending in ``.toml`` is treated
    as a literal filesystem path.
    """
    p = Path(name_or_path)
    if p.suffix == ".toml" or os.sep in name_or_path or "/" in name_or_path:
        resolved = p if p.is_absolute() else _REPO_ROOT / p
        if not resolved.exists():
            raise FileNotFoundError(f"Role file not found: {resolved}")
        return resolved

    # Treat as a role name → look in roles/
    candidate = _ROLES_DIR / f"{name_or_path}.toml"
    if candidate.exists():
        return candidate

    # Try case-insensitive scan in case the file is differently cased
    if _ROLES_DIR.exists():
        for p2 in _ROLES_DIR.glob("*.toml"):
            if p2.stem.lower() == name_or_path.lower():
                return p2

    raise FileNotFoundError(
        f"No role named '{name_or_path}' found in '{_ROLES_DIR}'. "
        f"Available: {list_roles()}"
    )


def _restore_config() -> None:
    """Re-apply saved config values (internal, does not touch prompt cache)."""
    from utils.config_manager import config as cfg_mgr

    for key, value in _saved_config_values.items():
        try:
            cfg_mgr.set(key, value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("roles: could not restore config key '%s': %s", key, exc)
