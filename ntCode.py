#!/usr/bin/python

# Implementation of The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code
# https://www.mihaileric.com/The-Emperor-Has-No-Clothes/
# by Joerg Kulbartz joerg@kulbartz.de

# ---------------------------------------------------------------------------
# Entry point shim - all logic has been moved to the modular package layout:
#
#   utils/      - config, rate_limiter, security, llm
#   tools/      - one file per tool + registry
#   frontend/   - connector, agent_loop, batch_loop, common
#
# This file is kept for backward compatibility: `python ntCode.py` still works.
#
# Usage:
#   python ntCode.py                              # interactive TUI
#   python ntCode.py --batch infile.txt           # batch mode (output to stdout-like default)
#   python ntCode.py --batch infile.txt --out outfile.txt  # batch mode with output file
#   python ntCode.py --todo todo.md --out output.txt    # todo mode
# ---------------------------------------------------------------------------

import argparse

from dotenv import load_dotenv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ntCode",
        description="ntCode AI coding assistant",
    )
    parser.add_argument(
        "--batch",
        metavar="INFILE",
        default=None,
        help="Run in batch mode: read instructions from INFILE (one per line).",
    )
    parser.add_argument(
        "--todo",
        metavar="TODOFILE",
        default=None,
        help="Run in todo mode: read tasks from a markdown file.",
    )
    parser.add_argument(
        "--out",
        metavar="OUTFILE",
        default="output.txt",
        help="Output file for batch/todo mode (default: output.txt).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.batch:
        from frontend.batch_loop import run_batch_loop  # noqa: E402
        run_batch_loop(args.batch, args.out)
    elif args.todo:
        from frontend.todo_loop import run_todo_loop  # noqa: E402
        run_todo_loop(args.todo, args.out)
    else:
        from frontend.agent_loop import run_coding_agent_loop  # noqa: E402
        run_coding_agent_loop()
