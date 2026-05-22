"""Runtime configuration manager for ntCode.

Provides a ``ConfigManager`` class that owns all mutable ntCode settings,
supports get/set with type coercion and validation, and can serialize the
current configuration to JSON (or .env format) and reload it at runtime.

A module-level ``config`` singleton is provided.  All call-time consumers
that need a setting which may have changed since startup should read from
``config.get(key)`` rather than from the frozen module-level constants in
``utils.config``.

Usage::

    from utils.config_manager import config

    model = config.get("DEFAULT_MODEL")
    config.set("DEFAULT_MODEL", "claude-3-5-sonnet-20241022")
    print(config.show())          # formatted table of all settings
    config.save("my_config.json")
    config.load("my_config.json")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
# Each entry: key -> (python_type, description, validator_or_None)
#
# validator is callable(value) -> None, raises ValueError on bad input.
# Only settings that make sense to change at runtime are included.
# Internal computed values (ALLOWED_BASE_PATHS, log handlers, etc.) are excluded.

def _must_be_positive_int(name: str):
    def _v(v):
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ValueError(f"{name} must be a positive integer, got {v!r}")
    return _v


def _must_be_nonneg_int(name: str):
    def _v(v):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ValueError(f"{name} must be a non-negative integer, got {v!r}")
    return _v


def _must_be_positive_float(name: str):
    def _v(v):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or float(v) <= 0:
            raise ValueError(f"{name} must be a positive number, got {v!r}")
    return _v


def _must_be_bool(name: str):
    def _v(v):
        if not isinstance(v, bool):
            raise ValueError(f"{name} must be true or false, got {v!r}")
    return _v


def _must_be_nonempty_str(name: str):
    def _v(v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"{name} must be a non-empty string, got {v!r}")
    return _v


def _provider_validator(v):
    allowed = {"anthropic", "openai"}
    if v not in allowed:
        raise ValueError(
            f"LLM_PROVIDER must be one of {sorted(allowed)!r}, got {v!r}"
        )


def _calling_convention_validator(v):
    allowed = {"", "auto", "ntcode", "xml", "json_block", "gemma"}
    if v not in allowed:
        raise ValueError(
            f"CALLING_CONVENTION must be one of {sorted(allowed)!r}, got {v!r}"
        )


def _temperature_validator(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ValueError(f"OPENAI_TEMPERATURE must be a number, got {v!r}")
    if not (0.0 <= float(v) <= 2.0):
        raise ValueError(
            f"OPENAI_TEMPERATURE must be between 0.0 and 2.0, got {v!r}"
        )


# (type, description, validator | None)
_SCHEMA: dict[str, tuple[type, str, Any]] = {
    # ── LLM / provider ───────────────────────────────────────────────────────
    "LLM_PROVIDER": (
        str,
        "Active LLM provider ('anthropic' or 'openai')",
        _provider_validator,
    ),
    "DEFAULT_MODEL": (
        str,
        "Anthropic model name (e.g. 'claude-sonnet-4-6')",
        _must_be_nonempty_str("DEFAULT_MODEL"),
    ),
    "ANTHROPIC_API_KEY": (
        str,
        "Anthropic API key",
        None,  # allow empty (key may not be needed when using OpenAI)
    ),
    "OPENAI_MODEL": (
        str,
        "OpenAI-compatible model name (e.g. 'gpt-4o', 'llama3')",
        _must_be_nonempty_str("OPENAI_MODEL"),
    ),
    "OPENAI_BASE_URL": (
        str,
        "OpenAI-compatible endpoint base URL",
        _must_be_nonempty_str("OPENAI_BASE_URL"),
    ),
    "OPENAI_API_KEY": (
        str,
        "Bearer token / API key for the OpenAI-compatible endpoint",
        None,
    ),
    "OPENAI_MAX_TOKENS": (
        int,
        "Max tokens for OpenAI responses (0 = let server decide)",
        _must_be_nonneg_int("OPENAI_MAX_TOKENS"),
    ),
    "CALLING_CONVENTION": (
        str,
        "Tool-calling format override ('auto', 'ntcode', 'xml', 'json_block', 'gemma')",
        _calling_convention_validator,
    ),
    "OPENAI_TEMPERATURE": (
        float,
        "Sampling temperature for OpenAI responses (0.0–2.0)",
        _temperature_validator,
    ),
    # ── Timeouts ─────────────────────────────────────────────────────────────
    "API_TIMEOUT": (
        float,
        "Anthropic API call timeout in seconds",
        _must_be_positive_float("API_TIMEOUT"),
    ),
    "GIT_TIMEOUT": (
        int,
        "Git command timeout in seconds",
        _must_be_positive_int("GIT_TIMEOUT"),
    ),
    "OPENAI_TIMEOUT": (
        float,
        "OpenAI-compatible endpoint timeout in seconds",
        _must_be_positive_float("OPENAI_TIMEOUT"),
    ),
    "OPENAI_MAX_RETRIES": (
        int,
        "Max retries for OpenAI-compatible endpoint calls",
        _must_be_positive_int("OPENAI_MAX_RETRIES"),
    ),
    # ── Rate limiting ─────────────────────────────────────────────────────────
    "TOKEN_LIMIT_PER_MINUTE": (
        int,
        "Token rate limit per minute (sliding window)",
        _must_be_positive_int("TOKEN_LIMIT_PER_MINUTE"),
    ),
    # ── Conversation ─────────────────────────────────────────────────────────
    "MAX_CONVERSATION_LENGTH": (
        int,
        "Max task-context messages before pruning",
        _must_be_positive_int("MAX_CONVERSATION_LENGTH"),
    ),
    # ── File / security ───────────────────────────────────────────────────────
    "MAX_FILE_SIZE": (
        int,
        "Maximum file size (bytes) for read/edit operations",
        _must_be_positive_int("MAX_FILE_SIZE"),
    ),
    "SYSTEM_PROMPT_FILE": (
        str,
        "Path to the system-prompt stub file",
        _must_be_nonempty_str("SYSTEM_PROMPT_FILE"),
    ),
    # ── Debug / verbosity ─────────────────────────────────────────────────────
    "DEBUG_MODE": (
        bool,
        "Enable detailed debug logging to console and file",
        _must_be_bool("DEBUG_MODE"),
    ),
    "VERBOSE_MODE": (
        bool,
        "Enable interactive tool-approval prompts before each tool runs",
        _must_be_bool("VERBOSE_MODE"),
    ),
    "LOG_CONVERSATIONS": (
        bool,
        "Log conversations and tool executions to ntcode.log",
        _must_be_bool("LOG_CONVERSATIONS"),
    ),
}

# Keys that should not be shown in plaintext in /config output
_SENSITIVE_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}


def _mask(key: str, value: Any) -> str:
    """Return a display-safe string for *value*."""
    if key in _SENSITIVE_KEYS and isinstance(value, str) and value:
        visible = value[:4]
        return f"{visible}{'*' * min(8, len(value) - 4)}"
    return repr(value)


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

def _coerce(key: str, raw: Any) -> Any:
    """Coerce *raw* to the schema type for *key*.

    Accepts strings from the /config set command as well as already-typed
    values (e.g. from JSON loading).

    Raises:
        KeyError:   If *key* is not in the schema.
        ValueError: If coercion fails.
    """
    expected_type, _, _ = _SCHEMA[key]

    if expected_type is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            if raw.lower() in ("true", "1", "yes", "on"):
                return True
            if raw.lower() in ("false", "0", "no", "off"):
                return False
        raise ValueError(
            f"Cannot convert {raw!r} to bool for '{key}'. "
            "Use: true / false / yes / no / 1 / 0"
        )

    if expected_type is int:
        if isinstance(raw, bool):
            raise ValueError(f"'{key}' must be an integer, not a boolean.")
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Cannot convert {raw!r} to int for '{key}'.")

    if expected_type is float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Cannot convert {raw!r} to float for '{key}'.")

    # str
    value = str(raw)
    if key in {"LLM_PROVIDER", "CALLING_CONVENTION"}:
        return value.lower().strip()
    return value


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Live, mutable ntCode runtime configuration.

    Initialised from the frozen module-level defaults in ``utils.config``
    (which already incorporate env-var overrides at import time).  After
    initialisation, settings may be changed via :meth:`set`, persisted via
    :meth:`save`, and restored via :meth:`load` or :meth:`reset`.

    All mutating methods also mirror the new value back into the
    ``utils.config`` module so that legacy call-sites reading module-level
    constants continue to see the updated value.

    Thread safety
    -------------
    Reads and single-key writes to the internal dict are GIL-safe in
    CPython.  No additional locking is used because config changes are
    infrequent and always originate from the single frontend thread.
    """

    def __init__(self) -> None:
        import utils.config as _cfg
        self._defaults: dict[str, Any] = {
            "LLM_PROVIDER":           _cfg.LLM_PROVIDER,
            "DEFAULT_MODEL":          _cfg.DEFAULT_MODEL,
            "ANTHROPIC_API_KEY":      os.environ.get("ANTHROPIC_API_KEY", ""),
            "OPENAI_MODEL":           _cfg.OPENAI_MODEL,
            "OPENAI_BASE_URL":        _cfg.OPENAI_BASE_URL,
            "OPENAI_API_KEY":         _cfg.OPENAI_API_KEY,
            "OPENAI_MAX_TOKENS":      int(_cfg.OPENAI_MAX_TOKENS),
            "CALLING_CONVENTION":     _cfg.CALLING_CONVENTION,
            "OPENAI_TEMPERATURE":     float(_cfg.OPENAI_TEMPERATURE),
            "API_TIMEOUT":            float(_cfg.API_TIMEOUT),
            "GIT_TIMEOUT":            int(_cfg.GIT_TIMEOUT),
            "OPENAI_TIMEOUT":         float(_cfg.OPENAI_TIMEOUT),
            "OPENAI_MAX_RETRIES":     int(_cfg.OPENAI_MAX_RETRIES),
            "TOKEN_LIMIT_PER_MINUTE": int(_cfg.TOKEN_LIMIT_PER_MINUTE),
            "MAX_CONVERSATION_LENGTH": int(_cfg.MAX_CONVERSATION_LENGTH),
            "MAX_FILE_SIZE":          int(_cfg.MAX_FILE_SIZE),
            "SYSTEM_PROMPT_FILE":     _cfg.SYSTEM_PROMPT_FILE,
            "DEBUG_MODE":             bool(_cfg.DEBUG_MODE),
            "VERBOSE_MODE":           bool(_cfg.VERBOSE_MODE),
            "LOG_CONVERSATIONS":      bool(_cfg.LOG_CONVERSATIONS),
        }
        self._values: dict[str, Any] = dict(self._defaults)

    # ------------------------------------------------------------------
    # Core get / set
    # ------------------------------------------------------------------

    def keys(self) -> list[str]:
        """Return the sorted list of all configurable keys."""
        return sorted(_SCHEMA.keys())

    def get(self, key: str) -> Any:
        """Return the current value for *key*.

        Raises:
            KeyError: If *key* is not a recognised config key.
        """
        if key not in _SCHEMA:
            raise KeyError(
                f"Unknown config key {key!r}. "
                "Use /config to see all available keys."
            )
        return self._values[key]

    def set(self, key: str, raw_value: Any) -> str:
        """Set *key* to *raw_value* with type coercion and validation.

        *raw_value* may be a string (from /config set) or an already-typed
        value (from JSON loading).

        Returns:
            A human-readable confirmation string, e.g.
            ``"DEFAULT_MODEL: 'claude-sonnet-4-6' → 'claude-3-5-sonnet-20241022'"``

        Raises:
            KeyError:   If *key* is not recognised.
            ValueError: If *raw_value* fails validation.
        """
        if key not in _SCHEMA:
            raise KeyError(
                f"Unknown config key {key!r}. "
                "Use /config to see all available keys."
            )
        coerced = _coerce(key, raw_value)
        _, _, validator = _SCHEMA[key]
        if validator is not None:
            validator(coerced)  # raises ValueError on bad values
        old = self._values[key]
        self._values[key] = coerced
        self._sync_to_config(key, coerced)
        return f"{key}: {_mask(key, old)} → {_mask(key, coerced)}"

    def reset(self, key: str | None = None) -> str:
        """Reset one or all keys to their startup defaults.

        Args:
            key: The key to reset, or None to reset everything.

        Returns:
            A human-readable confirmation string.
        """
        if key is not None:
            if key not in _SCHEMA:
                raise KeyError(f"Unknown config key {key!r}.")
            self._values[key] = self._defaults[key]
            self._sync_to_config(key, self._defaults[key])
            return f"{key} reset to {_mask(key, self._defaults[key])}"
        self._values = dict(self._defaults)
        for k, v in self._defaults.items():
            self._sync_to_config(k, v)
        return "All configuration values reset to startup defaults."

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def show(self, key: str | None = None) -> str:
        """Return a formatted view of the configuration.

        Args:
            key: If given, show only that key.  If None, show all.

        Returns:
            A multi-line human-readable string.
        """
        if key is not None:
            if key not in _SCHEMA:
                raise KeyError(
                    f"Unknown config key {key!r}. "
                    "Use /config to see all available keys."
                )
            _, desc, _ = _SCHEMA[key]
            val = _mask(key, self._values[key])
            default = _mask(key, self._defaults[key])
            changed = " *" if self._values[key] != self._defaults[key] else ""
            return f"{key}{changed}\n  value  : {val}\n  default: {default}\n  info   : {desc}"

        lines = ["ntCode configuration (* = changed from startup default):", ""]
        # Group by category
        groups = [
            ("LLM / Provider",   ["LLM_PROVIDER", "DEFAULT_MODEL", "ANTHROPIC_API_KEY",
                                   "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_API_KEY",
                                   "OPENAI_MAX_TOKENS", "CALLING_CONVENTION",
                                   "OPENAI_TEMPERATURE"]),
            ("Timeouts",         ["API_TIMEOUT", "GIT_TIMEOUT", "OPENAI_TIMEOUT",
                                   "OPENAI_MAX_RETRIES"]),
            ("Rate limiting",    ["TOKEN_LIMIT_PER_MINUTE"]),
            ("Conversation",     ["MAX_CONVERSATION_LENGTH"]),
            ("Files / Security", ["MAX_FILE_SIZE", "SYSTEM_PROMPT_FILE"]),
            ("Debug / Logging",  ["DEBUG_MODE", "VERBOSE_MODE", "LOG_CONVERSATIONS"]),
        ]
        for group_name, keys in groups:
            lines.append(f"  [{group_name}]")
            for k in keys:
                val = _mask(k, self._values[k])
                changed = " *" if self._values[k] != self._defaults[k] else ""
                lines.append(f"    {k}{changed} = {val}")
            lines.append("")
        lines.append("Use /config set <KEY> <value>  to change a setting.")
        lines.append("Use /config save [file]         to persist to JSON.")
        lines.append("Use /config load [file]         to reload from JSON.")
        lines.append("Use /config reset [key]         to restore default(s).")
        lines.append("Use /config help <KEY>          to see info about a key.")
        return "\n".join(lines)

    def help_key(self, key: str) -> str:
        """Return a detailed help string for a single key."""
        return self.show(key)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str = "ntcode_config.json") -> str:
        """Write the current configuration to a JSON file at *path*.

        Returns:
            A human-readable confirmation string.
        """
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                json.dump(self._values, fh, indent=2, ensure_ascii=False)
            return f"Configuration saved to {p.resolve()} ({len(self._values)} keys)."
        except Exception as exc:  # noqa: BLE001
            return f"\u274c Failed to save config: {exc}"

    def load(self, path: str = "ntcode_config.json") -> str:
        """Load configuration from a JSON file at *path*.

        Only keys present in the schema are applied; unknown keys are
        logged as warnings and ignored so that old config files do not
        cause errors after a schema change.

        Returns:
            A human-readable summary of what was applied (and what was
            skipped), or an error string on failure.
        """
        try:
            p = Path(path)
            with p.open(encoding="utf-8") as fh:
                raw: dict = json.load(fh)
        except FileNotFoundError:
            return f"\u274c Config file not found: {path}"
        except json.JSONDecodeError as exc:
            return f"\u274c Invalid JSON in {path}: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"\u274c Failed to read config file: {exc}"

        applied: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        for key, raw_value in raw.items():
            if key not in _SCHEMA:
                skipped.append(key)
                continue
            try:
                self.set(key, raw_value)  # coerces + validates + syncs
                applied.append(key)
            except (KeyError, ValueError) as exc:
                errors.append(f"{key}: {exc}")

        parts = [f"Loaded {path}:"]
        if applied:
            parts.append(f"  Applied  ({len(applied)}): {', '.join(applied)}")
        if skipped:
            parts.append(f"  Skipped  ({len(skipped)}): {', '.join(skipped)}")
        if errors:
            parts.append(f"  Errors   ({len(errors)}):")
            for e in errors:
                parts.append(f"    {e}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal: mirror changes back to utils.config
    # ------------------------------------------------------------------

    def _sync_to_config(self, key: str, value: Any) -> None:
        """Write *value* back to the matching name in ``utils.config``.

        This keeps legacy call-sites that read module-level constants
        (e.g. ``cfg.VERBOSE_MODE``) in sync with ``config.get()``.
        """
        try:
            import utils.config as _cfg
            if hasattr(_cfg, key):
                setattr(_cfg, key, value)
        except Exception:  # noqa: BLE001
            pass  # best-effort; don't crash on sync failure


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: The global ConfigManager instance.  Import and use this everywhere.
config: ConfigManager = ConfigManager()
