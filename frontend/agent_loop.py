"""TUI frontend for ntCode.

This module owns all terminal-interaction code:
  - printing the welcome banner
  - reading user input via ``input()``
  - displaying assistant responses with ANSI colours
  - starting the :func:`~utils.agent.run_agent` loop in a background thread

It communicates with the agent *exclusively* through a
:class:`~utils.connector.Connector` instance - it never imports
``execute_llm_call``, ``TOOL_REGISTRY``, or any other agent internals.
"""

import threading

from utils.config import (
    DEBUG_MODE,
    VERBOSE_MODE,
    YOU_COLOR,
    ASSISTANT_COLOR,
    RESET_COLOR,
    logger,
)

from tools.registry import TOOL_REGISTRY, get_full_system_prompt  # debug banner + /prompt
from utils.connector import Connector
from utils.agent import run_agent


# ---------------------------------------------------------------------------
# Slash-command table
# ---------------------------------------------------------------------------

_HELP_TEXT = """\
Available commands:
  /help                  Show this help message
  /quit  or  /exit       Exit ntCode
  /reset                 Clear conversation history (keep system prompt)
  /save  [file]          Save conversation to file (default: saves/conversation-<timestamp>.json)
  /load  [file]          Load conversation from file
  /prompt                Show the current system prompt
  /tools                 List available tools
  /provider              Show the current LLM provider
  /provider list         List all available provider aliases
  /provider <alias>      Switch provider  (e.g. /provider ollama)
  /provider <alias>/<model>  Switch provider and model  (e.g. /provider openai/gpt-4o)
"""


def _handle_provider_command(arg: str, connector: Connector) -> None:
    """Handle all /provider sub-commands locally (no agent round-trip needed).

    * ``/provider``          — print the active provider description.
    * ``/provider list``     — print all known aliases.
    * ``/provider <spec>``   — switch; spec may be ``alias`` or ``alias/model``.
    """
    from utils.llm import list_providers, current_provider_name, switch_provider

    arg = arg.strip()

    if not arg:
        print(f"Current provider: {current_provider_name()}")
        return

    if arg.lower() == "list":
        print("Available provider aliases:")
        for alias in list_providers():
            print(f"  {alias}")
        return

    # Switch request
    try:
        status = switch_provider(arg)
        print(status)
    except ValueError as exc:
        print(f"❌ {exc}")
    except Exception as exc:
        print(f"❌ Failed to switch provider: {exc}")


def _handle_slash_command(cmd: str, connector: Connector) -> bool:
    """Parse and dispatch a slash command entered by the user.

    Returns True if the main loop should exit, False otherwise.
    The function either prints locally (read-only info commands) or sends a
    control message to the agent (state-mutating commands) and waits for the
    agent's acknowledgement reply.
    """
    parts = cmd.strip().split(None, 1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name in ("/quit", "/exit"):
        return True  # signal the loop to break

    elif name == "/help":
        print(_HELP_TEXT)

    elif name == "/tools":
        print("Available tools: " + ", ".join(TOOL_REGISTRY.keys()))

    elif name == "/prompt":
        print(get_full_system_prompt())

    elif name == "/reset":
        connector.send_control("reset")
        _wait_and_print_reply(connector)

    elif name == "/save":
        connector.send_control("save", arg or None)
        _wait_and_print_reply(connector)

    elif name == "/load":
        connector.send_control("load", arg or None)
        _wait_and_print_reply(connector)

    elif name == "/provider":
        _handle_provider_command(arg, connector)

    else:
        print(f"Unknown command: {name}  (type /help for a list)")

    return False


def _wait_and_print_reply(connector: Connector, color: str = "", reset: str = "") -> None:
    """Block until the agent sends a reply and print it."""
    msg = connector.receive_assistant_blocking(timeout=10)
    if msg:
        print(f"{ASSISTANT_COLOR}{msg['content']}{RESET_COLOR}")


def run_coding_agent_loop() -> None:
    """Entry point called by ``ntCode.py``.

    Starts the agent in a background thread and runs the TUI input loop in
    the main thread.  The two sides communicate only through a ``Connector``.
    """
    # ------------------------------------------------------------------ #
    # Welcome banner
    # ------------------------------------------------------------------ #
    if DEBUG_MODE:
        print("=== ntCode AI Assistant ===")
        print("Available tools:", ", ".join(TOOL_REGISTRY.keys()))
        print(f"Debug Mode: {DEBUG_MODE}, Verbose Mode: {VERBOSE_MODE}")
        print(f"Logging: {logger.handlers}")
        print()
    else:
        print("ntCode AI Assistant - Ready!")
        print()

    # ------------------------------------------------------------------ #
    # Wire up connector and start the agent thread
    # ------------------------------------------------------------------ #
    connector = Connector()

    agent_thread = threading.Thread(
        target=run_agent,
        args=(connector,),
        name="ntcode-agent",
        # daemon=True means Python won't wait for this thread on exit.
        # Clean shutdown is handled explicitly: connector.shutdown() in the
        # finally block unblocks receive_user_blocking() so the thread exits
        # gracefully before the process ends.
        daemon=True,
    )
    agent_thread.start()
    logger.debug("Agent thread started.")

    # ------------------------------------------------------------------ #
    # TUI input loop
    # ------------------------------------------------------------------ #
    try:
        while True:
            # ---------------------------------------------------------- #
            # Read user input
            # ---------------------------------------------------------- #
            try:
                user_input = input(f"{YOU_COLOR}You:{RESET_COLOR} ").strip()
            except (KeyboardInterrupt, EOFError):
                print()  # newline after ^C / ^D
                break

            if not user_input:
                continue

            # ---------------------------------------------------------- #
            # Slash commands are handled locally / via control messages
            # ---------------------------------------------------------- #
            if user_input.startswith("/"):
                should_quit = _handle_slash_command(user_input, connector)
                if should_quit:
                    break
                continue

            # ---------------------------------------------------------- #
            # Forward user message to the agent and wait for the reply
            # ---------------------------------------------------------- #
            connector.send_user(user_input)

            # The agent may take a while (LLM call + multiple tool rounds).
            # While waiting we also service any verbose-mode approval prompts.
            response_msg = None
            while response_msg is None:
                if VERBOSE_MODE:
                    # Short-timeout poll so we can interleave approval prompts
                    response_msg = connector.receive_assistant_blocking(timeout=0.1)
                    if response_msg is None:
                        # Check for a pending approval request
                        req = connector.receive_approval_request_blocking(timeout=0.05)
                        if req is not None:
                            tool_name = req["tool_name"]
                            args = req["args"]
                            print(
                                f"\n{ASSISTANT_COLOR}[VERBOSE] Tool request:{RESET_COLOR} "
                                f"{tool_name}({args})"
                            )
                            try:
                                answer = input("  Approve? [y/N] ").strip().lower()
                            except (KeyboardInterrupt, EOFError):
                                answer = "n"
                            connector.send_approval_response(answer in ("y", "yes"))
                else:
                    response_msg = connector.receive_assistant_blocking()

            if response_msg is None:
                # Connector was shut down (e.g. agent crashed)
                logger.warning(
                    "TUI: received None from connector - agent may have exited."
                )
                break

            content = response_msg["content"]

            # Distinguish error sentinels (prefixed with emoji) from normal replies
            if content.startswith(
                (
                    "\u23f1\ufe0f",  # timeout
                    "\U0001f6ab",  # rate limit
                    "\U0001f310",  # connection
                    "\U0001f511",  # auth
                    "\u274c",  # API error
                    "\U0001f4a5",  # unexpected
                )
            ):
                print(f"{ASSISTANT_COLOR}Error:{RESET_COLOR} {content}")
            else:
                print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {content}")

    finally:
        # connector.shutdown() unblocks the agent's receive_user_blocking()
        # so it exits cleanly before the daemon thread is reaped.
        connector.shutdown()
        agent_thread.join(timeout=2)
        logger.debug("Agent thread joined.")
        print("Goodbye!")
