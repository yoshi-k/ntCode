# Agent Overview — ntCode

Welcome. This file is your entry point for the ntCode project. Read this first.

## What is ntCode?
ntCode is an AI-powered coding assistant that integrates with Claude AI (and OpenAI-compatible endpoints) to provide secure file manipulation, git workflow automation, and interactive development assistance. It was originally vibecoded from a 200-line proof-of-concept and has grown into a modular, layered architecture.

## Key documents

| Document | Purpose |
|---|---|
| [`outline.md`](outline.md) | High-level strategy, architecture vision, planned features, and implementation-status tracking. Start here for the "why" and "where are we going". |
| [`file_organization.md`](file_organization.md) | Detailed map of every file and directory in the repo, including the dependency rules between layers. Start here when you need to find or place code. |
| [`README.md`](README.md) | Full usage guide: quick-start, configuration, execution modes, available tools, security features, and examples. |
| [`bugs.md`](bugs.md) | Known bugs with diagnostic analysis and next actions. Check here before starting work to avoid duplicating effort. |
| [`decouplingStrategy.md`](decouplingStrategy.md) | The step-by-step refactoring plan that broke the original monolith into the current layered architecture. Useful architectural reference. |
| [`gitWorkflow.md`](gitWorkflow.md) | Branching strategy, commit conventions, and PR process. |
| [`gitTesting.md`](gitTesting.md) | Guidelines for writing and running git-related tests. |

## Architecture in one sentence
`frontend/` (TUI) → `utils/connector.py` → `utils/agent.py` (LLM loop) → `tools/` (one file per tool) → `utils/` (security, config, rate-limiting, LLM abstraction)

## Where to start
- **New to the project?** Read `outline.md`, then `file_organization.md`, then `README.md`.
- **About to fix a bug?** Check `bugs.md` first, then `file_organization.md` to locate the relevant file.
- **Adding a new tool?** Read `tools/registry.py` and any existing tool file (e.g. `tools/read_file.py`) as a template.
- **Swapping the LLM provider?** See `utils/llm.py` and the `LLM_PROVIDER` env var in `README.md`.
- **Running tests?** See `tests/` and `gitTesting.md`.
