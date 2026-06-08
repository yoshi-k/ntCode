"""Todo loop frontend for ntCode.

Reads a todo Markdown file, parses tasks with role specifications,
and executes them sequentially with a fresh context for each task.

Usage (via ntCode.py):
    python ntCode.py --todo tasks.md --out results.txt

Todo Markdown Format:
---------------------
# TODO: [Task Title]

## Role: [role_name]

[Task Instructions/Prompt]

---
"""

from __future__ import annotations

import sys
import threading
import re
from dataclasses import dataclass
from typing import Optional, List

from utils.config import VERBOSE_MODE, logger
from utils.connector import Connector
from utils.agent import run_agent
from utils.roles import load_role, unload_role
from frontend.common import DispatchResult, dispatch_line, is_error_response

@dataclass
class TodoTask:
    title: str
    role_name: str
    prompt: str

def _parse_todo_file(path: str) -> List[TodoTask]:
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
        if not role_match:
            logger.warning("Todo parser: Task '%s' missing '## Role: <name>' header. Skipping.", title)
            continue
        role_name = role_match.group(1).strip()

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

        tasks.append(TodoTask(title=title, role_name=role_name, prompt=prompt))

    return tasks

def _wait_for_reply(connector: Connector, timeout: Optional[float] = None) -> str:
    while True:
        if VERBOSE_MODE:
            msg = connector.receive_assistant_blocking(timeout=0.1)
            if msg is not None:
                return msg["content"]
            req = connector.receive_approval_request_blocking(timeout=0.05)
            if req is not None:
                logger.warning("Todo mode: auto-approving tool request for %s", req["tool_name"])
                connector.send_approval_response(True)
        else:
            msg = connector.receive_assistant_blocking(timeout=timeout)
            if msg is None: return ""
            return msg["content"]

def run_todo_loop(todo_file: str, outfile: Optional[str] = None) -> None:
    tasks = _parse_todo_file(todo_file)
    if not tasks:
        print("⚠️  No valid tasks found in the todo file.", file=sys.stderr)
        sys.exit(0)

    print(f"🚀 Starting Todo Loop: {len(tasks)} tasks found.")
    logger.info("Todo mode: %d tasks from %s", len(tasks), todo_file)

    try:
        out_fh = open(outfile, "w", encoding="utf-8") if outfile else sys.stdout

        for idx, task in enumerate(tasks, start=1):
            print(f"\n[Task {idx}/{len(tasks)}] {task.title}")
            if outfile: out_fh.write(f"=== [{idx}/{len(tasks)}] TASK: {task.title} (Role: {task.role_name}) ===\n")

            # New Connector and Agent Thread for every task to ensure fresh context
            connector = Connector()
            agent_thread = threading.Thread(target=run_agent, args=(connector,), name="ntcode-agent-todo", daemon=True)
            agent_thread.start()

            try:
                load_role(task.role_name)
                outcome = dispatch_line(task.prompt, connector)
                
                if outcome.result == DispatchResult.QUIT:
                    print("Stopping: /quit encountered.")
                    break

                reply = _wait_for_reply(connector)

                if not reply:
                    error_msg = "⚠️ No response from agent (connector shutdown)."
                    print(error_msg)
                    if outfile: out_fh.write(error_msg + "\n\n")
                    break

                if is_error_response(reply):
                    print(f"Error: {reply}")
                    if outfile: out_fh.write(f"Error: {reply}\n\n")
                else:
                    if outfile: out_fh.write(reply + "\n\n")
                    print(f"✅ Task Complete. Response snippet: {reply[:100]}...")

            except Exception as e:
                error_msg = f"❌ Task execution failed: {e}"
                print(error_msg)
                if outfile: out_fh.write(error_msg + "\n\n")
            finally:
                unload_role()
                connector.shutdown()
                agent_thread.join(timeout=2)

        if outfile:
            out_fh.close()
            print(f"\n✅ Todo loop complete. Results written to {outfile}")
        else:
            print("\n✅ Todo loop complete.")

    except KeyboardInterrupt:
        print("\nTodo loop interrupted by user.")
    except Exception as e:
        print(f"\n❌ Fatal error in todo loop: {e}")
