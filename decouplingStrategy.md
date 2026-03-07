#Decoupling

The idea is to seperate the app ntCode.py into three parts,

Front end, for now a tui app
Middleware handles the tools 
Backend the tools and the llm

The connection between the front end and the middleware should be a connector class wrapping a deque of messages. A goal here is to make it easy to add other front ends or to archive network transparency. 

The middleware should register tools, parse llm responses for tool use and execute commands from the front end.

The back end are the specific tools used. 

To archive this, first recreate each tool as a single file in the directory tools. 

---

## Specific Next Steps

### Understanding the Current Code (`ntCode.py`)

The current monolith contains these logical groups:

| Group | Items |
|---|---|
| **Config / constants** | `MAX_FILE_SIZE`, `MAX_CONVERSATION_LENGTH`, `DEFAULT_MODEL`, `GIT_TIMEOUT`, `API_MAX_TOKENS`, `API_TIMEOUT`, `ALLOWED_BASE_PATHS`, `TOKEN_LIMIT_PER_MINUTE`, debug flags, logging setup |
| **Rate limiter** | `TokenRateLimiter` class, `_rate_limiter` singleton |
| **LLM abstraction** | `LLM` (ABC), `AnthropicLLM`, `llm` singleton, `execute_llm_call()` |
| **Security helpers** | `validate_file_access()`, `resolve_abs_path()`, `validate_git_operation()`, `run_git_command()` |
| **Tool implementations** | `read_file_tool`, `list_files_tool`, `edit_file_tool`, `git_add_tool`, `git_commit_tool`, `git_status_tool`, `git_diff_tool`, `git_log_tool` |
| **Tool registry / dispatch** | `TOOL_REGISTRY` dict, `get_tool_str_representation()`, `extract_tool_invocations()`, `execute_tool_safely()` |
| **Prompt** | `SYSTEM_PROMPT` template, `get_full_system_prompt()` |
| **Agent loop / UI** | `run_coding_agent_loop()`, ANSI color constants, `if __name__ == "__main__"` |

---

### Target Directory Layout

```
ntCode/
├── main.py                        # Entry point → starts TUI frontend
├── frontend/
│   ├── __init__.py
│   └── tui.py                     # TUI app (currently: run_coding_agent_loop logic)
├── middleware/
│   ├── __init__.py
│   ├── connector.py               # Connector class wrapping deque[Message]
│   ├── agent.py                   # Agent loop: reads connector, calls LLM, dispatches tools
│   ├── tool_registry.py           # TOOL_REGISTRY, register_tool(), execute_tool_safely()
│   ├── llm_parser.py              # extract_tool_invocations(), get_full_system_prompt()
│   └── llm_provider.py            # LLM ABC, AnthropicLLM, llm singleton, execute_llm_call()
├── backend/
│   ├── __init__.py
│   ├── security.py                # validate_file_access(), resolve_abs_path(),
│   │                              #   validate_git_operation(), run_git_command()
│   ├── rate_limiter.py            # TokenRateLimiter, _rate_limiter singleton
│   ├── config.py                  # All constants + env-var reads + logging setup
│   └── tools/
│       ├── __init__.py            # Imports & re-exports all tool functions
│       ├── read_file.py           # read_file_tool()
│       ├── list_files.py          # list_files_tool()
│       ├── edit_file.py           # edit_file_tool()
│       ├── git_add.py             # git_add_tool()
│       ├── git_commit.py          # git_commit_tool()
│       ├── git_status.py          # git_status_tool()
│       ├── git_diff.py            # git_diff_tool()
│       └── git_log.py             # git_log_tool()
```

---

### Step 1 — Extract `backend/config.py`
- Move all module-level constants: `MAX_FILE_SIZE`, `MAX_CONVERSATION_LENGTH`, `DEFAULT_MODEL`,
  `GIT_TIMEOUT`, `API_MAX_TOKENS`, `API_TIMEOUT`, `TOKEN_LIMIT_PER_MINUTE`,
  `_RATE_WINDOW_SECONDS`, `ALLOWED_BASE_PATHS`.
- Move all debug/verbose/log flags: `DEBUG_MODE`, `VERBOSE_MODE`, `LOG_CONVERSATIONS`.
- Move `load_dotenv()` call and `logging` setup here — this file is imported first by everything.
- Move the ANSI color constants (`YOU_COLOR`, `ASSISTANT_COLOR`, `RESET_COLOR`) here
  (or into `frontend/tui.py` if they are considered purely UI — prefer the latter).
- **No business logic** in this file.

### Step 2 — Extract `backend/rate_limiter.py`
- Move `TokenRateLimiter` class verbatim.
- Move `_rate_limiter` module-level singleton.
- Imports needed: `threading`, `time`, `collections.deque`, and `config.TOKEN_LIMIT_PER_MINUTE` /
  `config._RATE_WINDOW_SECONDS`.
- Expose: `TokenRateLimiter`, `_rate_limiter`.

### Step 3 — Extract `backend/security.py`
- Move `validate_file_access()`, `resolve_abs_path()`, `validate_git_operation()`,
  `run_git_command()`.
- Imports needed: `os`, `subprocess`, `shlex`, `pathlib.Path`, `typing`, `logging`,
  `backend.config` (for `GIT_TIMEOUT`, `ALLOWED_BASE_PATHS`).
- All tool files will import from here — keep it dependency-free of tool or LLM code.

### Step 4 — Extract each tool into `backend/tools/<tool_name>.py`
Each file follows the same pattern:
```
from backend.security import resolve_abs_path, validate_file_access, ...
from backend.config import MAX_FILE_SIZE, ...
# tool function implementation
```
- `read_file.py`  → `read_file_tool(filename)`
- `list_files.py` → `list_files_tool(path)`
- `edit_file.py`  → `edit_file_tool(path, old_str, new_str)`
- `git_add.py`    → `git_add_tool(file_paths)` — imports `run_git_command`, `validate_git_operation`
- `git_commit.py` → `git_commit_tool(message, auto_generate)` — same git helpers
- `git_status.py` → `git_status_tool()` — same git helpers
- `git_diff.py`   → `git_diff_tool(file_path, staged)` — same git helpers
- `git_log.py`    → `git_log_tool(max_entries, file_path)` — same git helpers

`backend/tools/__init__.py` re-exports all of them for convenience:
```python
from .read_file import read_file_tool
from .list_files import list_files_tool
# ... etc.
```

### Step 5 — Extract `middleware/tool_registry.py`
- Move `TOOL_REGISTRY` dict (populated by importing from `backend/tools/`).
- Move `get_tool_str_representation()` and `execute_tool_safely()`.
- Expose `register_tool(name, fn)` for future dynamic registration.
- Imports: `inspect`, `typing`, `logging`, `backend.tools.*`.

### Step 6 — Extract `middleware/llm_provider.py`
- Move `LLM` ABC, `AnthropicLLM`, `llm` singleton, `execute_llm_call()`.
- Imports: `anthropic`, `json`, `time`, `logging`, `backend.config.*`,
  `backend.rate_limiter._rate_limiter`.
- **Gotcha:** `execute_llm_call()` currently references the module-level `llm` singleton.
  Keep that pattern; `llm` is instantiated here once at import time.

### Step 7 — Extract `middleware/llm_parser.py`
- Move `SYSTEM_PROMPT` template string, `get_full_system_prompt()`,
  `extract_tool_invocations()`.
- Imports: `logging`, `json`, `middleware.tool_registry.TOOL_REGISTRY` (to validate
  tool names during parsing).

### Step 8 — Create `middleware/connector.py`
- Define a `Message` dataclass or `TypedDict`: `{role: str, content: str}`.
- Define `Connector` class wrapping `collections.deque[Message]`.
- Public API:
  - `send(role, content)` — enqueue a message.
  - `receive()` — dequeue the next message (blocking or non-blocking variant).
  - `drain()` — return all pending messages as a list and clear the queue.
  - `snapshot()` — return a read-only copy of the full history (for LLM context).
- This class is the **only** communication channel between frontend and middleware.
- Design for future network transparency: keep it serialisable (no live objects in the deque).

### Step 9 — Extract `middleware/agent.py`
- Move the inner `while True:` agent loop from `run_coding_agent_loop()` here.
- Function signature: `run_agent(connector: Connector) -> None`
- Responsibilities:
  - Read user messages from `connector`.
  - Build/maintain conversation list (including pruning logic).
  - Call `execute_llm_call()` from `llm_provider`.
  - Parse tool invocations via `extract_tool_invocations()`.
  - Dispatch tools via `execute_tool_safely()`.
  - Write assistant responses (and tool results) back to `connector`.
- Imports: `middleware.connector`, `middleware.llm_provider`, `middleware.llm_parser`,
  `middleware.tool_registry`, `backend.config`.

### Step 10 — Extract `frontend/tui.py` and create `main.py`
- `frontend/tui.py`:
  - Move the `input()` / `print()` shell from `run_coding_agent_loop()`.
  - Instantiate `Connector`, start `run_agent(connector)` in a background thread
    (or run synchronously for the initial version).
  - Handle `KeyboardInterrupt` / `EOFError` gracefully.
  - Own the ANSI color constants (move them here from `config.py`).
- `main.py`:
  - One-liner: `from frontend.tui import run_tui; run_tui()`
  - Guards: `if __name__ == "__main__": main()`

---

### Dependency Rules (must not be violated)

```
frontend  →  middleware.connector  (only — never imports agent internals directly)
middleware →  backend.*
backend    →  (stdlib + anthropic only — never imports middleware or frontend)
```

---

### Key Risks & Gotchas

1. **`llm` singleton instantiated at import time** — `AnthropicLLM` reads `ANTHROPIC_API_KEY`
   from the environment when the module is first imported. Ensure `load_dotenv()` in
   `backend/config.py` is imported (and thus executed) before `middleware/llm_provider.py`.

2. **`logger` references before logging is configured** — `AnthropicLLM.call()` uses
   `logger` which is set up in `config.py`. Import `backend.config` first in every module
   that uses `logger`.

3. **`ALLOWED_BASE_PATHS = [Path.cwd()]` is evaluated at import time** — moving it to
   `config.py` is safe as long as the working directory is set before any import. Document
   this assumption.

4. **`Connector` deque and thread safety** — if `run_agent()` runs in a background thread
   and the TUI reads responses from the same `Connector`, all `deque` access must be
   guarded by a `threading.Lock()` inside `Connector`.

5. **Conversation pruning keeps index 0 (system prompt)** — the pruning logic in the agent
   loop assumes `conversation[0]` is always the system message. After the split this
   invariant must be maintained inside `agent.py`; the `Connector` deque only carries
   user/assistant messages, not the system prompt.

6. **`get_tool_str_representation()` uses `inspect.signature`** — tool docstrings and
   signatures form the LLM's tool description. Moving tools to separate files must not
   change their signatures or docstrings, or the system prompt will silently change.

7. **`ntCode.py` can be kept as a shim** during transition:
   ```python
   from frontend.tui import run_tui
   if __name__ == "__main__":
       run_tui()
   ```
   This preserves backward compatibility for anyone currently running `python ntCode.py`.

