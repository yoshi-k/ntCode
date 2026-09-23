"""Pure-logic agent loop for ntCode.

This module contains **no** UI code.  It communicates exclusively through a
:class:`~utils.connector.Connector` instance:

* Reads user messages via :meth:`~utils.connector.Connector.receive_user_blocking`.
* Writes assistant responses via :meth:`~utils.connector.Connector.send_assistant`.

The TUI (or any other frontend) owns the ``Connector`` and starts
:func:`run_agent` in a background thread::

    from utils.connector import Connector
    from utils.agent import run_agent

    connector = Connector()
    thread = threading.Thread(target=run_agent, args=(connector,), daemon=True)
    thread.start()
"""

import json
import os
import pathlib
import datetime
from typing import Any, Dict, List, Optional

from utils.config import DEBUG_MODE, logger
from utils import config as cfg_module
import utils.llm as llm_module
from utils.llm import SessionHeader, ConversationManager
from utils.connector import Connector
from tools.registry import TOOL_REGISTRY, get_full_system_prompt, execute_tool_safely
from core.tool_schema import tool_specs
from core.types import Message, ToolCall, ToolResult
from providers.base import Provider
from providers.errors import ProviderError

# Default directory used when the user does not supply a path for save/load.
_DEFAULT_SAVE_DIR = "saves"


def _default_save_path() -> str:
    """Return a timestamped path inside the saves/ folder."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    p = pathlib.Path(_DEFAULT_SAVE_DIR) / f"conversation-{timestamp}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


# ---------------------------------------------------------------------------
# Conversation persistence helpers
# ---------------------------------------------------------------------------

def _save_conversation(mgr: ConversationManager, path: str) -> str:
    """Serialise the task-context messages to a JSON file at *path*.

    Returns a human-readable status string.
    """
    try:
        abs_path = os.path.abspath(path)
        flat = mgr.as_flat_conversation()
        with open(abs_path, "w", encoding="utf-8") as fh:
            json.dump(flat, fh, ensure_ascii=False, indent=2)
        logger.info("Conversation saved to %s (%d messages)", abs_path, len(flat))
        return f"Conversation saved to {abs_path} ({len(flat)} messages)."
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save conversation: %s", exc)
        return f"\u274c Failed to save conversation: {exc}"


def _load_conversation(mgr: ConversationManager, path: str) -> str:
    """Load a previously saved conversation into *mgr*'s task context.

    Returns a human-readable status string.
    """
    try:
        abs_path = os.path.abspath(path)
        with open(abs_path, "r", encoding="utf-8") as fh:
            flat: List[Dict[str, Any]] = json.load(fh)
        # Strip any system-role entries that might exist in old saves.
        flat = [m for m in flat if m.get("role") != "system"]
        mgr.start_task()           # clear current task context
        mgr.restore_from_flat(flat)
        logger.info("Conversation loaded from %s (%d messages)", abs_path, len(flat))
        return f"Conversation loaded from {abs_path} ({len(flat)} messages restored)."
    except FileNotFoundError:
        msg = f"\u274c File not found: {path}"
        logger.warning(msg)
        return msg
    except Exception as exc:  # noqa: BLE001
        msg = f"\u274c Failed to load conversation: {exc}"
        logger.error(msg)
        return msg


# ---------------------------------------------------------------------------
# Control-message handler (ConversationManager-aware)
# ---------------------------------------------------------------------------

def _handle_control(
    msg: Dict[str, Any],
    mgr: ConversationManager,
    connector: "Connector",
) -> bool:
    """Execute a control command and publish a status reply via *connector*.

    Control commands never call the model; the caller waits for the next
    user message afterwards.  Returns True once handled.
    """
    command = msg.get("command", "")
    payload = msg.get("payload", "") or ""

    if command == "reset":
        mgr.start_task()
        connector.send_assistant("Conversation reset. Starting fresh!")
        logger.info("Conversation reset by user.")

    elif command == "save":
        path = payload or _default_save_path()
        connector.send_assistant(_save_conversation(mgr, path))

    elif command == "load":
        path = payload or _DEFAULT_SAVE_DIR
        p = pathlib.Path(path)
        if p.is_dir():
            candidates = sorted(p.glob("*.json"), key=lambda f: f.stat().st_mtime)
            if not candidates:
                connector.send_assistant(
                    f"\u274c No saved conversations found in {path}/"
                )
                return True
            path = str(candidates[-1])
        connector.send_assistant(_load_conversation(mgr, path))

    elif command == "savepoint":
        # payload is the save-point name
        name = payload.strip()
        if not name:
            connector.send_assistant(
                "\u274c Usage: /savepoint <name>"
            )
            return True
        try:
            mgr.save_point(name)
            count = mgr.task_message_count
            connector.send_assistant(
                f"\U0001f4cc Save point {name!r} captured ({count} messages)."
            )
        except ValueError as exc:
            connector.send_assistant(f"\u274c {exc}")

    elif command == "restore":
        # payload is the save-point name
        name = payload.strip()
        if not name:
            names = mgr.save_point_names
            if names:
                connector.send_assistant(
                    f"\u274c Usage: /restore <name>. "
                    f"Available save points: {', '.join(names)}"
                )
            else:
                connector.send_assistant(
                    "\u274c No save points exist yet. Use /savepoint <name> first."
                )
            return True
        try:
            mgr.restore(name)
            count = mgr.task_message_count
            connector.send_assistant(
                f"\u23ea Restored to save point {name!r} ({count} messages)."
            )
        except KeyError as exc:
            connector.send_assistant(f"\u274c {exc}")

    elif command == "savepoints":
        # list all save points
        names = mgr.save_point_names
        if names:
            connector.send_assistant(
                "\U0001f4cc Save points: " + ", ".join(names)
            )
        else:
            connector.send_assistant(
                "No save points yet. Use /savepoint <name> to create one."
            )

    elif command == "role":
        # Handle role load/unload/show commands
        return _handle_role_command(payload, mgr, connector)

    elif command == "config_changed":
        # Kept for compatibility with frontends that may send this control
        # message. The normal agent loop refreshes prompt/parser before every
        # LLM call, so no action is required here.
        connector.send_assistant("Configuration will be applied before the next LLM call.")

    else:
        connector.send_assistant(f"\u274c Unknown control command: {command!r}")
        logger.warning("Unknown control command: %s", command)

    return True


def _handle_role_command(
    payload: str,
    mgr: ConversationManager,
    connector: "Connector",
) -> bool:
    """Handle role load/unload/show/list commands.  Returns True once handled.

    Loading or unloading a role changes the allowed tools and possibly the
    prompt file and provider settings (utils.roles rebuilds the provider);
    the agent loop rebuilds the system prompt and tool list before the next
    model call.
    """
    from utils.roles import list_roles, load_role, unload_role, get_active_role
    from utils.prompt import invalidate_cache

    parts = payload.split()
    sub = parts[0].lower() if parts else ""

    # /role (no sub-command) → list available roles
    if sub in ("", "list"):
        available = list_roles()
        if not available:
            connector.send_assistant(
                "No roles found.  "
                "Add .toml files to the roles/ directory to define roles."
            )
            return True
        active = get_active_role()
        lines = ["Available roles:"]
        for rname in available:
            marker = "  ← active" if (active and active.name == rname) else ""
            lines.append(f"  {rname}{marker}")
        connector.send_assistant("\n".join(lines))
        return True

    # /role load <name>
    if sub == "load":
        if len(parts) < 2:
            connector.send_assistant(
                "\u274c Usage: /role load <name>   "
                "(use /role list to see available roles)"
            )
            return True
        name_or_path = parts[1]
        try:
            role = load_role(name_or_path)
            # The prompt and tool list are rebuilt before the next model call.
            invalidate_cache()
            connector.set_role_name(role.name)

            tool_list = ", ".join(role.tools) if role.tools else "all available tools"
            role_notification = (
                f"\u2705 Role '{role.name}' loaded.\n"
                f"Available tools: {tool_list}\n\n"
                f"{role.summary()}"
            )
            connector.send_assistant(role_notification)
            logger.info("Role '%s' loaded and system prompt rebuilt", role.name)
            return True

        except FileNotFoundError as exc:
            connector.send_assistant(f"\u274c {exc}")
            return True
        except ValueError as exc:
            connector.send_assistant(f"\u274c Error loading role: {exc}")
            return True
        except Exception as exc:  # noqa: BLE001
            connector.send_assistant(f"\u274c Unexpected error loading role: {exc}")
            return True

    # /role show
    if sub == "show":
        active = get_active_role()
        if active is None:
            connector.send_assistant(
                "No role is currently active.  "
                "Use /role load <name> to activate one."
            )
            return True
        connector.send_assistant(active.summary())
        return True

    # /role unload
    if sub == "unload":
        active = get_active_role()
        if active is None:
            connector.send_assistant("No role is currently active.")
            return True
        rname = active.name
        unload_role()
        invalidate_cache()
        connector.set_role_name("default")

        role_notification = (
            f"\u2705 Role '{rname}' unloaded. Defaults restored.\n"
            f"You now have access to all available tools."
        )
        connector.send_assistant(role_notification)
        logger.info("Role '%s' unloaded, system prompt rebuilt", rname)
        return True

    connector.send_assistant(
        f"\u274c Unknown /role sub-command: {sub!r}\n"
        "Use: /role list | /role load <name> | /role show | /role unload"
    )
    return True


# ---------------------------------------------------------------------------
# One model step: a provider call plus its tool calls
# ---------------------------------------------------------------------------

def _execute_tool_call(call: ToolCall, connector: Connector) -> ToolResult:
    """Run one tool call and return its result.

    Every call gets a result, including unknown, rejected and failing
    tools (with ``is_error``): native APIs reject a request in which a tool
    call has no matching result.
    """
    def error(message: str) -> ToolResult:
        payload = {"error": message, "tool_name": call.name, "success": False}
        return ToolResult(call.id, json.dumps(payload), is_error=True)

    if call.raw_arguments is not None:
        logger.warning("Tool %s called with invalid arguments: %r", call.name, call.raw_arguments)
        return error(
            f"The arguments are not a valid JSON object: {call.raw_arguments!r}. "
            "Call the tool again with a JSON object matching its parameters."
        )

    if call.name not in TOOL_REGISTRY:
        logger.warning("Model called unknown tool %r", call.name)
        return error(f"Unknown tool: {call.name}")

    if cfg_module.VERBOSE_MODE:
        connector.request_approval(call.name, call.args)
        approval = connector.receive_approval_response_blocking(timeout=60)
        if approval is None or not approval.get("approved", False):
            logger.info("Tool %s rejected by user (verbose mode)", call.name)
            connector.send_assistant(f"Tool {call.name} was rejected by user.")
            return error("Tool execution rejected by user.")

    try:
        if DEBUG_MODE:
            logger.debug("Executing tool %s args=%s", call.name, call.args)
        result = execute_tool_safely(call.name, TOOL_REGISTRY[call.name], call.args)
    except Exception as exc:  # noqa: BLE001
        logger.error("Tool execution failed for %s: %s", call.name, exc)
        return error(f"Tool execution failed: {exc}")

    if DEBUG_MODE:
        logger.debug("Tool %s result: %s", call.name, result)
    is_error = isinstance(result, dict) and bool(result.get("error"))
    return ToolResult(
        call.id, json.dumps(result, ensure_ascii=False, default=str), is_error=is_error
    )


def _native_step(
    provider: Provider,
    mgr: ConversationManager,
    connector: Connector,
    allowed_tools: Optional[List[str]],
) -> bool:
    """One model call plus its tool calls.  Returns True when the turn is over.

    The turn is over when the model replies without tool calls (the reply is
    published), refuses, or the provider fails (the error is published and
    nothing is added to the history).  Otherwise the tool results are added
    and the caller calls the model again.
    """
    mgr.session_header = SessionHeader(system_prompt=get_full_system_prompt())
    system = mgr.session_header.system_with_docs()
    tools = tool_specs(TOOL_REGISTRY, allowed_tools)

    try:
        turn = provider.complete(system, mgr.messages(), tools)
    except ProviderError as exc:
        logger.error("Provider error (%s): %s", type(exc).__name__, exc)
        connector.send_assistant(f"\u274c {exc.user_message()}")
        return True

    msg = turn.message
    if turn.stop_reason == "refusal":
        note = "\u26a0\ufe0f The model declined this request."
        connector.send_assistant(f"{note}\n{msg.text}" if msg.text else note)
        return True

    if msg.content:
        mgr.add_message(msg)

    if not msg.tool_calls:
        text = msg.text or "(The model returned an empty reply.)"
        if turn.stop_reason == "max_tokens":
            text += "\n\n(The reply was cut off at the max_tokens limit.)"
        connector.send_assistant(text)
        return True

    results = [_execute_tool_call(call, connector) for call in msg.tool_calls]
    mgr.add_message(Message.tool_results(results))
    return False


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(connector: Connector) -> None:
    """Drive the LLM conversation loop; communicate only via *connector*.

    Designed to run in a background thread.  Blocks on
    :meth:`~utils.connector.Connector.receive_user_blocking` waiting for
    the next user turn, then runs the inner tool-execution loop until the LLM
    produces a plain (non-tool) response, publishes it via
    :meth:`~utils.connector.Connector.send_assistant`, and waits again.

    Each model call goes through the active provider (utils.llm.llm, a
    providers.base.Provider); the reply and the tool results are stored as
    typed core.types messages (see _native_step).

    Exits cleanly when the connector is shut down.
    """
    mgr = ConversationManager(SessionHeader(system_prompt=get_full_system_prompt()))
    logger.info("AgentLoop started, waiting for user messages.")

    while True:
        # ----------------------------------------------------------------
        # Wait for the next user turn or control command
        # ----------------------------------------------------------------
        user_msg = connector.receive_user_blocking()
        if user_msg is None:
            logger.info("AgentLoop: connector shut down, exiting.")
            break

        # Handle control commands (save / load / reset / role) without the model
        if user_msg.get("role") == "control":
            _handle_control(user_msg, mgr, connector)
            continue
        mgr.add_user(user_msg["content"])

        # ----------------------------------------------------------------
        # Inner loop: model -> tools -> model ... until a plain reply
        # ----------------------------------------------------------------
        while True:
            try:
                mgr.prune_task_messages(cfg_module.MAX_CONVERSATION_LENGTH)

                # Re-read the role and prompt files every step so /config,
                # /role and prompt-file changes apply without a restart.
                from utils.roles import get_active_role
                from utils.prompt import invalidate_cache

                active_role = get_active_role()
                allowed_tools = active_role.tools if active_role and active_role.tools else None
                invalidate_cache()

                if _native_step(llm_module.llm, mgr, connector, allowed_tools):
                    break

            except Exception as exc:  # noqa: BLE001
                logger.error("Agent inner loop error: %s", exc)
                connector.send_assistant(
                    f"\U0001f4a5 Internal error: {exc}\n"
                    "Please try again with a shorter or simpler request."
                )
                break
