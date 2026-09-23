# ntCode — Strategy & Vision

> For usage instructions see [`README.md`](README.md).  
> For known bugs and immediate action items see [`bugs.md`](bugs.md).  
> For the file-by-file code map see [`file_organization.md`](file_organization.md).  
> For agent/contributor orientation see [`agent.md`](agent.md).

---

## Origin

ntCode is an exploration of an AI coding assistant, originally vibecoded from a 200-line proof-of-concept:

> *"The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code"*  
> https://www.mihaileric.com/The-Emperor-Has-No-Clothes/  
> Adapted and extended by Joerg Kulbartz (joerg@kulbartz.de)

---

# Notes -- important to check
For save
## Architecture Vision

Three clean layers: **Frontend → Middleware → Backend**.

### Frontend
Displays messages, handles all UI (chat, help, log queries).
- ✅ **DONE**: `frontend/agent_loop.py` is a pure TUI shell (`input`/`print` only). Starts `run_agent()` in a background thread; communicates exclusively through `Connector`.

### Middleware
Routes messages between the UI and the LLM; logs all interactions.
- ✅ **DONE**: `utils/agent.py` — pure agent loop (conversation history, LLM calls, tool dispatch, invocation parsing). Zero UI code.
- ✅ **DONE**: `utils/connector.py` — thread-safe two-directional queue API. Blocking `Event`-based receives (no busy-wait). Supports `shutdown()` for clean teardown.

### Backend
Tool implementations and LLM provider abstraction.
- ✅ **DONE**: Native tool calling for Claude (`providers.anthropic.AnthropicProvider`) and OpenAI-compatible endpoints (`providers.openai_chat.OpenAIChatProvider`), with text dialects (`providers.text_tools`) as a fallback. Swapping providers requires only the `LLM_PROVIDER` env var, `/provider` or `/config set`.
- ✅ **DONE**: `TokenRateLimiter` — sliding-window rate limiter (30 000 tokens / 60 s), configurable via `NTCODE_TOKEN_LIMIT_PER_MINUTE`.
- 🔲 **PLANNED**: MCP abstraction for tools — standardised tool interface compatible with the Model Context Protocol.

---

## Strategic Ideas

### Cache and Fine-Grained Rollbacks
Use conversation save points as good reset positions. Cache expensive context (e.g. `SYSTEM_PROMPT + outline.md`) server-side so it is not re-sent every turn. Implement fine-grained rollback controls before building the todo-list feature.

### Todo Lists
Store a prioritised task list in a file. The agent works through item #1, then resets to a cache point and moves to item #2. Requires rollback controls first.

### Batch Mode
ntCode reads tasks from a file and works through them deterministically — useful for reproducible automated testing.

### Skills (Roles) ✅
Paired system prompts + model endpoints + tool subsets, targeted at specific task domains. Implemented in `utils/roles.py`; three built-in roles: `developer`, `researcher`, `executive`. Activated via `/role load <name>`, deactivated via `/role unload`. Config overrides are saved and restored on unload. System-prompt file is swapped and the prompt cache invalidated automatically.

### Tests Before Commit
The system should run the test suite before any `git commit`, either inline or as a CI/git-action (tests + coverage).

### Environment Safety
Automatic backup of files before editing. Restricted-privilege sandbox execution.

### RAG (Retrieval-Augmented Generation)
Implement long-term memory and large-scale context ingestion via vector embeddings and retrieval tools.

### Workflow Vision
```
Issue Tracker → ntCode.py → git → CI
```
Issue tracker starts as a plain `.md` file; later integrates with a real tracker (GitHub Issues, Linear, etc.).

---

## Tool Roadmap

| Tool | Status |
|---|---|
| File operations (read, edit, list) | ✅ Done |
| Git integration (status, diff, add, commit, log) | ✅ Done |
| Bug / issue tracker reader | 🔲 Planned |
| Internet researcher | 🔲 Planned |
| MCP abstraction layer | 🔲 Planned |
| RAG / Knowledge Base tools | 🔲 Planned |

---

## Planned Features

### High Priority
- [ ] Automatic file backup before destructive edits
- [ ] Confirmation prompt for destructive operations

### Medium Priority
- [ ] Batch mode — process a list of tasks from a file non-interactively
- [ ] Issue tracker integration — read bugs and tasks from an external tracker
- [ ] Internet research tool
- [ ] Code analysis / linting integration
- [ ] Todo lists with rollback/checkpoint support
- [ ] RAG integration (Vector DB + Embedding tools)
- [x] Roles/Skills system — `utils/roles.py`, `roles/*.toml`, `/role` command ✅

### Low Priority
- [ ] Plugin system — dynamically register custom tools
- [ ] Web interface
- [ ] Tool usage analytics
- [ ] Conversation branching / forking
- [ ] AI-generated commit messages

---

## Implementation Status

### ✅ Completed
- Security framework (path validation, size limits, traversal protection)
- Roles/Skills: `utils/roles.py`, built-in developer / researcher / executive roles, `/role` slash-command
- File operations: read / edit / list
- Git workflow: status / diff / add / commit / log
- Frontend ↔ agent split via `Connector`
- Provider abstraction (`providers.base.Provider`: `AnthropicProvider`, `OpenAIChatProvider`, `TextToolsProvider`) on provider-neutral `core.types` messages
- Token rate limiting (`TokenRateLimiter`, 30 k TPM sliding window)
- Conversation pruning that keeps tool calls with their results (`ConversationManager.prune_task_messages()`)
- Typed provider errors (`providers.errors`) shown to the user without polluting the conversation
- Fully configurable via env vars (`config.py`, `.env.example`)
- Unit and integration test suite (`tests/`)
- `DummyProvider` and wire-contract fixtures for offline / deterministic testing
