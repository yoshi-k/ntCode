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
    logger,
)
from utils.llm import execute_llm_call, SessionHeader, ConversationManager
from utils.connector import Connector
from tools.registry import TOOL_REGISTRY, get_full_system_prompt, execute_tool_safely

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

def extract_tool_invocations(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Return list of (tool_name, args) for every ``tool: NAME({...})`` line in *text*.

    Lines that do not match the format, contain unknown tool names, or carry
    malformed JSON are logged as warnings and silently skipped.
    """
    invocations: List[Tuple[str, Dict[str, Any]]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("tool:"):
            continue
        try:
            after = line[len("tool:"):].strip()

            if "(" not in after:
                logger.warning("Invalid tool invocation (missing parentheses): %s", line)
                continue

            name, rest = after.split("(", 1)
            name = name.strip()

            if not name:
                logger.warning("Invalid tool invocation (empty tool name): %s", line)
                continue

            if not rest.endswith(")"):
                logger.warning(
                    "Invalid tool invocation (missing closing parenthesis): %s", line
                )
                continue

            json_str = rest[:-1].strip()

            if not json_str:
                args: Dict[str, Any] = {}
            else:
                try:
                    args = json.loads(json_str)
                    if not isinstance(args, dict):
                        logger.warning(
                            "Tool args must be a dict, got %s: %s",
                            type(args).__name__,
                            line,
                        )
                        continue
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Invalid JSON in tool invocation '%s': %s", json_str, exc
                    )
                    continue

            if name not in TOOL_REGISTRY:
                logger.warning("Unknown tool name: %s", name)
                continue

            invocations.append((name, args))
            logger.debug("Parsed tool invocation: %s args=%s", name, args)

        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error parsing tool invocation '%s': %s", line, exc)
            continue

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
) -> None:
    """Execute a control command and publish a status reply via *connector*."""
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

    else:
        connector.send_assistant(f"\u274c Unknown control command: {command!r}")
        logger.warning("Unknown control command: %s", command)


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
    system_prompt = get_full_system_prompt()
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
            _handle_control(user_msg, mgr, connector)
            continue

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

                        mgr.add_user(
                            f"tool_result({json.dumps(result, ensure_ascii=False)})"
                        )

                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Tool execution failed for %s: %s", name, exc
                        )
                        error_result = {
                            "error": f"Tool execution failed: {exc}",
                            "tool_name": name,
                            "success": False,
                        }
                        mgr.add_user(
                            f"tool_result({json.dumps(error_result)})"
                        )

            except Exception as exc:  # noqa: BLE001
                logger.error("Agent inner loop error: %s", exc)
                connector.send_assistant(
                    f"\U0001f4a5 Internal error: {exc}\n"
                    "Please try again with a shorter or simpler request."
                )
                break
