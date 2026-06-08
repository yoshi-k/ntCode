"""Unified Task Loop frontend for ntCode.

Processes a sequence of tasks from various input formats (Batch or Todo).

Supported Formats:
1. Batch: One instruction per line. (Persistent context)
2. Todo: Structured Markdown with Title, Role, and Prompt. (Fresh context per task)

Usage:
    python ntCode.py --batch tasks.txt --out results.txt
    python ntCode.py --todo tasks.md --out results.txt
"""

from __future__ import annotations

import sys
import threading
import re
from dataclasses import dataclass
from typing import Optional, List, Protocol

from utils.config import VERBOSE_MODE, logger
from utils.connector import Connector
from utils.agent import run_agent
from utils.roles import load_role, unload_role
from frontend.common import DispatchResult, dispatch_line, is_error_response


@dataclass
class Task:
    prompt: str
    title: str = "Instruction"
    role: Optional[str] = None
    fresh_context: bool = True


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_batch_file(path: str) -> List[Task]:
    """Parse simple line-based file. Uses persistent context (fresh_context=False)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception as e:
        print(f"❌ Error reading batch file: {e}", file=sys.stderr)
        sys.exit(1)

    return [
        Task(prompt=line.rstrip("\n"), title=line.strip(), fresh_context=False)
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _parse_todo_file(path: str) -> List[Task]:
    """Parse structured Markdown file. Uses fresh context (fresh_context=True)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception as e:
        print(f"❌ Error reading todo file: {e}", file=sys.stderr)
        sys.exit(1)

    tasks = []
    chunks = re.split(r'(?=#\s*TODO:)', content)

    for chunk in chunks:
        if not chunk.strip():
            continue

        title_match = re.search(r'#\s*TODO:\s*(.*)', chunk)
        if not title_match:
            continue
        title = title_match.group(1).strip()

        role_match = re.search(r'##\s*Role:\s*([^\n]+)', chunk)
        role_name = role_match.group(1).strip() if role_match else None
        if role_name and not role_match:
            logger.warning("Todo parser: Task '%s' missing '## Role: <name>' header. Skipping.", title)
            continue

        lines = chunk.splitlines()
        prompt_lines = []
        role_found = False
        for line in lines:
            if role_found:
                prompt_lines.append(line)
            elif re.match(r'##\s*Role:\s*', line):
                role_found = True
        
        prompt = "\n".join(prompt_lines).strip()
        if not prompt:
            logger.warning("Todo parser: Task '%s' has an empty prompt. Skipping.", title)
            continue

        tasks.append(Task(prompt=prompt, title=title, role=role_name, fresh_context=True))

    return tasks


# ---------------------------------------------------------------------------
# Execution Engine
# ---------------------------------------------------------------------------

def _wait_for_reply(connector: Connector, timeout: Optional[float] = None) -> str:
    """Standardized wait logic for all task modes."""
    while True:
        if VERBOSE_MODE:
            msg = connector.receive_assistant_blocking(timeout=0.1)
            if msg is not None:
                return msg["content"]
            req = connector.receive_approval_request_blocking(timeout=0.05)
            if req is not None:
                logger.warning("Task mode: auto-approving tool request for %s", req["tool_name"])
                connector.send_approval_response(True)
        else:
            msg = connector.receive_assistant_blocking(timeout=timeout)
            if msg is None: return ""
            return msg["content"]


def run_task_loop(tasks: List[Task], outfile: Optional[str] = None) -> None:
    """The core engine that iterates through tasks and manages lifecycle."""
    if not tasks:
        print("⚠️  No valid tasks found.", file=sys.stderr)
        return

    print(f"🚀 Starting Task Loop: {len(tasks)} tasks found.")
    logger.info("Task loop started with %d tasks.", len(tasks))

    try:
        out_fh = open(outfile, "w", encoding="utf-8") if outfile else sys.stdout

        # If any task requires fresh context, we must manage the lifecycle per-task.
        # If ALL tasks are persistent, we use one connector for all.
        all_persistent = all(not t.fresh_context for t in tasks)

        if all_persistent:
            connector = Connector()
            agent_thread = threading.Thread(target=run_agent, args=(connector,), name="ntcode-agent-persistent", daemon=True)
            agent_thread.start()
        else:
            connector = None
            agent_thread = None

        for idx, task in enumerate(tasks, start=1):
            task_desc = task.title
            if task.role:
                task_desc += f" (Role: {task.role})"
            
            print(f"\n[Task {idx}/{len(tasks)}] {task_desc}")
            if outfile: 
                out_fh.write(f"=== [{idx}/{len(tasks)}] TASK: {task_desc} ===\n")

            # Lifecycle management for fresh context tasks
            current_connector = connector
            current_agent_thread = agent_thread

            if task.fresh_context:
                current_connector = Connector()
                current_agent_thread = threading.Thread(target=run_agent, args=(current_connector,), name="ntcode-agent-fresh", daemon=True)
                current_agent_thread.start()

            try:
                if task.role:
                    load_role(task.role)
                
                outcome = dispatch_line(task.prompt, current_connector)

                if outcome.result == DispatchResult.QUIT:
                    print("Stopping: /quit encountered.")
                    break

                if outcome.result == DispatchResult.LOCAL:
                    reply = outcome.reply or "(no output)"
                    _write_to_out(out_fh, reply, outfile)
                    continue

                if outcome.result == DispatchResult.CONTROL:
                    reply = _wait_for_reply(current_connector, timeout=30)
                    _write_to_out(out_fh, (reply or "(no acknowledgement)"), outfile)
                    continue

                # Full LLM round-trip
                reply = _wait_for_reply(current_connector)

                if not reply:
                    error_msg = "⚠️ No response from agent (connector shutdown)."
                    print(error_msg)
                    if outfile: out_fh.write(error_msg + "\n\n")
                    break

                if is_error_response(reply):
                    print(f"Error: {reply}")
                    if outfile: out_fh.write(f"Error: {reply}\n\n")
                else:
                    _write_to_out(out_fh, reply, outfile)
                    if not outfile: print(f"✅ Task Complete. Response snippet: {reply[:100]}...")

            except Exception as e:
                error_msg = f"❌ Task execution failed: {e}"
                print(error_msg)
                if outfile: out_fh.write(error_msg + "\n\n")
            finally:
                if task.role:
                    unload_role()
                
                if task.fresh_context:
                    current_connector.shutdown()
                    current_agent_thread.join(timeout=2)

        # Cleanup persistent resources
        if all_persistent:
            connector.shutdown()
            agent_thread.join(timeout=2)

        if outfile:
            out_fh.close()
            print(f"\n✅ Task loop complete. Results written to {outfile}")
        else:
            print("\n✅ Task loop complete.")

    except KeyboardInterrupt:
        print("\nTask loop interrupted by user.")
    except Exception as e:
        print(f"\n❌ Fatal error in task loop: {e}")


def _write_to_out(fh, text: str, outfile_path: Optional[str]) -> None:
    """Helper to write to file or stdout."""
    if outfile_path:
        fh.write(text + "\n\n")
        fh.flush()
    else:
        print(text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_batch_mode(infile: str, outfile: str) -> None:
    tasks = _parse_batch_file(infile)
    run_task_loop(tasks, outfile)


def run_todo_mode(todo_file: str, outfile: Optional[str] = None) -> None:
    tasks = _parse_todo_file(todo_file)
    run_task_loop(tasks, outfile)
