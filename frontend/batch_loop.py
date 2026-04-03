"""Batch frontend for ntCode.

Reads instructions from a file (one non-empty line = one prompt) and writes
all responses to an output file.  No terminal interaction whatsoever.

Usage (via ntCode.py)::

    python ntCode.py --batch infile.txt --out outfile.txt

Input file format
-----------------
* One instruction per line.
* Blank lines and lines starting with ``#`` are skipped.
* Slash-commands (``/reset``, ``/save``, ``/savepoint``, …) work exactly as
  in the TUI because both frontends share :func:`frontend.common.dispatch_line`.

Output file format
------------------
For each processed line the output file receives::

    === [N] You: <instruction> ===
    <assistant response>
    (blank line)

If a line produces only a local reply (e.g. ``/help``) the same structure is
used with the local text as the response.

VERBOSE_MODE
------------
Tool-approval prompts cannot be answered interactively in batch mode.
All approval requests are **auto-approved** and a warning is written both to
the log and to the output file.
"""

from __future__ import annotations

import sys
import threading
from typing import Optional

from utils.config import VERBOSE_MODE, logger
from utils.connector import Connector
from utils.agent import run_agent
from frontend.common import DispatchResult, dispatch_line, is_error_response


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_instructions(path: str) -> list[str]:
    """Read *path* and return non-blank, non-comment lines in order."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        print(f"❌ Batch input file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"❌ Cannot read batch input file: {exc}", file=sys.stderr)
        sys.exit(1)

    return [
        line.rstrip("\n")
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _wait_for_reply(
    connector: Connector,
    timeout: Optional[float] = None,
) -> str:
    """Block until the agent sends a reply; auto-approve any tool requests.

    Returns the reply content string, or an empty string if the connector
    shuts down before a reply arrives.
    """
    while True:
        if VERBOSE_MODE:
            # Short-timeout poll so we can drain approval requests
            msg = connector.receive_assistant_blocking(timeout=0.1)
            if msg is not None:
                return msg["content"]
            # Service any pending approval request
            req = connector.receive_approval_request_blocking(timeout=0.05)
            if req is not None:
                logger.warning(
                    "Batch mode: auto-approving tool request for %s",
                    req["tool_name"],
                )
                connector.send_approval_response(True)
        else:
            msg = connector.receive_assistant_blocking(timeout=timeout)
            if msg is None:
                return ""  # shutdown or timeout
            return msg["content"]


def _write(fh, text: str) -> None:
    """Write *text* to *fh* and flush immediately."""
    fh.write(text)
    fh.flush()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_batch_loop(infile: str, outfile: str) -> None:
    """Process *infile* instruction-by-instruction and write results to *outfile*.

    Parameters
    ----------
    infile :
        Path to the instruction file (one prompt per non-blank, non-comment line).
    outfile :
        Path to the output file.  Created or overwritten.
    """
    instructions = _read_instructions(infile)
    if not instructions:
        print("⚠️  Batch input file is empty or contains only comments.", file=sys.stderr)
        sys.exit(0)

    logger.info(
        "Batch mode: %d instruction(s) from %s -> %s",
        len(instructions),
        infile,
        outfile,
    )

    # ------------------------------------------------------------------ #
    # Wire up connector and start the agent thread
    # ------------------------------------------------------------------ #
    connector = Connector()

    agent_thread = threading.Thread(
        target=run_agent,
        args=(connector,),
        name="ntcode-agent-batch",
        daemon=True,
    )
    agent_thread.start()
    logger.debug("Batch agent thread started.")

    # ------------------------------------------------------------------ #
    # Process instructions
    # ------------------------------------------------------------------ #
    try:
        with open(outfile, "w", encoding="utf-8") as out:
            for idx, line in enumerate(instructions, start=1):
                _write(out, f"=== [{idx}/{len(instructions)}] You: {line} ===\n")
                logger.info("Batch [%d/%d]: %s", idx, len(instructions), line)

                outcome = dispatch_line(line, connector)

                if outcome.result == DispatchResult.QUIT:
                    _write(out, "(batch terminated by /quit)\n\n")
                    logger.info("Batch: /quit encountered at instruction %d, stopping.", idx)
                    break

                if outcome.result == DispatchResult.LOCAL:
                    # e.g. /help, /tools, /provider — reply is already in outcome.reply
                    reply = outcome.reply or "(no output)"
                    _write(out, reply + "\n\n")
                    continue

                if outcome.result == DispatchResult.CONTROL:
                    # e.g. /reset, /save, /savepoint — agent sends an ack
                    reply = _wait_for_reply(connector, timeout=30)
                    _write(out, (reply or "(no acknowledgement)") + "\n\n")
                    continue

                # DispatchResult.USER — full LLM round-trip
                reply = _wait_for_reply(connector)
                if not reply:
                    _write(out, "(no response — connector shut down)\n\n")
                    logger.warning("Batch: no response for instruction %d.", idx)
                    break

                if is_error_response(reply):
                    _write(out, f"Error: {reply}\n\n")
                    logger.warning("Batch: error response for instruction %d: %s", idx, reply)
                else:
                    _write(out, reply + "\n\n")

        print(f"✅ Batch complete. Output written to {outfile}")
        logger.info("Batch complete. Output written to %s", outfile)

    except KeyboardInterrupt:
        print("\nBatch interrupted.", file=sys.stderr)
        logger.warning("Batch mode interrupted by user.")

    finally:
        connector.shutdown()
        agent_thread.join(timeout=2)
        logger.debug("Batch agent thread joined.")
