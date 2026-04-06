# ntCode – File Organisation

This document gives a short description of every source file in the project.
The repository follows a three-layer architecture (frontend → tools/middleware → utils/backend)
with `ntCode.py` as a thin entry-point shim.

---

## Root

| File | Description |
|------|-------------|
| `system_prompt.md` | **System-prompt stub** — the editable source for the LLM system prompt. Contains the base prose instructions, `{{TOOLS}}` (replaced at runtime with formatted tool descriptions), and `{{FILE:path}}` directives (each replaced with the content of the named file). Edit this file to customise the model's role, add or remove context files, or change the tool-use format. Loaded by `utils/prompt.py`; controlled by `NTCODE_SYSTEM_PROMPT_FILE`. |
| `ntCode.py` | Entry-point shim. Loads `.env`, then imports and calls `run_coding_agent_loop()` from `frontend/agent_loop.py`. Kept so that `python ntCode.py` continues to work. |
| `agent.md` | **Start here** — high-level project orientation for agents and new contributors. Links to all key documents and explains the architecture in one sentence. |
| `outline.md` | Strategy, architecture vision, planned features, and implementation-status summary. The place to capture decisions and future direction. |
| `bugs.md` | Known bugs with diagnostic analysis, likely root causes, and next immediate actions. Check before starting any work. |
| `decouplingStrategy.md` | Step-by-step refactoring plan used to break the original monolith apart. Describes the target directory layout, the ten extraction steps, dependency rules, and key gotchas. Now largely complete but kept as architectural reference. |
| `README.md` | Full usage guide: quick-start, configuration, execution modes, available tools, security features, usage examples, and known issues. The authoritative reference for running and using ntCode. |
| `requirements.txt` | Python package dependencies (anthropic, python-dotenv, etc.). |
| `.env.example` | Template showing all supported environment variables with example values. Copy to `.env` and fill in `ANTHROPIC_API_KEY` before running. |
| `ntcode.log` | Runtime log file written by the application (git-ignored). Contains conversation history, tool executions, API timing, and token-usage data. |
| `start_qwen.sh` | Shell script to run ntCode against a local Qwen model. Sets `LLM_PROVIDER=openai` and the `OPENAI_*` variables to route via `OpenAILLM` to a llama.cpp server on `nt-angband.local`. Use instead of the default Anthropic backend when running against a local model. |
| `instruct1.txt` | Ad-hoc instruction file containing a short user prompt (e.g. a task to run on startup). Not part of the main application — used for one-off experiments and manual testing. |
| `out1.json` / `out2.json` | Ephemeral JSON output files produced during development and experiments (git-ignored via `out*.json`). Not part of the main application. |
| `test_api_key.py` | Standalone script that smoke-tests the Anthropic API key and model name configured in `.env`. |

---

## `utils/` – Backend infrastructure

Shared low-level modules that every other layer depends on.
Contains no tool logic, no UI, and no LLM call-site code beyond the provider abstraction.

| File | Description |
|------|-------------|
| `__init__.py` | Empty package marker. |
| `prompt.py` | System-prompt builder. `build_system_prompt()` loads the stub file named by `SYSTEM_PROMPT_FILE`, resolves every `{{FILE:path}}` directive by inlining the named file, and replaces `{{TOOLS}}` with the formatted descriptions of all registered tools. Result is module-level cached; call `invalidate_cache()` to force a rebuild (useful in tests). This is the single source of truth consumed by both `tools/registry.py` (`get_full_system_prompt()`) and the `/prompt` command. |
| `config.py` | Single source of truth for all constants and runtime settings. Reads every `NTCODE_*` environment variable, configures the `logging` framework (handlers for console and `ntcode.log`), exposes the named `logger`, defines ANSI colour constants for the TUI, and sets `ALLOWED_BASE_PATHS`, `MAX_FILE_SIZE`, model defaults, timeout values, and the token-rate-limit constants. |
| `security.py` | Path-safety and git-safety helpers used by every tool. `resolve_abs_path()` turns relative paths into absolute ones; `validate_file_access()` enforces sandbox restrictions and blocks path-traversal attempts; `validate_git_operation()` confirms a git repository is present; `run_git_command()` wraps `subprocess.run` with timeout handling and security checks. |
| `rate_limiter.py` | `TokenRateLimiter` class implementing a sliding-window (60-second) token-consumption budget. `wait_for_capacity(estimated)` blocks until headroom is available and returns a reservation ID; `record_actual(id, actual)` corrects the reservation once the real API token counts are known. A module-level `_rate_limiter` singleton is shared by `AnthropicLLM`. |
| `llm.py` | LLM provider abstraction. `LLM` is an abstract base class with a single `call()` method. `AnthropicLLM` implements it: estimates tokens, calls `_rate_limiter.wait_for_capacity()`, makes the Anthropic API request with timeout support, then corrects the reservation. `execute_llm_call()` is the application-level wrapper that separates the system message, delegates to the active `llm` singleton, and catches and humanises all provider exceptions (timeout, rate-limit, auth, connection errors). |
| `dummy_llm.py` | `DummyLLM` — a file-replay subclass of `LLM` for tests and offline development. Reads a plain-text replay file (one response per non-blank, non-comment line) and returns each line in turn via `call(system, messages)`, cycling back to the start when exhausted. Returns a `_FakeUsage` object that mirrors Anthropic's usage type so `execute_llm_call()` and logging code work without modification. No API calls, no rate limiting, no credentials needed. Extras: `reset()` restarts the replay; `reload(path)` re-reads from disk; `response_count` and `current_index` properties for assertion in tests. |

---

## `tools/` – Tool middleware

One file per tool, each exporting a single `*_tool()` function.
All tools import security and config helpers from `utils/`; none import from `frontend/`.

| File | Description |
|------|-------------|
| `__init__.py` | Re-exports all eight `*_tool` symbols so other modules can import from `tools` as a single namespace. |
| `registry.py` | Central tool registry and dispatcher. `TOOL_REGISTRY` maps tool names to their functions. `get_tool_str_representation()` formats one tool's name/description/signature for the prompt. `get_full_system_prompt()` delegates to `utils.prompt.build_system_prompt()` — it no longer builds the prompt itself. `execute_tool_safely()` introspects each tool's signature, fills in defaults for missing parameters, and executes the call inside a try/except. `register_tool()` allows future dynamic registration. |
| `read_file.py` | `read_file_tool(filename)` – validates the path, checks the 10 MB size limit, and reads the file with UTF-8 / latin-1 fallback. |
| `list_files.py` | `list_files_tool(path)` – validates the path, iterates the directory, and returns a list of `{filename, type}` dicts (only entries that pass `validate_file_access` are included). |
| `edit_file.py` | `edit_file_tool(path, old_str, new_str)` – if `old_str` is empty, creates or overwrites the file; otherwise replaces the first occurrence of `old_str` with `new_str`. Enforces the size limit and path sandbox. |
| `git_status.py` | `git_status_tool()` – runs `git status --porcelain`, parses each line into structured `staged`, `unstaged`, and `untracked` lists (with action labels), also reports the current branch name and a `is_clean` flag. |
| `git_diff.py` | `git_diff_tool(file_path, staged)` – builds and runs the appropriate `git diff` command, parses the output to produce a summary (files changed, lines added/removed), and returns both the raw diff text and structured metadata. |
| `git_add.py` | `git_add_tool(file_paths)` – validates each requested path inside the sandbox, converts to repo-relative paths, runs `git add`, and returns the list of files now staged. |
| `git_commit.py` | `git_commit_tool(message, auto_generate)` – checks that staged changes exist, optionally auto-generates a commit message from the staged-file list, then runs `git commit -m`. |
| `git_log.py` | `git_log_tool(max_entries, file_path)` – runs `git log` with a structured format string, parses each entry into `{hash, author, date, message}` dicts, and returns count metadata including whether more history exists. |

---

## `utils/` additions – Agent middleware (connector + loop)

Two new files added to `utils/` complete the frontend/middleware split.
They contain no UI code and no `print()`/`input()` calls.

| File | Description |
|------|-------------|
| `connector.py` | `Connector` class: the **only** communication channel between any frontend and the agent. Maintains two thread-safe `deque` queues (one per direction) plus a `threading.Event` per queue for blocking receives. API: `send_user(content)` / `send_assistant(content)` for convenience helpers; `receive_assistant_blocking()` / `receive_user_blocking()` for event-driven blocking reads (no busy-wait); `receive()` / `receive_user()` for non-blocking polls; `drain()` / `snapshot()` for bulk access; `shutdown()` to unblock all waiters. Only plain JSON-serialisable dicts stored. |
| `agent.py` | `run_agent(connector)` – the pure agent loop designed to run in a background thread. Owns the `conversation` list (system prompt + history), prunes via `_prune_conversation()`, calls `execute_llm_call()`, parses tool invocations via `extract_tool_invocations()` (also defined here, moved from the old `frontend/agent_loop.py`), dispatches tools via `execute_tool_safely()`, feeds results back into the conversation, and publishes the final plain reply via `connector.send_assistant()`. No TUI code. |

## `frontend/` – User interface

Handles user interaction only. Imports `Connector` and `run_agent` from `utils/`;
never imports LLM or tool internals directly.

| File | Description |
|------|-------------|
| `__init__.py` | Empty package marker. |
| `connector.py` | Backward-compatibility shim. Re-exports `Connector` and `Message` from `utils.connector` so any code importing `from frontend.connector import Connector` continues to work. |
| `agent_loop.py` | TUI frontend. `run_coding_agent_loop()` prints the welcome banner, instantiates a `Connector`, starts `run_agent()` in a daemon background thread, then runs the `input()` / `print()` REPL loop. Forwards user input via `connector.send_user()` and blocks on `connector.receive_assistant_blocking()` for replies. Handles `KeyboardInterrupt` / `EOFError` gracefully and calls `connector.shutdown()` on exit. |
| `batch_loop.py` | Batch frontend. `run_batch_loop(infile, outfile)` reads a plain-text instruction file (one prompt per non-blank, non-comment line), instantiates a `Connector`, starts `run_agent()` in a daemon background thread, and processes each instruction sequentially, writing structured output (`=== [N] You: … ===` / response / blank line) to `outfile`. Slash-commands (`/reset`, `/save`, `/savepoint`, `/restore`, etc.) are handled via `dispatch_line()` from `common.py`, so the full command set works identically to the TUI. In `VERBOSE_MODE`, tool-approval requests are auto-approved with a log warning. Invoked via `python ntCode.py --batch infile.txt --out outfile.txt`. |
| `common.py` | Shared frontend logic used by both the TUI and batch frontends. Exports: `ERROR_PREFIXES` / `is_error_response()` — detect provider-level error sentinels; `HELP_TEXT` — the `/help` string; `handle_provider_command()` — handles `/provider` sub-commands and returns plain text; `DispatchResult` enum (`QUIT`, `LOCAL`, `CONTROL`, `USER`) and `DispatchOutcome` dataclass — describe what `dispatch_line()` did; `dispatch_line(line, connector)` — the central input router that handles all slash-commands (`/help`, `/tools`, `/prompt`, `/provider`, `/reset`, `/save`, `/load`, `/savepoint`, `/restore`, `/savepoints`, `/quit`) and forwards plain user messages to the agent. Contains no `print()`, `input()`, or ANSI colour code. |

---

## `tests/` – Test suite

| File | Description |
|------|-------------|
| `dummy_responses.txt` | Plain-text replay file consumed by `DummyLLM` in tests. Contains a mix of plain-prose replies and tool-invocation lines so tests cover both response shapes. Comments (lines starting with `#`) and blank lines are ignored by the loader. |
| `__init__.py` | Empty package marker. |
| `test_security.py` | Tests for `validate_file_access()` and `resolve_abs_path()` in `utils/security.py`: verifies that paths inside `cwd` are allowed, that paths outside it raise `PermissionError`, and that `..` traversal attempts are blocked. Also contains integration tests for `read_file_tool` and `edit_file_tool` checking that security boundaries are enforced end-to-end. |
| `test_basic.py` | Smoke tests imported directly from `ntCode.py` (stubs out `anthropic` and `dotenv`): path handling, `read_file_tool`, `list_files_tool`, and `extract_tool_invocations` happy-path and edge cases. |
| `test_extract_tool_invocations.py` | Focused unit tests for `extract_tool_invocations()`: valid single and multiple calls, empty args, boolean/int args, prose lines ignored, malformed JSON skipped, missing parentheses, unknown tool names rejected, non-dict JSON rejected, and empty tool names rejected. |

---

## `experiments/` – Experimental scripts

Contains experimental code and scripts not yet part of the main application.

| File | Description |
|------|-------------|
| `numerics_experiment.py` | Experimental numeric computation script, used to explore algorithms or data processing ideas outside the main codebase. |
| `numerics.md` | Notes and documentation accompanying `numerics_experiment.py`. |
| `plot1.png` | Output plot generated by the numerics experiment. |

---

## Documentation Files

All `.md` files live at the root. See the Root table above for `README.md`, `outline.md`, `decouplingStrategy.md`, and `file_organization.md`.

| File | Description |
|------|-------------|
| `gitWorkflow.md` | Git workflow guidelines: branching strategy, commit conventions, and PR process. |
| `gitTesting.md` | Guidelines for git-related testing: how to verify git tool behaviour and write git-touching tests. |

---

## Architecture layer map

| `decouplingStrategy.md` name | Actual directory | Contains |
|---|---|---|
| `backend/` | `utils/` | `config`, `security`, `rate_limiter`, `llm` |
| `middleware/tools/` + registry + parser | `tools/` | one file per tool + `registry.py` (tool registry, system-prompt builder, `execute_tool_safely`) |
| `middleware/` (connector + agent) | `utils/` (`connector.py` + `agent.py`) | message channel + LLM loop + tool parser |
| `frontend/` | `frontend/` | `agent_loop.py` (TUI shell), `batch_loop.py` (batch runner), `common.py` (shared constants), `connector.py` (re-export shim) |

### Dependency rules (enforced)

```
frontend/  ->  utils.connector + utils.agent  (no LLM/tool internals)
utils/     ->  tools/  (agent.py only) + stdlib + anthropic
tools/     ->  utils/
```

### What was split in this refactor

The original `frontend/agent_loop.py` was a monolith containing both TUI code
(`input`, `print`, ANSI colours) and agent logic (conversation management, LLM
calls, tool dispatch, tool invocation parsing).  It has been split into:

* **`utils/agent.py`** – all agent logic; no UI imports.
* **`frontend/agent_loop.py`** – TUI shell only; no LLM or tool imports.
* **`utils/connector.py`** – the stable thread-safe API between the two.
* **`frontend/connector.py`** – backward-compat re-export shim.

Adding a new frontend (GUI, web, network) now requires only:
1. Instantiate `Connector()` from `utils.connector`.
2. Start `run_agent(connector)` from `utils.agent` in a thread.
3. Call `connector.send_user()` / `connector.receive_assistant_blocking()`.
