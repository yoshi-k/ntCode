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
from tools.registry import TOOL_REGISTRY  # only for the debug banner
from utils.connector import Connector
from utils.agent import run_agent


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
        daemon=True,  # exits automatically when the main thread exits
    )
    agent_thread.start()
    logger.debug("Agent thread started.")

    # ------------------------------------------------------------------ #
    # TUI input loop
    # ------------------------------------------------------------------ #
    try:
        while True:
            try:
                user_input = input(f"{YOU_COLOR}You:{RESET_COLOR} ").strip()
            except (KeyboardInterrupt, EOFError):
                print()  # newline after ^C / ^D
                break

            if not user_input:
                continue

            # Forward user message to the agent
            connector.send_user(user_input)

            # Block until the agent publishes its reply.
            # The agent may take a while (LLM call + tool rounds).
            response_msg = connector.receive_assistant_blocking()

            if response_msg is None:
                # Connector was shut down (e.g. agent crashed)
                logger.warning("TUI: received None from connector - agent may have exited.")
                break

            content = response_msg["content"]

            # Distinguish error sentinels (prefixed with emoji) from normal replies
            if content.startswith((
                "\u23f1\ufe0f",   # timeout
                "\U0001f6ab",     # rate limit
                "\U0001f310",     # connection
                "\U0001f511",     # auth
                "\u274c",         # API error
                "\U0001f4a5",     # unexpected
            )):
                print(f"{ASSISTANT_COLOR}Error:{RESET_COLOR} {content}")
            else:
                print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {content}")

    finally:
        # Cleanly signal the agent thread to stop
        connector.shutdown()
        agent_thread.join(timeout=2)
        logger.debug("Agent thread joined.")
        print("Goodbye!")
