# Experimental
This is an experimental project. It works with Claude and with OpenAI-compatible servers such as llama.cpp, but expect rough edges.

# ntCode AI Coding Assistant

An AI coding assistant for the terminal. It gives a model tools for reading and editing files, git, web research, codebase search and persistent memory, with path validation, optional per-tool approval and role-based tool restrictions. It works with Claude (Anthropic API) and with any OpenAI-compatible server: llama.cpp, vLLM, Ollama, LM Studio, OpenAI, Groq.

> Originally inspired by ["The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code"](https://www.mihaileric.com/The-Emperor-Has-No-Clothes/) by Mihail Eric. Adapted and extended by Joerg Kulbartz (joerg@kulbartz.de).

> **Key docs:** [`agent.md`](agent.md) — orientation for agents/contributors · [`file_organization.md`](file_organization.md) — code map · [`prompt_doc.md`](prompt_doc.md) — prompt and tool calling · [`outline.md`](outline.md) — strategy & roadmap · [`bugs.md`](bugs.md) — known issues

---

## 🚀 Features

- **Native tool calling** — Claude and OpenAI-compatible servers receive tool definitions through their APIs; text tool-call formats are available as a fallback for servers without tool support
- **Local and hosted models** — Claude, or any OpenAI-compatible server; switch at runtime with `/provider` or `/config set`
- **Secure file operations** — Read, edit, and list files with path validation and a size limit; edits keep a backup
- **Git integration** — status, diff, log, add, and commit
- **Research and memory** — web search and page reading, codebase search, and persistent notes across sessions
- **Roles** — focused personas with their own tool allowlist, prompt and settings
- **Multiple execution modes** — interactive TUI, per-tool approval, batch and todo files
- **Conversation management** — pruning that keeps tool calls with their results, save/load, in-memory save points
- **Prompt caching** — Claude requests reuse the cached system prompt and conversation prefix
- **Clear error handling** — timeouts, rate limits, bad keys and server errors are reported as such, without polluting the conversation

---

## 📋 Requirements

- Python 3.10+
- One of:
  - an [Anthropic API key](https://console.anthropic.com/), or
  - an OpenAI-compatible server (for llama.cpp, start `llama-server` with `--jinja` so it handles tool calls)
- A git repository (for the git tools)

---

## ⚡ Quick Start

1. **Clone and install:**
   ```bash
   git clone <repository-url>
   cd ntCode
   pip install -r requirements.txt
   ```

2. **Configure the model** in `.env` (`cp .env.example .env`):
   ```bash
   # Claude
   ANTHROPIC_API_KEY=your-key

   # ...or a local OpenAI-compatible server
   LLM_PROVIDER=openai
   OPENAI_BASE_URL=http://localhost:8080/v1
   OPENAI_MODEL=your-model-name
   ```
   `start_qwen.sh` is an example script for a llama.cpp server.

3. **Run:**
   ```bash
   python ntCode.py
   ```

4. **Optional:** create the starter roles with `python bootstrap_roles.py`.

---

## 🔧 Configuration

### Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` \| `openai` | `anthropic` | Claude, or an OpenAI-compatible server |
| `ANTHROPIC_API_KEY` | string | — | Anthropic API key (needed for Claude) |
| `NTCODE_MODEL` | string | `claude-sonnet-4-6` | Claude model |
| `NTCODE_API_TIMEOUT` | seconds | `600` | Timeout for Claude requests |
| `OPENAI_BASE_URL` | URL | `http://localhost:11434/v1` | OpenAI-compatible endpoint, including `/v1` |
| `OPENAI_API_KEY` | string | `ollama` | API key; local servers accept any value |
| `OPENAI_MODEL` | string | `llama3` | Model name the server knows |
| `OPENAI_MAX_TOKENS` | int | `0` | Output limit; `0` lets the server decide |
| `OPENAI_TEMPERATURE` | float | `0.7` | Sampling temperature |
| `OPENAI_TIMEOUT` | seconds | `120` | Timeout for OpenAI-compatible requests |
| `OPENAI_MAX_RETRIES` | int | `3` | Attempts per request on transient errors |
| `CALLING_CONVENTION` | `auto`\|`native`\|`ntcode`\|`xml`\|`json_block`\|`gemma` | *(native)* | Tool calling for OpenAI-compatible servers: native (default) or a text format; see [Tool Calling](#-tool-calling). Also accepted as `NTCODE_CALLING_CONVENTION`. |
| `NTCODE_TOKEN_LIMIT_PER_MINUTE` | int | `30000` | Client-side token rate limit |
| `NTCODE_DEBUG` | true/false | false | Detailed logging to console and file |
| `NTCODE_VERBOSE` | true/false | false | Ask for approval before each tool runs |
| `NTCODE_LOG_CONVERSATIONS` | true/false | true | Log to `ntcode.log` |
| `NTCODE_SYSTEM_PROMPT_FILE` | path | `system_prompt.md` | System-prompt stub (relative to the repo root, or absolute); see [`prompt_doc.md`](prompt_doc.md) |

### Execution Modes

#### Normal Mode (Default)
```bash
python ntCode.py
```
- Tools execute automatically
- Conversations logged to `ntcode.log`

#### Debug Mode
```bash
NTCODE_DEBUG=true python ntCode.py
```
- Detailed logging to console and file, including tool calls and results

#### Verbose Mode
```bash
NTCODE_VERBOSE=true python ntCode.py
```
- Interactive approval required before each tool executes; a rejected call is reported back to the model

#### Batch Mode
```bash
python ntCode.py --batch tasks.txt --out results.txt
```
- Reads instructions from a plain-text file (one per line; `#` lines and blank lines are skipped)
- Writes all responses to `results.txt`: `=== [N] You: <instruction> ===` / response / blank line
- Slash-commands (`/reset`, `/save`, `/savepoint`, `/restore`, …) work as in the TUI
- Tool-approval prompts (verbose mode) are auto-approved with a log warning

#### Todo Mode
```bash
python ntCode.py --todo tasks.md --out results.txt
```
- Reads a Markdown file of `# TODO: <title>` tasks, each optionally with a `## Role: <name>` line
- Runs each task with a fresh context, in the given role

---

## 🛠️ Available Tools

### Files and code

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with UTF-8 / latin-1 encoding detection |
| `edit_file` | Replace the first occurrence of a string, or create/overwrite a file; keeps a backup in `backups/` |
| `list_files` | List contents of a directory |
| `search_codebase` | Search file contents for a keyword or regex, with a glob filter |

### Git

| Tool | Description |
|------|-------------|
| `git_status` | Show staged, unstaged, and untracked files |
| `git_add` | Stage one or more files for commit |
| `git_commit` | Commit staged changes with a message or an auto-generated one |
| `git_diff` | Show staged or unstaged diffs, optionally for one file |
| `git_log` | Show commit history, optionally for one file |

### Web

| Tool | Description |
|------|-------------|
| `search_web` | Search the web using DuckDuckGo |
| `read_web` | Fetch a web page and extract its main text |

### Memory

| Tool | Description |
|------|-------------|
| `memory_store` | Save a note to `storage/memory/` that persists across sessions |
| `memory_search` | Search stored notes by keyword and tags |
| `memory_list` | List stored notes, optionally by tag |

`/tools` lists the tools available in the current session.

---

## ⌨️ Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/reset` | Clear the conversation (the system prompt is kept) |
| `/save [file]` · `/load [file]` | Save or load the conversation (default folder: `saves/`) |
| `/savepoint <name>` · `/restore <name>` · `/savepoints` | In-memory save points |
| `/prompt` | Show the system prompt exactly as the model receives it |
| `/tools` | List available tools |
| `/provider` · `/provider list` | Show the current provider, or the known aliases |
| `/provider <alias>[/<model>]` | Switch provider and optionally model, e.g. `/provider anthropic/claude-opus-5`, `/provider openai/gemma-4`, `/provider ollama/qwen3` |
| `/config ...` | View and change settings; see below |
| `/role ...` | List, load, show or unload roles; see below |
| `/quit` · `/exit` | Exit |

`/provider openai/...` uses the configured `OPENAI_BASE_URL`; `ollama`, `lmstudio` and `groq` use their standard URLs.

---

## ⚙️ Runtime Configuration

Settings can be viewed and changed at runtime with `/config`, without a restart. Changing a provider setting (provider, model, URL, key, timeout, tool-calling convention, …) rebuilds the model client immediately.

### View settings
```
/config                        # show all settings (grouped, with change markers)
/config help GIT_TIMEOUT       # show description, current value, and default for one key
```

### Change settings
```
/config set DEFAULT_MODEL claude-opus-5
/config set OPENAI_MODEL gemma-4-26B-A4B-it-UD-Q8_K_XL.gguf
/config set CALLING_CONVENTION gemma
/config set VERBOSE_MODE true
```

Type coercion is automatic: booleans accept `true/false/yes/no/1/0`; integers and floats accept numeric strings.

### Save and load
```
/config save                   # save to ntcode_config.json
/config save my_settings.json  # save to a named file
/config load                   # load from ntcode_config.json
/config load my_settings.json  # load from a named file
```

Saved files are plain JSON and can be edited by hand. Unknown keys in a file are skipped; validation errors are reported per key without aborting the load.

### Reset
```
/config reset                  # restore all settings to startup defaults
/config reset GIT_TIMEOUT      # restore one setting to its startup default
```

### Configurable keys

| Key | Type | Description |
|-----|------|-------------|
| `LLM_PROVIDER` | str | Active provider (`anthropic` \| `openai`) |
| `DEFAULT_MODEL` | str | Claude model (starts as `NTCODE_MODEL`) |
| `ANTHROPIC_API_KEY` | str | Anthropic API key (masked in display) |
| `API_TIMEOUT` | float | Claude request timeout (seconds) |
| `OPENAI_MODEL` | str | OpenAI-compatible model name |
| `OPENAI_BASE_URL` | str | OpenAI-compatible endpoint URL |
| `OPENAI_API_KEY` | str | OpenAI-compatible API key (masked in display) |
| `OPENAI_MAX_TOKENS` | int | Output limit (0 = server default) |
| `OPENAI_TEMPERATURE` | float | Sampling temperature (0.0–2.0) |
| `OPENAI_TIMEOUT` | float | OpenAI-compatible request timeout (seconds) |
| `OPENAI_MAX_RETRIES` | int | Attempts per request on transient errors |
| `CALLING_CONVENTION` | str | `''` / `auto` / `native` = native tool calling; `ntcode` \| `xml` \| `json_block` \| `gemma` = text format |
| `GIT_TIMEOUT` | int | Git command timeout (seconds) |
| `TOKEN_LIMIT_PER_MINUTE` | int | Token rate limit per minute |
| `MAX_CONVERSATION_LENGTH` | int | Max task-context messages before pruning |
| `MAX_FILE_SIZE` | int | Max file size in bytes for read/edit |
| `SYSTEM_PROMPT_FILE` | str | Path to the system-prompt stub file |
| `DEBUG_MODE` | bool | Enable detailed debug logging |
| `VERBOSE_MODE` | bool | Enable interactive tool-approval prompts |
| `LOG_CONVERSATIONS` | bool | Log conversations to `ntcode.log` |

---

## 🔌 Tool Calling

**Claude** (`LLM_PROVIDER=anthropic`) always uses the API's native tool calling:
tool definitions travel in the request, and tool calls and results are kept as
structured messages.

**OpenAI-compatible servers** (`LLM_PROVIDER=openai`) also use native tool
calling by default: ntCode sends the tools in the request's `tools` field and
the server parses the model's tool calls with the model's own chat template.
This works with OpenAI, llama.cpp (`llama-server --jinja`), vLLM
(`--enable-auto-tool-choice --tool-call-parser <name>`), Ollama, LM Studio and
Groq, for any model whose template supports tools (Gemma 4, Qwen, Llama 3.x,
Mistral, …). To check whether a server returns structured tool calls:

```bash
python scripts/capture_wire_fixture.py --provider openai \
    --base-url http://localhost:8080/v1 --model your-model --name check
```

For a server or model without tool support, choose a text format with
`CALLING_CONVENTION`. ntCode then describes the tools in the system prompt,
parses calls out of the reply text, and sends results back as text in strictly
alternating turns:

| Format | Syntax | Typical models |
|--------|--------|----------------|
| `ntcode` | `tool: NAME({...})` | any instruction-following model |
| `xml` | `<tool_call>{...}</tool_call>` | Qwen2.5-Instruct, Qwen3 |
| `json_block` | ` ```json {"tool": ...} ``` ` | Mistral, Mixtral |
| `gemma` | `<\|tool_call>call:tool:NAME({...})<tool_call\|>` | Gemma 3/4 instruct |

```bash
# In .env:
CALLING_CONVENTION=gemma

# Or on the command line:
CALLING_CONVENTION=gemma python ntCode.py

# Or at runtime:
/config set CALLING_CONVENTION gemma
```

Unset, `auto` or `native` means native tool calling. Details:
[`prompt_doc.md`](prompt_doc.md).

---

## 🎭 Roles

Roles give the agent a focused persona, a restricted toolset, a custom system prompt and setting overrides, all activated with a single command. Run `python bootstrap_roles.py` once to create the starter roles in `roles/`.

### Using roles

```
/role                          # list available roles
/role load developer           # activate the developer role
/role show                     # show details of the currently active role
/role unload                   # deactivate and restore defaults
```

### Starter roles

| Role | Tools | Description |
|------|-------|-------------|
| **developer** | All tools | Full-access developer: file editing, git workflow, and web research. |
| **researcher** | `read_file`, `list_files`, `search_web`, `read_web` | Read-only file access plus web search, with a research-focused system prompt. |
| **executive** | `read_file`, `list_files`, `search_web`, `read_web` | Read-only file access plus web research, with a concise, executive-style system prompt. |

### Creating custom roles

1. Create a `.toml` file in the `roles/` directory:
   ```toml
   # roles/myrole.toml
   [role]
   name = "myrole"
   description = "A short description of the role."
   system_prompt_file = "roles/prompts/myrole.md"   # optional

   tools = [                                          # optional — omit to allow all tools
       "read_file",
       "list_files",
       "search_web",
   ]

   [config]                                           # optional /config overrides
   OPENAI_TEMPERATURE = "0.7"
   ```
2. (Optional) Add a system-prompt stub in `roles/prompts/myrole.md`. Put `{{TOOLS}}` where the note about tools should go; the tool definitions themselves are supplied by the provider.
3. Activate with `/role load myrole`.

A role's `[config]` can also switch the provider or model (e.g. `LLM_PROVIDER`, `OPENAI_MODEL`); the client is rebuilt on load and restored on unload.

---

## 🔒 Security Features

- **Path Validation** — All file operations restricted to the current directory and subdirectories
- **File Size Limit** — 10 MB maximum for read/edit operations
- **Path Traversal Protection** — Blocks `..` sequences and symlinks that escape allowed paths
- **Git Scope Validation** — Git operations validated within repository bounds
- **Role Tool Allowlists** — A role can only call the tools it lists
- **Interactive Approval** — Verbose mode lets you approve every tool call before it runs

---

## 💡 Usage Examples

### Ask about your code
```
You: Read ntCode.py and summarise the security features
```

### Edit a file
```
You: In utils.py replace the old_function definition with new_function
```

### Git workflow
```
You: Show git status, then stage and commit all modified files with a good message
```

---

## 📊 Logging

- **`ntcode.log`** — model requests (timing, token usage, cache hits, tool calls), tool executions and errors
- Created automatically when `NTCODE_LOG_CONVERSATIONS=true` (default)
- Debug mode adds tool arguments and results

---

## 🧪 Testing

```bash
./run_tests.sh        # or: pytest tests/
```

The suite runs offline. Provider behaviour is pinned by wire-contract fixtures in `tests/fixtures/wire/`, which record the exact HTTP requests ntCode must send and the responses it must understand; see [`tests/fixtures/wire/README.md`](tests/fixtures/wire/README.md).

---

## 🐛 Known Issues

See [`bugs.md`](bugs.md) for details.

1. **Pruning counts messages, not tokens** — the conversation is trimmed at `MAX_CONVERSATION_LENGTH` messages, so a few very large tool results can still approach the model's context limit.
2. **Text formats depend on the model** — with `CALLING_CONVENTION` set to a text format, a model that does not follow the syntax will not call tools; prefer native tool calling where the server supports it.
3. **`frontend/task_loop.py` is not wired in** — `--batch` and `--todo` still use the separate `batch_loop.py` and `todo_loop.py`.

---

## 🗺️ Roadmap

See [`outline.md`](outline.md). Ideas include:
- Token-based conversation pruning or summarisation
- Streaming replies in the TUI
- Issue tracker integration (read bugs and tasks)
- MCP tool support and a plugin system for custom tools
- Web interface

---

## 📁 Project Structure

```
ntCode/
├── frontend/          # TUI, batch and todo interfaces
├── core/              # Provider-neutral message types and tool schemas
├── providers/         # Model API adapters (Anthropic, OpenAI-compatible, text formats)
├── tools/             # Tool implementations and registry
├── utils/             # Agent loop, configuration, prompt, roles, security
├── tests/             # Test suite and wire-contract fixtures
├── scripts/           # Developer scripts
├── experiments/       # Experimental scripts
├── ntCode.py          # Main entry point
└── ...                # Configuration and documentation
```

See [`file_organization.md`](file_organization.md) for the full map.

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push your changes: `git push origin feature/my-feature`
5. Open a Pull Request

Read [`agent.md`](agent.md) first; it lists the rules for the model backend.

---

## 🙏 Acknowledgments

- Original concept by [Mihail Eric](https://www.mihaileric.com/The-Emperor-Has-No-Clothes/)
- Built with [Claude AI](https://www.anthropic.com/) by Anthropic

---

**Note:** This is an experimental AI coding assistant. Always review generated changes and keep backups before making significant modifications to your projects.
