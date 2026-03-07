#!/usr/bin/python

# Implementation of The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code
# https://www.mihaileric.com/The-Emperor-Has-No-Clothes/
# by Joerg Kulbartz joerg@kulbartz.de

# ---------------------------------------------------------------------------
# Entry point shim - all logic has been moved to the modular package layout:
#
#   utils/      - config, rate_limiter, security, llm
#   tools/      - one file per tool + registry
#   frontend/   - connector, agent_loop
#
# This file is kept for backward compatibility: `python ntCode.py` still works.
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

load_dotenv()

from frontend.agent_loop import run_coding_agent_loop  # noqa: E402


if __name__ == "__main__":
    run_coding_agent_loop()
