# Agent Overview — ntCode

Welcome. This file is your entry point for the ntCode project. Read this first.

## What is ntCode?
ntCode is an AI coding assistant for the terminal. It works with Claude (Anthropic API) and with any OpenAI-compatible server (llama.cpp, vLLM, Ollama, LM Studio, OpenAI, Groq), and gives the model tools for reading and editing files, git, web research, codebase search and persistent memory. It began as a vibe-coded 200-line proof of concept and has grown into a layered architecture.

## Key documents

| Document | Purpose |
|---|---|
| [`README.md`](README.md) | Usage guide: quick start, configuration, commands, tools, roles, tool calling. |
| [`file_organization.md`](file_organization.md) | Map of every file and directory, including the dependency rules between layers. Start here when you need to find or place code. |
| [`prompt_doc.md`](prompt_doc.md) | How the system prompt is built, how tools reach the model (native or text dialect), and how to add a dialect. |
| [`outline.md`](outline.md) | Strategy, architecture vision, planned features and status. |
| [`bugs.md`](bugs.md) | Known bugs and test gaps. Check here before starting work. |
| [`gitWorkflow.md`](gitWorkflow.md) | Branching strategy, commit conventions, and PR process. |
| [`gitTesting.md`](gitTesting.md) | Guidelines for writing and running git-related tests. |

## Architecture in one sentence
`frontend/` (TUI, batch) → `utils/connector.py` → `utils/agent.py` (agent loop on `core/types` messages) → `providers/` (one adapter per model API) and `tools/` (one file per tool), with `utils/` for configuration, prompt, security and rate limiting.

## Rules for the model backend
- **The agent loop never handles wire formats or tool-call text.** It works only with `core.types` (`Message`, `ToolCall`, `ToolResult`, `ToolSpec`). Converting to and from an API's format happens in `providers/`, nowhere else.
- **Supporting a new model is configuration or a dialect, never a special case.** A server with native tool calling needs no code. A model that only does text tool calls gets a `Dialect` class in `providers/text_tools.py` (see `prompt_doc.md` §5). A new API gets a new `Provider` in `providers/`.
- **Every change to the backend comes with wire-contract fixtures** in `tests/fixtures/wire/`, and a bug fix adds a fixture or test that failed before the fix.
- **The configuration is the single source of truth for the active provider.** Change settings through `utils.config_manager` and call `utils.llm.rebuild_provider()`; never replace `utils.llm.llm` directly.
- **Tool descriptions come only from `core/tool_schema.py`**, built from each tool's type hints and `:param` docstring.

## Where to start
- **New to the project?** Read `README.md`, then `file_organization.md`.
- **About to fix a bug?** Check `bugs.md`, then `file_organization.md` to locate the code.
- **Adding a new tool?** Copy an existing tool (e.g. `tools/read_file.py`): type-annotate every parameter and document each with `:param name:`; register it in `tools/registry.py`.
- **Working on providers or tool calling?** Read `prompt_doc.md` and `tests/fixtures/wire/README.md`.
- **Running tests?** `./run_tests.sh` or `pytest tests/`; see also `gitTesting.md`.
