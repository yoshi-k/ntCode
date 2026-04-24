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
from typing import Any, Dict, List, Optional, Tuple

from utils.config import (
    DEBUG_MODE,
    VERBOSE_MODE,
    MAX_CONVERSATION_LENGTH,
    LLM_PROVIDER,
    logger,
)
from utils.llm import execute_llm_call, SessionHeader, ConversationManager
from utils.connector import Connector
from tools.registry import TOOL_REGISTRY, get_full_system_prompt, execute_tool_safely
from utils.tool_format import get_parser_for_provider

# Default directory used when the user does not supply a path for save/load.
_DEFAULT_SAVE_DIR = "saves"


def _default_save_path() -> str:
    """Return a timestamped path inside the saves/ folder."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    p = pathlib.Path(_DEFAULT_SAVE_DIR) / f"conversation-{timestamp}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


# ---------------------------------------------------------------------------
# Tool invocation parser
# ---------------------------------------------------------------------------

def _resolve_active_model() -> str:
    """Return the model name string for the currently active provider."""
    import os
    if LLM_PROVIDER == "openai":
        from utils.config import OPENAI_MODEL
        return OPENAI_MODEL
    from utils.config import DEFAULT_MODEL
    return os.environ.get("NTCODE_MODEL", DEFAULT_MODEL)


# Parser selected at agent startup based on the active provider/model.
# Stored at module level so it is chosen once and reused for every turn.
_active_parser = get_parser_for_provider(LLM_PROVIDER, _resolve_active_model())


def extract_tool_invocations(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Return list of (tool_name, args) extracted from *text*.

    Delegates to the provider-aware parser selected at import time by
    :func:`utils.tool_format.get_parser_for_provider`.  The parser is
    determined once from ``LLM_PROVIDER`` and the active model name so that
    the correct syntax (ntcode / xml / json_block) is used throughout the
    session.

    Lines that do not match the expected format, reference unknown tool names,
    or carry malformed JSON are logged as warnings and silently skipped.
    """
    invocations = _active_parser(text)

    if DEBUG_MODE and invocations:
        logger.debug(
            "Extracted %d tool invocation(s): %s",
            len(invocations),
            [n for n, _ in invocations],
        )

    return invocations


# ---------------------------------------------------------------------------
# Error-response detection
# ---------------------------------------------------------------------------

# Emoji prefixes used by execute_llm_call() to signal provider-level errors.
_ERROR_PREFIXES = (
    "\u23f1\ufe0f",   # timeout
    "\U0001f6ab",     # rate limit
    "\U0001f310",     # connection
    "\U0001f511",     # auth
    "\u274c",         # API error
    "\U0001f4a5",     # unexpected
)


def _is_error_response(text: str) -> bool:
    """Return True if *text* is an error sentinel from execute_llm_call()."""
    return any(text.startswith(p) for p in _ERROR_PREFIXES)


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

    Returns:
        True if the caller should continue waiting for the next user message.
        False if the caller should continue the tool-execution loop (e.g. role
        changes that trigger LLM calls with tool invocations).
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
                return
            path = str(candidates[-1])
        connector.send_assistant(_load_conversation(mgr, path))

    elif command == "savepoint":
        # payload is the save-point name
        name = payload.strip()
        if not name:
            connector.send_assistant(
                "\u274c Usage: /savepoint <name>"
            )
            return
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
            return
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

    else:
        connector.send_assistant(f"\u274c Unknown control command: {command!r}")
        logger.warning("Unknown control command: %s", command)

    return True


def _handle_role_command(
    payload: str,
    mgr: ConversationManager,
    connector: "Connector",
) -> bool:
    """Handle role load/unload/show commands and rebuild system prompt.

    Returns:
        True if the caller should continue waiting for the next user message.
        False if the caller should continue the tool-execution loop (e.g. role
        changes that trigger LLM calls with tool invocations).

    When a role is loaded or unloaded, the system prompt must be rebuilt
    with the correct tool list, and the LLM must be notified about the change.
    """
    from utils.roles import list_roles, load_role, unload_role, get_active_role
    from utils.prompt import invalidate_cache
    from tools.registry import get_full_system_prompt

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
            # Rebuild the system prompt with the new tool list
            invalidate_cache()
            allowed_tools = role.tools if role.tools else None
            new_system_prompt = get_full_system_prompt(allowed_tools=allowed_tools)
            # Update the session header with the new system prompt
            mgr.session_header = SessionHeader(system_prompt=new_system_prompt)

            # Notify the LLM about the role change by adding it to conversation history
            tool_list = ", ".join(role.tools) if role.tools else "all available tools"
            role_notification = (
                f"\u2705 Role '{role.name}' loaded.\n"
                f"\n"
                f"You are now operating as the {role.name} role.\n"
                f"Available tools: {tool_list}\n"
                f"\n"
                f"{role.summary()}"
            )
            # Add to conversation history so the LLM sees the role change
            mgr.add_user(role_notification)
            # Also send to TUI for user visibility
            connector.send_assistant(role_notification)
            logger.info("Role '%s' loaded, system prompt rebuilt and LLM notified", role.name)

            # Trigger an LLM call so the assistant can acknowledge the role change
            # and confirm its new capabilities. This updates the LLM's context
            # to match the new system prompt.
            try:
                mgr.prune_task_messages(MAX_CONVERSATION_LENGTH)
                assistant_response = execute_llm_call(
                    conversation=[],
                    system_override=mgr.system_for_api(),
                    messages_override=mgr.messages_for_api(),
                )

                # If the LLM produces a plain response (not a tool call),
                # add it to the conversation and send to TUI
                tool_invocations = extract_tool_invocations(assistant_response)
                if not tool_invocations:
                    mgr.add_assistant(assistant_response)
                    connector.send_assistant(
                        f"\n\u2705 Assistant response:\n{assistant_response}"
                    )
                    logger.info("Role '%s' acknowledged by LLM", role.name)
                    return True
                else:
                    # If the LLM tries to call tools immediately, we need to
                    # continue the tool execution loop. Add the assistant's
                    # response to the conversation and signal the caller to
                    # continue with tool execution.
                    mgr.add_assistant(assistant_response)
                    logger.info(
                        "Role '%s' triggered tool calls immediately: %s",
                        role.name,
                        [name for name, _ in tool_invocations],
                    )
                    return False  # Continue tool loop
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to get LLM acknowledgment for role '%s': %s", role.name, exc)
                connector.send_assistant(
                    f"\u274c Failed to notify LLM of role change: {exc}"
                )
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
        # Rebuild the system prompt without role restrictions
        invalidate_cache()
        new_system_prompt = get_full_system_prompt(allowed_tools=None)
        mgr.session_header = SessionHeader(system_prompt=new_system_prompt)

        # Notify the LLM about the role change
        role_notification = (
            f"\u2705 Role '{rname}' unloaded. Defaults restored.\n"
            f"You now have access to all available tools."
        )
        mgr.add_user(role_notification)
        connector.send_assistant(role_notification)
        logger.info("Role '%s' unloaded, system prompt rebuilt", rname)

        # Trigger an LLM call to acknowledge the role change
        try:
            mgr.prune_task_messages(MAX_CONVERSATION_LENGTH)
            assistant_response = execute_llm_call(
                conversation=[],
                system_override=mgr.system_for_api(),
                messages_override=mgr.messages_for_api(),
            )

            tool_invocations = extract_tool_invocations(assistant_response)
            if not tool_invocations:
                mgr.add_assistant(assistant_response)
                connector.send_assistant(
                    f"\n\u2705 Assistant response:\n{assistant_response}"
                )
                logger.info("Role '%s' acknowledged by LLM", rname)
                return True
            else:
                mgr.add_assistant(assistant_response)
                logger.info(
                    "Role '%s' triggered tool calls immediately: %s",
                    rname,
                    [name for name, _ in tool_invocations],
                )
                return False  # Continue tool loop
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get LLM acknowledgment for role '%s': %s", rname, exc)
            connector.send_assistant(
                f"\u274c Failed to notify LLM of role change: {exc}"
            )
            return True

    connector.send_assistant(
        f"\u274c Unknown /role sub-command: {sub!r}\n"
        "Use: /role list | /role load <name> | /role show | /role unload"
    )
    return True


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

    Uses ConversationManager to maintain a session-header cache point:
    the system prompt and documentation files are sent with cache_control
    markers so Claude can reuse its server-side KV-cache across turns,
    reducing latency and token cost for the stable prefix.

    Exits cleanly when the connector is shut down.
    """
    # Determine the active role's tool restrictions (if any)
    from utils.roles import get_active_role
    active_role = get_active_role()
    allowed_tools = active_role.tools if active_role and active_role.tools else None

    system_prompt = get_full_system_prompt(allowed_tools=allowed_tools)
    header = SessionHeader(system_prompt=system_prompt)
    mgr = ConversationManager(header)

    logger.info(
        "AgentLoop started with session-header caching, "
        "waiting for user messages."
    )

    while True:
        # ----------------------------------------------------------------
        # Wait for the next user turn or control command
        # ----------------------------------------------------------------
        user_msg = connector.receive_user_blocking()
        if user_msg is None:
            logger.info("AgentLoop: connector shut down, exiting.")
            break

        # Handle control commands (save / load / reset) before touching the LLM
        if user_msg.get("role") == "control":
            continue_tool_loop = _handle_control(user_msg, mgr, connector)
            if continue_tool_loop:
                continue
            # If _handle_control returned False, it means a role change triggered
            # an LLM call with tool invocations. We need to continue the tool
            # execution loop to process those invocations.
            # Fall through to the tool execution loop below.
        else:
            mgr.add_user(user_msg["content"])

        # ----------------------------------------------------------------
        # Inner loop: LLM -> tools -> LLM ... until plain reply
        # ----------------------------------------------------------------
        while True:
            try:
                mgr.prune_task_messages(MAX_CONVERSATION_LENGTH)

                assistant_response = execute_llm_call(
                    conversation=[],
                    system_override=mgr.system_for_api(),
                    messages_override=mgr.messages_for_api(),
                )

                # Propagate provider-level errors directly to the TUI
                if _is_error_response(assistant_response):
                    connector.send_assistant(assistant_response)
                    break

                tool_invocations = extract_tool_invocations(assistant_response)

                if DEBUG_MODE:
                    logger.debug("Assistant response:\n%s", assistant_response)
                    logger.debug("Tool invocations: %s", tool_invocations)

                if not tool_invocations:
                    # Plain LLM reply - publish and wait for next user turn
                    connector.send_assistant(assistant_response)
                    mgr.add_assistant(assistant_response)
                    break

                # Record assistant's tool-call message *before* tool results
                # so the LLM sees its own invocation in context.
                mgr.add_assistant(assistant_response)

                # Execute each tool and feed results back into the conversation
                for name, args in tool_invocations:
                    if name not in TOOL_REGISTRY:
                        logger.error("Unknown tool after registry check: %s", name)
                        continue

                    # Verbose-mode approval: ask the TUI before executing
                    if VERBOSE_MODE:
                        connector.request_approval(name, args)
                        approval = connector.receive_approval_response_blocking(
                            timeout=60
                        )
                        if approval is None or not approval.get("approved", False):
                            logger.info(
                                "Tool %s rejected by user (verbose mode)", name
                            )
                            denied_result = {
                                "error": "Tool execution rejected by user.",
                                "tool_name": name,
                                "success": False,
                            }
                            mgr.add_user(
                                f"tool_result({json.dumps(denied_result)})"
                            )
                            # IMPORTANT: We must notify the connector so the user sees the rejection
                            connector.send_assistant(f"Tool {name} was rejected by user.")
                            continue

                    tool_fn = TOOL_REGISTRY[name]
                    try:
                        if DEBUG_MODE:
                            logger.debug(
                                "Executing tool %s args=%s", name, args
                            )

                        result = execute_tool_safely(name, tool_fn, args)

                        if DEBUG_MODE:
                            logger.debug("Tool %s result: %s", name, result)

                        tool_result_str = f"tool_result({json.dumps(result, ensure_ascii=False)})"
                        mgr.add_user(tool_result_str)

                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Tool execution failed for %s: %s", name, exc
                        )
                        error_result = {
                            "error": f"Tool execution failed: {exc}",
                            "tool_name": name,
                            "success": False,
                        }
                        error_result_str = f"tool_result({json.dumps(error_result)})"
                        mgr.add_user(error_result_str)

            except Exception as exc:  # noqa: BLE001
                logger.error("Agent inner loop error: %s", exc)
                connector.send_assistant(
                    f"\U0001f4a5 Internal error: {exc}\n"
                    "Please try again with a shorter or simpler request."
                )
                break
