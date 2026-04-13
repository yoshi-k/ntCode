"""Shared frontend logic for ntCode.

This module contains everything that is not I/O-specific, so that both the
TUI (``frontend/agent_loop.py``) and batch (``frontend/batch_loop.py``) frontends
can share it without divergence.

What lives here
---------------
* ``ERROR_PREFIXES`` / ``is_error_response()`` — detect provider error sentinels.
* ``HELP_TEXT`` — the /help string shown to users.
* ``handle_provider_command()`` — /provider sub-commands; returns a plain string.
* ``handle_config_command()`` — /config sub-commands; returns a plain string.
* ``DispatchResult`` — enum returned by ``dispatch_line()``.
* ``dispatch_line()`` — parse one line of input and act on it; the caller decides
  how to display the result and whether to wait for a connector reply.

What does NOT live here
-----------------------
* ANSI colour codes  (stay in ``agent_loop.py``).
* ``input()`` / ``print()`` calls.
* File I/O beyond config save/load.
* The agent thread or ``Connector`` instantiation.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from tools.registry import TOOL_REGISTRY, get_full_system_prompt
from utils.connector import Connector
from utils.config import logger

# ---------------------------------------------------------------------------
# Error-sentinel detection  (single source of truth — used by both frontends)
# ---------------------------------------------------------------------------

ERROR_PREFIXES = (
    "\u23f1\ufe0f",   # ⏱️  timeout
    "\U0001f6ab",     # 🚫  rate limit
    "\U0001f310",     # 🌐  connection
    "\U0001f511",     # 🔑  auth
    "\u274c",         # ❌  API error
    "\U0001f4a5",     # 💥  unexpected
)


def is_error_response(content: str) -> bool:
    """Return True if *content* is a provider-level error sentinel."""
    return any(content.startswith(p) for p in ERROR_PREFIXES)


# ---------------------------------------------------------------------------
# Help text  (single source of truth)
# ---------------------------------------------------------------------------

HELP_TEXT = """\
Available commands:
  /help                        Show this help message
  /quit  or  /exit             Exit ntCode

  Conversation:
  /reset                       Clear conversation history (keep system prompt)
  /save  [file]                Save conversation to file
  /load  [file]                Load conversation from file
  /savepoint <name>            Capture an in-memory save point
  /restore   <name>            Roll back to a named save point
  /savepoints                  List all current in-memory save points

  Info:
  /prompt                      Show the current system prompt
  /tools                       List available tools
  /provider                    Show the current LLM provider
  /provider list               List all available provider aliases
  /provider <alias>            Switch provider  (e.g. /provider ollama)
  /provider <alias>/<model>    Switch provider and model  (e.g. /provider openai/gpt-4o)

  Configuration:
  /config                      Show all current configuration settings
  /config help <KEY>           Show description and current value for KEY
  /config set <KEY> <value>    Change a setting at runtime
  /config reset                Reset all settings to startup defaults
  /config reset <KEY>          Reset one setting to its startup default
  /config save [file]          Save current config to JSON (default: ntcode_config.json)
  /config load [file]          Load config from JSON file
"""


# ---------------------------------------------------------------------------
# Provider command handler  (returns plain text; no print() calls)
# ---------------------------------------------------------------------------

def handle_provider_command(arg: str) -> str:
    """Handle all /provider sub-commands and return a plain-text result string.

    * ``/provider``          — return the active provider description.
    * ``/provider list``     — return all known aliases.
    * ``/provider <spec>``   — switch; spec may be ``alias`` or ``alias/model``.
    """
    from utils.llm import list_providers, current_provider_name, switch_provider

    arg = arg.strip()

    if not arg:
        return f"Current provider: {current_provider_name()}"

    if arg.lower() == "list":
        lines = ["Available provider aliases:"]
        for alias in list_providers():
            lines.append(f"  {alias}")
        return "\n".join(lines)

    try:
        return switch_provider(arg)
    except ValueError as exc:
        return f"\u274c {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"\u274c Failed to switch provider: {exc}"


# ---------------------------------------------------------------------------
# Config command handler  (returns plain text; no print() calls)
# ---------------------------------------------------------------------------

def handle_config_command(arg: str) -> str:
    """Handle all /config sub-commands and return a plain-text result string.

    Sub-commands
    ------------
    /config                     — show all settings.
    /config help <KEY>          — show description + value for KEY.
    /config set <KEY> <value>   — change a setting.
    /config reset               — restore all settings to startup defaults.
    /config reset <KEY>         — restore one setting to its startup default.
    /config save [file]         — persist current config to JSON.
    /config load [file]         — reload config from JSON.
    """
    from utils.config_manager import config

    arg = arg.strip()

    # /config  (no sub-command) → show everything
    if not arg:
        return config.show()

    parts = arg.split(None, 2)   # up to 3 tokens: sub-cmd [KEY] [value]
    sub = parts[0].lower()

    # /config help <KEY>
    if sub == "help":
        if len(parts) < 2:
            return "Usage: /config help <KEY>"
        key = parts[1].upper()
        try:
            return config.help_key(key)
        except KeyError as exc:
            return f"\u274c {exc}"

    # /config set <KEY> <value>
    if sub == "set":
        if len(parts) < 3:
            return "Usage: /config set <KEY> <value>"
        key = parts[1].upper()
        value = parts[2]          # raw string; ConfigManager coerces it
        try:
            result = config.set(key, value)
            # For LLM_PROVIDER changes, also switch the active LLM provider
            # so the change takes effect immediately without a restart.
            if key == "LLM_PROVIDER":
                try:
                    from utils.llm import switch_provider
                    switch_provider(value.strip().lower())
                except Exception as exc:  # noqa: BLE001
                    result += f"\n  (LLM provider switch: {exc})"
            return f"\u2705 {result}"
        except (KeyError, ValueError) as exc:
            return f"\u274c {exc}"

    # /config reset  or  /config reset <KEY>
    if sub == "reset":
        key = parts[1].upper() if len(parts) >= 2 else None
        try:
            return f"\u2705 {config.reset(key)}"
        except KeyError as exc:
            return f"\u274c {exc}"

    # /config save [file]
    if sub == "save":
        path = parts[1] if len(parts) >= 2 else "ntcode_config.json"
        return config.save(path)

    # /config load [file]
    if sub == "load":
        path = parts[1] if len(parts) >= 2 else "ntcode_config.json"
        return config.load(path)

    return (
        f"Unknown /config sub-command: {sub!r}\n"
        "Use /config help for usage."
    )


# ---------------------------------------------------------------------------
# Dispatch result
# ---------------------------------------------------------------------------

class DispatchResult(Enum):
    """What ``dispatch_line`` did with the input line.

    The caller uses this to decide whether to wait for a connector reply.

    QUIT    — the user requested exit; the caller should break its loop.
    LOCAL   — handled entirely locally (e.g. /help, /tools, /provider);
              ``reply`` contains the text to display; no connector reply expected.
    CONTROL — a control command was forwarded to the agent via the connector;
              the caller should call ``connector.receive_assistant_blocking()``.
    USER    — a plain user message was forwarded to the agent via the connector;
              the caller should wait for the agent's full response.
    """
    QUIT    = auto()
    LOCAL   = auto()
    CONTROL = auto()
    USER    = auto()


class DispatchOutcome:
    """Return value of ``dispatch_line()``.

    Attributes
    ----------
    result : DispatchResult
        What kind of action was taken.
    reply : str
        For ``LOCAL`` results: the text to display to the user.
        For all other results: empty string.
    """

    __slots__ = ("result", "reply")

    def __init__(self, result: DispatchResult, reply: str = "") -> None:
        self.result = result
        self.reply = reply

    def __repr__(self) -> str:  # pragma: no cover
        return f"DispatchOutcome({self.result.name}, reply={self.reply!r})"


# ---------------------------------------------------------------------------
# Central dispatcher
# ---------------------------------------------------------------------------

def dispatch_line(line: str, connector: Connector) -> DispatchOutcome:
    """Parse one line of user input and act on it.

    Parameters
    ----------
    line :
        A single stripped line of user input.  Must be non-empty.
    connector :
        The shared ``Connector`` instance.  Control and user messages are
        forwarded here; the caller is responsible for reading the reply.

    Returns
    -------
    DispatchOutcome
        See :class:`DispatchResult` for the meaning of each variant.
    """
    if not line:
        # Callers should filter blank lines, but be safe.
        return DispatchOutcome(DispatchResult.LOCAL, reply="")

    if not line.startswith("/"):
        # Plain user message — forward to agent.
        connector.send_user(line)
        return DispatchOutcome(DispatchResult.USER)

    # ------------------------------------------------------------------ #
    # Slash-command dispatch
    # ------------------------------------------------------------------ #
    parts = line.strip().split(None, 1)
    name = parts[0].lower()
    arg  = parts[1].strip() if len(parts) > 1 else ""

    # --- exit ---
    if name in ("/quit", "/exit"):
        return DispatchOutcome(DispatchResult.QUIT)

    # --- local / read-only info commands ---
    if name == "/help":
        return DispatchOutcome(DispatchResult.LOCAL, reply=HELP_TEXT)

    if name == "/tools":
        return DispatchOutcome(
            DispatchResult.LOCAL,
            reply="Available tools: " + ", ".join(TOOL_REGISTRY.keys()),
        )

    if name == "/prompt":
        return DispatchOutcome(DispatchResult.LOCAL, reply=get_full_system_prompt())

    if name == "/provider":
        return DispatchOutcome(
            DispatchResult.LOCAL,
            reply=handle_provider_command(arg),
        )

    if name == "/config":
        return DispatchOutcome(
            DispatchResult.LOCAL,
            reply=handle_config_command(arg),
        )

    # --- state-mutating commands forwarded to the agent ---
    if name == "/reset":
        connector.send_control("reset")
        return DispatchOutcome(DispatchResult.CONTROL)

    if name == "/save":
        connector.send_control("save", arg or None)
        return DispatchOutcome(DispatchResult.CONTROL)

    if name == "/load":
        connector.send_control("load", arg or None)
        return DispatchOutcome(DispatchResult.CONTROL)

    if name == "/savepoint":
        connector.send_control("savepoint", arg)
        return DispatchOutcome(DispatchResult.CONTROL)

    if name == "/restore":
        connector.send_control("restore", arg)
        return DispatchOutcome(DispatchResult.CONTROL)

    if name == "/savepoints":
        connector.send_control("savepoints")
        return DispatchOutcome(DispatchResult.CONTROL)

    # --- unknown ---
    return DispatchOutcome(
        DispatchResult.LOCAL,
        reply=f"Unknown command: {name}  (type /help for a list)",
    )
