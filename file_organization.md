# ntCode – File Organisation

This document gives a short description of every source file in the project.
The repository follows a three-layer architecture (frontend → tools/middleware → utils/backend)
with `ntCode.py` as a thin entry-point shim.

---

## Root

| File | Description |
|------|-------------|
| `ntCode.py` | Entry-point shim. Loads `.env`, then imports and calls `run_coding_agent_loop()` from `frontend/agent_loop.py`. Kept so that `python ntCode.py` continues to work. |
| `outline.md` | Living project document: ideas, architecture notes, usage instructions, environment-variable reference, known bugs, TODO list, and implementation-status tracking. The primary place to capture decisions and future work. |
| `decouplingStrategy.md` | Step-by-step refactoring plan used to break the original monolith apart. Describes the target directory layout, the ten extraction steps, dependency rules, and key gotchas. Now largely complete but kept as architectural reference. |
| `README.md` | User-facing documentation: quick-start, configuration table, execution modes, available tools, security features, usage examples, and roadmap. |
| `requirements.txt` | Python package dependencies (anthropic, python-dotenv, etc.). |
| `.env.example` | Template showing all supported environment variables with example values. Copy to `.env` and fill in `ANTHROPIC_API_KEY` before running. |
| `ntcode.log` | Runtime log file written by the application (git-ignored). Contains conversation history, tool executions, API timing, and token-usage data. |
| `test_api_key.py` | Standalone script that smoke-tests the Anthropic API key and model name configured in `.env`. |

---

## `utils/` – Backend infrastructure

Shared low-level modules that every other layer depends on.
Contains no tool logic, no UI, and no LLM call-site code beyond the provider abstraction.

| File | Description |
|------|-------------|
| `__init__.py` | Empty package marker. |
| `config.py` | Single source of truth for all constants and runtime settings. Reads every `NTCODE_*` environment variable, configures the `logging` framework (handlers for console and `ntcode.log`), exposes the named `logger`, defines ANSI colour constants for the TUI, and sets `ALLOWED_BASE_PATHS`, `MAX_FILE_SIZE`, model defaults, timeout values, and the token-rate-limit constants. |
| `security.py` | Path-safety and git-safety helpers used by every tool. `resolve_abs_path()` turns relative paths into absolute ones; `validate_file_access()` enforces sandbox restrictions and blocks path-traversal attempts; `validate_git_operation()` confirms a git repository is present; `run_git_command()` wraps `subprocess.run` with timeout handling and security checks. |
| `rate_limiter.py` | `TokenRateLimiter` class implementing a sliding-window (60-second) token-consumption budget. `wait_for_capacity(estimated)` blocks until headroom is available and returns a reservation ID; `record_actual(id, actual)` corrects the reservation once the real API token counts are known. A module-level `_rate_limiter` singleton is shared by `AnthropicLLM`. |
| `llm.py` | LLM provider abstraction. `LLM` is an abstract base class with a single `call()` method. `AnthropicLLM` implements it: estimates tokens, calls `_rate_limiter.wait_for_capacity()`, makes the Anthropic API request with timeout support, then corrects the reservation. `execute_llm_call()` is the application-level wrapper that separates the system message, delegates to the active `llm` singleton, and catches and humanises all provider exceptions (timeout, rate-limit, auth, connection errors). |

---

## `tools/` – Tool middleware

One file per tool, each exporting a single `*_tool()` function.
All tools import security and config helpers from `utils/`; none import from `frontend/`.

| File | Description |
|------|-------------|
| `__init__.py` | Re-exports all eight `*_tool` symbols so other modules can import from `tools` as a single namespace. |
| `registry.py` | Central tool registry and dispatcher. `TOOL_REGISTRY` maps tool names to their functions. `get_tool_str_representation()` and `get_full_system_prompt()` build the system-prompt text that advertises each tool (name, docstring, signature) to the LLM. `execute_tool_safely()` introspects each tool's signature, fills in defaults for missing parameters, and executes the call inside a try/except. `register_tool()` allows future dynamic registration. |
| `read_file.py` | `read_file_tool(filename)` – validates the path, checks the 10 MB size limit, and reads the file with UTF-8 / latin-1 fallback. |
| `list_files.py` | `list_files_tool(path)` – validates the path, iterates the directory, and returns a list of `{filename, type}` dicts (only entries that pass `validate_file_access` are included). |
| `edit_file.py` | `edit_file_tool(path, old_str, new_str)` – if `old_str` is empty, creates or overwrites the file; otherwise replaces the first occurrence of `old_str` with `new_str`. Enforces the size limit and path sandbox. |
| `git_status.py` | `git_status_tool()` – runs `git status --porcelain`, parses each line into structured `staged`, `unstaged`, and `untracked` lists (with action labels), also reports the current branch name and a `is_clean` flag. |
| `git_diff.py` | `git_diff_tool(file_path, staged)` – builds and runs the appropriate `git diff` command, parses the output to produce a summary (files changed, lines added/removed), and returns both the raw diff text and structured metadata. |
| `git_add.py` | `git_add_tool(file_paths)` – validates each requested path inside the sandbox, converts to repo-relative paths, runs `git add`, and returns the list of files now staged. |
| `git_commit.py` | `git_commit_tool(message, auto_generate)` – checks that staged changes exist, optionally auto-generates a commit message from the staged-file list, then runs `git commit -m`. |
| `git_log.py` | `git_log_tool(max_entries, file_path)` – runs `git log` with a structured format string, parses each entry into `{hash, author, date, message}` dicts, and returns count metadata including whether more history exists. |

---

## `frontend/` – User interface

Handles user interaction and the agent REPL loop.
Imports from `tools/` and `utils/`; nothing in `utils/` or `tools/` imports from here.

| File | Description |
|------|-------------|
| `__init__.py` | Empty package marker. |
| `connector.py` | `Connector` class: a thread-safe `deque`-backed message channel. `send()` enqueues a `{role, content}` message and appends it to the full history; `receive()` dequeues the next message; `drain()` returns and clears all pending messages; `snapshot()` returns a read-only copy of the full history. Designed for network transparency (only plain JSON-serialisable dicts stored). Currently instantiated but not yet wired into the agent loop — reserved for a future multi-frontend architecture. |
| `agent_loop.py` | `run_coding_agent_loop()` – the main REPL. Prints the welcome banner, owns the `conversation` list, prunes history when it exceeds `MAX_CONVERSATION_LENGTH`, calls `execute_llm_call()`, parses tool invocations via `extract_tool_invocations()` (defined in this file), dispatches each tool through `execute_tool_safely()`, appends results back to the conversation, and loops until the LLM returns a plain response. Also contains `extract_tool_invocations()`: parses `tool: NAME({…})` lines from LLM output, validates tool names against `TOOL_REGISTRY`, and silently skips malformed JSON or unknown tools. |

---

## `tests/` – Test suite

| File | Description |
|------|-------------|
| `__init__.py` | Empty package marker. |
| `test_security.py` | Tests for `validate_file_access()` and `resolve_abs_path()` in `utils/security.py`: verifies that paths inside `cwd` are allowed, that paths outside it raise `PermissionError`, and that `..` traversal attempts are blocked. Also contains integration tests for `read_file_tool` and `edit_file_tool` checking that security boundaries are enforced end-to-end. |
| `test_basic.py` | Smoke tests imported directly from `ntCode.py` (stubs out `anthropic` and `dotenv`): path handling, `read_file_tool`, `list_files_tool`, and `extract_tool_invocations` happy-path and edge cases. |
| `test_extract_tool_invocations.py` | Focused unit tests for `extract_tool_invocations()`: valid single and multiple calls, empty args, boolean/int args, prose lines ignored, malformed JSON skipped, missing parentheses, unknown tool names rejected, non-dict JSON rejected, and empty tool names rejected. |

---

## Notes on the `decouplingStrategy.md` target layout vs. current layout

The strategy document describes a future `frontend / middleware / backend` split with a
`middleware/` directory. The current code has collapsed that into three directories
whose roles map as follows:

| Strategy doc | Current directory | Contains |
|---|---|---|
| `backend/` | `utils/` | config, security, rate_limiter, llm |
| `middleware/tools/` + registry + parser | `tools/` | one file per tool + registry (includes tool parser and system-prompt builder) |
| `frontend/` | `frontend/` | connector (future), agent_loop (current REPL + tool parser) |

The `Connector` class in `frontend/connector.py` is implemented but not yet wired into
`agent_loop.py`; connecting them is the next step toward a fully decoupled architecture.
