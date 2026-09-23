"""TUI frontend for ntCode.

This module owns all terminal-interaction code:
  - printing the welcome banner
  - reading user input via ``input()``
  - displaying assistant responses with ANSI colours
  - starting the :func:`~utils.agent.run_agent` loop in a background thread

It communicates with the agent *exclusively* through a
:class:`~utils.connector.Connector` instance - it never imports
the provider, ``TOOL_REGISTRY``, or any other agent internals.

All slash-command parsing and dispatch is handled by
:mod:`frontend.common` so that the batch frontend stays in sync.
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

from tools.registry import TOOL_REGISTRY
from utils.connector import Connector
from utils.agent import run_agent
from frontend.common import (
    DispatchResult,
    dispatch_line,
    is_error_response,
)


def _wait_and_print_reply(connector: Connector) -> None:
    """Block until the agent sends a control-command acknowledgement and print it.

    Drains any additional messages that might have been sent during the
    command processing (e.g. LLM acknowledgments).
    """
    msg = connector.receive_assistant_blocking(timeout=10)
    if msg:
        print(f"{ASSISTANT_COLOR}{msg['content']}{RESET_COLOR}")

    while True:
        extra_msg = connector.receive()
        if extra_msg is None:
            break
        print(f"{ASSISTANT_COLOR}{extra_msg['content']}{RESET_COLOR}")


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
                role_name = connector.get_role_name()
                prompt = "You" if role_name == "default" else f"You [{role_name}]"
                user_input = input(f"{YOU_COLOR}{prompt}:{RESET_COLOR} ").strip()
            except (KeyboardInterrupt, EOFError):
                print()  # newline after ^C / ^D
                break

            if not user_input:
                continue

            # ---------------------------------------------------------- #
            # Dispatch via shared common module
            # ---------------------------------------------------------- #
            outcome = dispatch_line(user_input, connector)

            if outcome.result == DispatchResult.QUIT:
                break

            if outcome.result == DispatchResult.LOCAL:
                if outcome.reply:
                    print(f"{ASSISTANT_COLOR}{outcome.reply}{RESET_COLOR}")
                continue

            if outcome.result == DispatchResult.CONTROL:
                _wait_and_print_reply(connector)
                continue

            # DispatchResult.USER — wait for the agent's full response,
            # interleaving VERBOSE approval prompts if needed.
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
                logger.warning(
                    "TUI: received None from connector - agent may have exited."
                )
                break

            content = response_msg["content"]
            if is_error_response(content):
                print(f"{ASSISTANT_COLOR}Error:{RESET_COLOR} {content}")
            else:
                print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {content}")

    finally:
        connector.shutdown()
        agent_thread.join(timeout=2)
        logger.debug("Agent thread joined.")
        print("Goodbye!")
