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
| `start_qwen.sh` | Shell script to run ntCode against a local Qwen model. Sets `LLM_PROVIDER=openai` and the `OPENAI_*` variables to route via `OpenAIChatProvider` (native tool calling) to a llama.cpp server on `nt-angband.local`. Use instead of the default Anthropic backend when running against a local model. |
| `instruct1.txt` | Ad-hoc instruction file containing a short user prompt (e.g. a task to run on startup). Not part of the main application — used for one-off experiments and manual testing. |
| `out1.json` / `out2.json` | Ephemeral JSON output files produced during development and experiments (git-ignored via `out*.json`). Not part of the main application. |
| `test_api_key.py` | Standalone script that smoke-tests the Anthropic API key and model name configured in `.env`. |

---

## `storage/` – Persistent agent memory

Holds data that the agent writes and reads across sessions.  All paths are inside `cwd` and therefore within the security sandbox.

| Path | Description |
|------|-------------|
| `storage/memory/` | Created on first `memory_store` call. Contains one `<key>_<timestamp>.md` file per stored memory. Files have a YAML-ish frontmatter block (`timestamp`, `tags`, `key`) followed by the memory body in plain Markdown. Human-readable and inspectable at any time. Git-tracked by default — add `storage/memory/` to `.gitignore` if you prefer not to commit memories. |

---

## `core/` – Provider-neutral types

The target of the backend rewrite: everything above the provider adapters
should work with these types, and wire formats are converted at the edge.

| File | Description |
|------|-------------|
| `types.py` | Conversation types: `Message` (role + tuple of blocks), `TextBlock`, `ToolCall` (id, name, args), `ToolResult` (call_id, content, is_error), plus `ToolSpec`, `Usage` and `AssistantTurn`. `message_to_dict()` / `message_from_dict()` convert to the JSON form used by saved conversations and the wire-contract fixtures. |
| `tool_schema.py` | **The only tool-description generator.** `tool_specs(registry, allowed)` turns tool functions into `ToolSpec`s with JSON-Schema parameters (from type hints) and descriptions (from `:param` docstrings). Used by native OpenAI `tools` and by every text dialect's `{{TOOLS}}` block. Unsupported annotations raise `TypeError`. |

---

## `providers/` – Model API adapters

Each adapter converts `core.types` to one API's wire format and back, and
raises typed errors instead of returning error text.

| File | Description |
|------|-------------|
| `base.py` | `Provider` interface: `complete(system, messages, tools) -> AssistantTurn`. |
| `errors.py` | `ProviderError` and subclasses (`ProviderAuthError`, `ProviderRateLimitError`, `ProviderTimeoutError`, `ProviderConnectionError`, `ProviderRequestError`, `ProviderServerError`); `user_message()` gives the text to show. |
| `openai_chat.py` | `OpenAIChatProvider`: any OpenAI-compatible Chat Completions server (OpenAI, llama.cpp `--jinja`, vLLM, Ollama, LM Studio) through the `openai` SDK with native tool calling: `tools` function definitions, assistant `tool_calls`, one `role: "tool"` message per result. Invalid argument JSON is kept in `ToolCall.raw_arguments`; `finish_reason` is mapped to the shared stop reasons. The default for `LLM_PROVIDER=openai` unless `CALLING_CONVENTION` names a text format. |
| `text_tools.py` | Tool calling through text for servers or models without native tools. `Dialect` subclasses (`ntcode`, `xml`, `json_block`, `gemma`; see `DIALECTS`) render tool descriptions and past calls in their syntax and parse calls out of replies with a JSON decoder (multi-line arguments, delimiters inside strings; invalid arguments become `ToolCall.raw_arguments`). `TextToolsProvider` wraps a plain-text provider: tools go into the system prompt, history is rendered as strictly alternating text, replies are split into prose and `ToolCall`s. Used when `CALLING_CONVENTION` names a text format. |
| `anthropic.py` | `AnthropicProvider`: Claude with native tool use (`tool_use` / `tool_result` blocks, parallel results in one user message), cache breakpoints on the system block and at the end of the conversation (no beta header), thinking and other unknown blocks kept as `OpaqueBlock`s and sent back unchanged, SDK exceptions mapped to `ProviderError`s. |

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
| `rate_limiter.py` | `TokenRateLimiter` class implementing a sliding-window (60-second) token-consumption budget. `wait_for_capacity(estimated)` blocks until headroom is available and returns a reservation ID; `record_actual(id, actual)` corrects the reservation once the real API token counts are known. A module-level `_rate_limiter` singleton is shared by the providers. |
| `llm.py` | Active provider and conversation state. `llm` is the active provider, always built from the configuration by `_build_llm()`: `providers.anthropic.AnthropicProvider` for Claude, `providers.openai_chat.OpenAIChatProvider` for OpenAI-compatible endpoints, wrapped in `providers.text_tools.TextToolsProvider` when `CALLING_CONVENTION` names a text format. `rebuild_provider()` rebuilds it after a change to one of `PROVIDER_KEYS` (called by `/config set` and roles); `switch_provider()` (`/provider`) writes provider, model and URL into the configuration and rebuilds. Tests may still set a legacy `LLM` (`DummyLLM`) with a single `call()` method. `SessionHeader` holds the system prompt and documentation files (`system_with_docs()` for native providers); `ConversationManager` stores the task conversation as `core.types.Message`s. `execute_llm_call()` wraps legacy `LLM`s only, turning their exceptions into error text. |
| `openai_llm.py` | OpenAI-specific implementation of the LLM provider abstraction. |
| `dummy_llm.py` | `DummyLLM` — a file-replay subclass of `LLM` for tests and offline development. Reads a plain-text replay file (one response per non-blank, non-comment line) and returns each line in turn via `call(system, messages)`, cycling back to the start when exhausted. Returns a `_FakeUsage` object that mirrors Anthropic's usage type so `execute_llm_call()` and logging code work without modification. No API calls, no rate limiting, no credentials needed. Extras: `reset()` restarts the replay; `reload(path)` re-reads from disk; `response_count` and `current_index` properties for assertion in tests. |
| `config_manager.py` | `ConfigManager` class and module-level `config` singleton. Owns all mutable runtime settings as a typed dict, validated against a schema. `get(key)` / `set(key, value)` (type coercion from strings + validation) / `reset(key=None)` / `show(key=None)` (grouped display with change markers `*`) / `save(path)` / `load(path)` (JSON round-trip; skips unknown keys, reports per-key errors). Mirrors every change back into `utils.config` module-level names so legacy call-sites stay in sync. Sensitive keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are masked in display. Initialised from `utils.config` at import time so all env-var overrides are preserved. |
| `tool_format.py` | **Legacy** text-protocol formatters and parsers, used only by the legacy `LLM` path (`DummyLLM`) and the non-native `{{TOOLS}}` block of `utils/prompt.py`; the live text formats are in `providers/text_tools.py`. `openai_tool_mode()` tells whether `CALLING_CONVENTION` selects native tools or a text format. Scheduled for removal. |

---

## `tools/` – Tool middleware

One file per tool, each exporting a single `*_tool()` function.
All tools import security and config helpers from `utils/`; none import from `frontend/`.

| File | Description |
|------|-------------|
| `__init__.py` | Re-exports all `*_tool` symbols so other modules can import from `tools` as a single namespace. Currently exports 13 tools. |
| `registry.py` | Central tool registry and dispatcher. `TOOL_REGISTRY` maps tool names to their functions. `get_tool_str_representation()` formats one tool's name/description/signature for the prompt. `get_full_system_prompt()` delegates to `utils.prompt.build_system_prompt()` — it no longer builds the prompt itself. `execute_tool_safely()` introspects each tool's signature, fills in defaults for missing parameters, and executes the call inside a try/except. `register_tool()` allows future dynamic registration. |
| `read_file.py` | `read_file_tool(filename)` – validates the path, checks the 10 MB size limit, and reads the file with UTF-8 / latin-1 fallback. |
| `list_files.py` | `list_files_tool(path)` – validates the path, iterates the directory, and returns a list of `{filename, type}` dicts (only entries that pass `validate_file_access` are included). |
| `edit_file.py` | `edit_file_tool(path, old_str, new_str)` – if `old_str` is empty, creates or overwrites the file; otherwise replaces the first occurrence of `old_str` with `new_str`. Enforces the size limit and path sandbox. |
| `git_status.py` | `git_status_tool()` – runs `git status --porcelain`, parses each line into structured `staged`, `unstaged`, and `untracked` lists (with action labels), also reports the current branch name and a `is_clean` flag. |
| `git_diff.py` | `git_diff_tool(file_path, staged)` – builds and runs the appropriate `git diff` command, parses the output to produce a summary (files changed, lines added/removed), and returns both the raw diff text and structured metadata. |
| `git_add.py` | `git_add_tool(file_paths)` – validates each requested path inside the sandbox, converts to repo-relative paths, runs `git add`, and returns the list of files now staged. |
| `git_commit.py` | `git_commit_tool(message, auto_generate)` – checks that staged changes exist, optionally auto-generates a commit message from the staged-file list, then runs `git commit -m`. |
| `git_log.py` | `git_log_tool(max_entries, file_path)` – runs `git log` with a structured format string, parses each entry into `{hash, author, date, message}` dicts, and returns count metadata including whether more history exists. |
| `search_web.py` | `search_web_tool(query, max_results)` – searches the web using DuckDuckGo. |
| `read_web.py` | `read_web_tool(url)` – fetches a webpage and extracts its main text content. |
| `search_codebase.py` | `search_codebase_tool(query, path, glob, case_sensitive, max_results)` – regex/keyword search over file contents. Walks the directory tree, skips binary files, returns `{file, line, text}` matches with truncation guard. Zero new dependencies. |
| `memory_store.py` | `memory_store_tool(key, content, tags)` – writes a tagged Markdown memory file to `storage/memory/`. Filename encodes key + timestamp so repeated calls with the same key produce distinct files. Key must be alphanumeric + hyphens/underscores. |
| `memory_search.py` | `memory_search_tool(query, tags, max_results)` – keyword/regex search across `storage/memory/*.md`. Optionally filters by tag. Returns newest-first results with key, timestamp, tags, and a body snippet. Returns empty result (not error) if the memory directory does not yet exist. |
| `memory_list.py` | `memory_list_tool(tag, limit)` – lists stored memories newest-first with optional tag filter. Returns key, timestamp, tags, and a one-line summary of each memory body. Cheap orientation call; use at the start of a new task. |

---

## `utils/` additions – Agent middleware (connector + loop)

Two new files added to `utils/` complete the frontend/middleware split.
They contain no UI code and no `print()`/`input()` calls.

| File | Description |
|------|-------------|
| `connector.py` | `Connector` class: the **only** communication channel between any frontend and the agent. Maintains two thread-safe `deque` queues (one per direction) plus a `threading.Event` per queue for blocking receives. API: `send_user(content)` / `send_assistant(content)` for convenience helpers; `receive_assistant_blocking()` / `receive_user_blocking()` for event-driven blocking reads (no busy-wait); `receive()` / `receive_user()` for non-blocking polls; `drain()` / `snapshot()` for bulk access; `shutdown()` to unblock all waiters. Only plain JSON-serialisable dicts stored. |
| `agent.py` | `run_agent(connector)` – the pure agent loop designed to run in a background thread. Owns the conversation history, prunes via `ConversationManager.prune_task_messages()`, calls `execute_llm_call()`, parses tool invocations via `extract_tool_invocations()` (a thin wrapper around the parser returned by `utils.tool_format.get_parser_for_provider()`), dispatches tools via `execute_tool_safely()`, feeds results back into the conversation, and publishes the final plain reply via `connector.send_assistant()`. The active parser is selected once at import time from `LLM_PROVIDER` and the active model name. No TUI code. |

## `frontend/` – User interface

Handles user interaction only. Imports `Connector` and `run_agent` from `utils/`;
never imports LLM or tool internals directly.

| File | Description |
|------|-------------|
| `__init__.py` | Empty package marker. |
| `connector.py` | Backward-compatibility shim. Re-exports `Connector` and `Message` from `utils.connector` so any code importing `from frontend.connector import Connector` continues to work. |
| `agent_loop.py` | TUI frontend. `run_coding_agent_loop()` prints the welcome banner, instantiates a `Connector`, starts `run_agent()` in a daemon background thread, then runs the `input()` / `print()` REPL loop. Forwards user input via `connector.send_user()` and blocks on `connector.receive_assistant_blocking()` for replies. Handles `KeyboardInterrupt` / `EOFError` gracefully and calls `connector.shutdown()` on exit. |
| `batch_loop.py` | Batch frontend. `run_batch_loop(infile, outfile)` reads a plain-text instruction file (one prompt per non-blank, non-comment line), instantiates a `Connector`, starts `run_agent()` in a daemon background thread, and processes each instruction sequentially, writing structured output (`=== [N] You: … ===` / response / blank line) to `outfile`. Slash-commands (`/reset`, `/save`, `/savepoint`, `/restore`, etc.) are handled via `dispatch_line()` from `common.py`, so the full command set works identically to the TUI. In `VERBOSE_MODE`, tool-approval requests are auto-approved with a log warning. Invoked via `python ntCode.py --batch infile.txt --out outfile.txt`. |
| `common.py` | Shared frontend logic used by both the TUI and batch frontends. Exports: `ERROR_PREFIXES` / `is_error_response()` — detect provider-level error sentinels; `HELP_TEXT` — the `/help` string; `handle_provider_command()` — handles `/provider` sub-commands and returns plain text; `handle_config_command()` — handles all `/config` sub-commands (`set`, `reset`, `save`, `load`, `help`) by delegating to `utils.config_manager.config` and returning plain text (no connector round-trip needed); `DispatchResult` enum (`QUIT`, `LOCAL`, `CONTROL`, `USER`) and `DispatchOutcome` dataclass — describe what `dispatch_line()` did; `dispatch_line(line, connector)` — the central input router that handles all slash-commands (`/help`, `/tools`, `/prompt`, `/provider`, `/config`, `/reset`, `/save`, `/load`, `/savepoint`, `/restore`, `/savepoints`, `/quit`) and forwards plain user messages to the agent. Contains no `print()`, `input()`, or ANSI colour code. |

---

## `roles/` – Role definitions

One `.toml` file per role. System-prompt stubs for roles that override the default prompt live under `roles/prompts/`. Loaded and validated by `utils/roles.py`; activated via `/role load <name>` in the TUI or batch frontend.

| File | Description |
|------|-------------|
| `developer.toml` | Full-access developer role (all tools allowed, no system-prompt override, `OPENAI_TEMPERATURE=0.5`). |
| `researcher.toml` | Read-only + web tools (`read_file`, `list_files`, `search_web`, `read_web`); loads `roles/prompts/researcher.md`. |
| `executive.toml` | Read-only + web tools; concise executive style; loads `roles/prompts/executive.md`. |
| `prompts/researcher.md` | System-prompt stub for the researcher role. Contains `{{TOOLS}}` placeholder. |
| `prompts/executive.md` | System-prompt stub for the executive role. Contains `{{TOOLS}}` placeholder. |

**Adding a new role:** create `roles/<name>.toml` with at minimum `[role] name = "<name>"`. See `developer.toml` for a fully-commented template. The `tools` array limits which tools are callable; omit it to allow all tools. Add `system_prompt_file = "roles/prompts/<name>.md"` to supply a custom system prompt.

---

## `tests/` – Test suite

| File | Description |
|------|-------------|
| `dummy_responses.txt` | Plain-text replay file consumed by `DummyLLM` in tests. Contains a mix of plain-prose replies and tool-invocation lines so tests cover both response shapes. Comments (lines starting with `#`) and blank lines are ignored by the loader. |
| `__init__.py` | Empty package marker. |
| `test_security.py` | Tests for `validate_file_access()` and `resolve_abs_path()` in `utils/security.py`: verifies that paths inside `cwd` are allowed, that paths outside it raise `PermissionError`, and that `..` traversal attempts are blocked. Also contains integration tests for `read_file_tool` and `edit_file_tool` checking that security boundaries are enforced end-to-end. Imports directly from `utils.security` and `tools.*` (no `ntCode.py` shim). |
| `test_basic.py` | Smoke tests for path handling, `read_file_tool`, `list_files_tool`, and `extract_tool_invocations` happy-path and edge cases. Imports directly from `utils.security`, `tools.*`, and `utils.agent`. |
| `test_extract_tool_invocations.py` | Focused unit tests for `extract_tool_invocations()` from `utils.agent`: valid single and multiple calls, empty args, boolean/int args, prose lines ignored, malformed JSON skipped, missing parentheses, unknown tool names rejected, non-dict JSON rejected, and empty tool names rejected. |
| `test_config_manager.py` | Unit and integration tests for `utils/config_manager.py`: get/set/reset for all key types, type coercion from strings, validation (provider enum, positive int/float, temperature range, non-empty str), masked display of sensitive keys, save/load JSON round-trip (creates files, preserves values, skips unknown keys, reports per-key validation errors), and `_sync_to_config` (verifies that `utils.config` module-level constants are updated after set/reset). |
| `test_tool_format.py` | Unit tests for `utils/tool_format.py`: `_detect_family()` routing for all supported model families; `_parse_ntcode()`, `_parse_xml()`, and `_parse_json_block()` parsers (happy path, multi-call, prose-ignored, unknown-tool, malformed-JSON, missing-field cases); `format_tools_for_provider()` smoke-tests that each formatter produces the expected key strings; `get_parser_for_provider()` identity checks. All tests offline — no LLM calls. TOOL_REGISTRY patched with a minimal two-tool stub. |
| `test_openai_llm_parse.py` | Tests for parsing OpenAI-specific tool call formats. |
| `test_dummy_llm.py` | Tests for the `DummyLLM` implementation. |
| `test_memory_tools.py` | Unit tests for `memory_store`, `memory_search`, `memory_list`, and `search_codebase`. All memory tests use `tmp_path` to redirect `_MEMORY_DIR` — no real `storage/memory/` files touched. Covers: file creation, key validation, tag filtering, case-insensitivity, empty/missing directory handling, regex errors, binary file skipping, glob filtering, sandbox enforcement. |
| `conftest.py` | Autouse fixture that snapshots and restores global runtime state (`utils.config` constants, `ConfigManager` values, active LLM, parser and role) around every test, so results do not depend on test order. |
| `test_core_types.py` | Tests for `core/types.py`: constructors, role/block validation, immutability, dict round trip (including the old string save format), and that every fixture conversation parses. |
| `test_tool_schema.py` | Tests for `core/tool_schema.py`: annotation-to-JSON-Schema mapping, docstring parsing, error cases, a spec for every registered tool, and the `List[str]` → array regression in the native OpenAI schema. |
| `test_conversation_manager.py` | Tests for `ConversationManager`: text API format, pruning that never starts at an assistant message or orphans a tool result, lossless save/restore, old save format, save points. |
| `test_anthropic_provider.py` | `AnthropicProvider` beyond the fixtures: request building (cache breakpoints, block order, dropped empty blocks), thinking-block round trip, refusal, usage, error mapping for each HTTP status, timeouts and connection errors, rate limiter use. |
| `test_openai_provider.py` | `OpenAIChatProvider` beyond the fixtures: request building, finish-reason mapping, usage with cached tokens, invalid or missing arguments and ids, error mapping. |
| `test_provider_selection.py` | Which client is built for each `LLM_PROVIDER` / `CALLING_CONVENTION`, `switch_provider()`, `/config set` rebuilding the client, the native prompt for OpenAI endpoints, and a Claude conversation continuing on an OpenAI endpoint. |
| `test_text_tools.py` | Text dialects and `TextToolsProvider`: parsing per dialect (multi-line arguments, delimiters in strings, unquoted keys, invalid arguments, ordinary code fences left alone), render/parse round trips, tools in the system prompt, history rendered as alternating text. |
| `test_agent_native.py` | Agent loop with a native provider: tool call round trip, parallel results, unknown/failing tools still answered, provider errors and refusals published but not stored, max_tokens note, bare `/savepoint` regression, and one end-to-end run of `AnthropicProvider` through `run_agent` over a mock transport. |
| `test_wire_contract.py` / `wire_backends.py` | Wire-contract tests: each JSON file in `fixtures/wire/` specifies an HTTP request or response for a provider and tool mode (see `fixtures/wire/README.md`). `wire_backends.py` runs them against the current code through a mock HTTP transport; cases it gets wrong are strict xfails. |

---

## `scripts/` – Developer scripts

| File | Description |
|------|-------------|
| `capture_wire_fixture.py` | Sends one native tool-calling request to a real Anthropic or OpenAI-compatible server and saves the raw response as a wire-contract fixture in `tests/fixtures/wire/captured/`. |

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
| `prompt_doc.md` | **Prompt architecture reference.** Explains how `system_prompt.md` is assembled (stub → `{{FILE:…}}` inlining → `{{TOOLS}}` injection → cache), documents all three built-in calling conventions (ntcode / xml / json_block) with wire-format examples, and gives a step-by-step guide for adding a new calling convention for a new model family. |

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
