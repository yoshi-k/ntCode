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
from typing import Any, Dict, List, Optional, Tuple

from utils.config import (
    DEBUG_MODE,
    VERBOSE_MODE,
    MAX_CONVERSATION_LENGTH,
    logger,
)
from utils.llm import execute_llm_call
from utils.connector import Connector
from tools.registry import TOOL_REGISTRY, get_full_system_prompt, execute_tool_safely

# Default directory used when the user does not supply a path for save/load.
_DEFAULT_SAVE_DIR = "saves"


def _default_save_path() -> str:
    """Return a timestamped path inside the saves/ folder."""
    import datetime
    import pathlib
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
# Conversation pruning helper
# ---------------------------------------------------------------------------

def _prune_conversation(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the system prompt plus the most recent *MAX_CONVERSATION_LENGTH* messages."""
    system_msgs = [m for m in conversation if m["role"] == "system"]
    non_system = [m for m in conversation if m["role"] != "system"]

    if len(non_system) > MAX_CONVERSATION_LENGTH:
        logger.info(
            "Conversation too long (%d messages), pruning to last %d",
            len(non_system),
            MAX_CONVERSATION_LENGTH,
        )
        non_system = non_system[-MAX_CONVERSATION_LENGTH:]

    return system_msgs + non_system


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

def _save_conversation(conversation: List[Dict[str, Any]], path: str) -> str:
    """Serialise *conversation* to a JSON file at *path*.

    Returns a human-readable status string.
    """
    try:
        abs_path = os.path.abspath(path)
        with open(abs_path, "w", encoding="utf-8") as fh:
            json.dump(conversation, fh, ensure_ascii=False, indent=2)
        logger.info("Conversation saved to %s (%d messages)", abs_path, len(conversation))
        return f"Conversation saved to {abs_path} ({len(conversation)} messages)."
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save conversation: %s", exc)
        return f"\u274c Failed to save conversation: {exc}"


def _load_conversation(
    path: str, system_prompt: str
) -> Tuple[List[Dict[str, Any]], str]:
    """Load a previously saved conversation from *path*.

    Always re-inserts the current system prompt as the first message so the
    agent uses up-to-date tool descriptions even when loading an old file.

    Returns ``(conversation, status_string)``.
    """
    try:
        abs_path = os.path.abspath(path)
        with open(abs_path, "r", encoding="utf-8") as fh:
            loaded: List[Dict[str, Any]] = json.load(fh)
        # Strip any old system messages and prepend the current one
        non_system = [m for m in loaded if m.get("role") != "system"]
        conversation = [{"role": "system", "content": system_prompt}] + non_system
        logger.info(
            "Conversation loaded from %s (%d messages)", abs_path, len(conversation)
        )
        return conversation, f"Conversation loaded from {abs_path} ({len(non_system)} messages restored)."
    except FileNotFoundError:
        msg = f"\u274c File not found: {path}"
        logger.warning(msg)
        return None, msg
    except Exception as exc:  # noqa: BLE001
        msg = f"\u274c Failed to load conversation: {exc}"
        logger.error(msg)
        return None, msg


# ---------------------------------------------------------------------------
# Control-message handler
# ---------------------------------------------------------------------------

def _handle_control(
    msg: Dict[str, Any],
    conversation: List[Dict[str, Any]],
    connector: "Connector",
) -> List[Dict[str, Any]]:
    """Execute a control command and publish a status reply.

    Returns the (possibly replaced) conversation list.
    """
    command = msg.get("command", "")
    payload = msg.get("payload", "") or ""
    system_prompt = get_full_system_prompt()

    if command == "reset":
        conversation.clear()
        conversation.append({"role": "system", "content": system_prompt})
        connector.send_assistant("Conversation reset. Starting fresh!")
        logger.info("Conversation reset by user.")

    elif command == "save":
        path = payload or _default_save_path()
        status = _save_conversation(conversation, path)
        connector.send_assistant(status)

    elif command == "load":
        path = payload or _DEFAULT_SAVE_DIR
        # If path resolves to a directory, pick the most-recently modified .json
        import pathlib
        p = pathlib.Path(path)
        if p.is_dir():
            candidates = sorted(p.glob("*.json"), key=lambda f: f.stat().st_mtime)
            if not candidates:
                connector.send_assistant(f"\u274c No saved conversations found in {path}/")
                return conversation
            path = str(candidates[-1])
        new_conv, status = _load_conversation(path, system_prompt)
        if new_conv is not None:
            conversation.clear()
            conversation.extend(new_conv)
        connector.send_assistant(status)

    else:
        connector.send_assistant(f"\u274c Unknown control command: {command!r}")
        logger.warning("Unknown control command: %s", command)

    return conversation


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

    Exits cleanly when the connector is shut down.
    """
    conversation: List[Dict[str, Any]] = [
        {"role": "system", "content": get_full_system_prompt()}
    ]

    logger.info("AgentLoop started, waiting for user messages.")

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
            _handle_control(user_msg, conversation, connector)
            continue

        conversation.append({"role": "user", "content": user_msg["content"]})

        # ----------------------------------------------------------------
        # Inner loop: LLM -> tools -> LLM ... until plain reply
        # ----------------------------------------------------------------
        while True:
            try:
                conversation = _prune_conversation(conversation)

                assistant_response = execute_llm_call(conversation)

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
                    conversation.append(
                        {"role": "assistant", "content": assistant_response}
                    )
                    break

                # Record assistant's tool-call message *before* tool results
                # so the LLM sees its own invocation in context.
                conversation.append(
                    {"role": "assistant", "content": assistant_response}
                )

                # Execute each tool and feed results back into the conversation
                for name, args in tool_invocations:
                    if name not in TOOL_REGISTRY:
                        logger.error("Unknown tool after registry check: %s", name)
                        continue

                    # Verbose-mode approval: ask the TUI before executing
                    if VERBOSE_MODE:
                        connector.request_approval(name, args)
                        approval = connector.receive_approval_response_blocking(timeout=60)
                        if approval is None or not approval.get("approved", False):
                            logger.info("Tool %s rejected by user (verbose mode)", name)
                            denied_result = {
                                "error": "Tool execution rejected by user.",
                                "tool_name": name,
                                "success": False,
                            }
                            conversation.append(
                                {
                                    "role": "user",
                                    "content": f"tool_result({json.dumps(denied_result)})",
                                }
                            )
                            continue

                    tool_fn = TOOL_REGISTRY[name]
                    try:
                        if DEBUG_MODE:
                            logger.debug("Executing tool %s args=%s", name, args)

                        result = execute_tool_safely(name, tool_fn, args)

                        if DEBUG_MODE:
                            logger.debug("Tool %s result: %s", name, result)

                        conversation.append(
                            {
                                "role": "user",
                                "content": f"tool_result({json.dumps(result, ensure_ascii=False)})",
                            }
                        )

                    except Exception as exc:  # noqa: BLE001
                        logger.error("Tool execution failed for %s: %s", name, exc)
                        error_result = {
                            "error": f"Tool execution failed: {exc}",
                            "tool_name": name,
                            "success": False,
                        }
                        conversation.append(
                            {
                                "role": "user",
                                "content": f"tool_result({json.dumps(error_result)})",
                            }
                        )

            except Exception as exc:  # noqa: BLE001
                logger.error("Agent inner loop error: %s", exc)
                connector.send_assistant(
                    f"\U0001f4a5 Internal error: {exc}\n"
                    "Please try again with a shorter or simpler request."
                )
                break
