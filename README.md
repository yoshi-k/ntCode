# ntCode AI Coding Assistant

An AI-powered coding assistant that integrates with Claude AI to provide secure file manipulation, git workflow automation, and interactive development assistance. Built with security-first principles and comprehensive tool integration.

> Originally inspired by ["The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code"](https://www.mihaileric.com/The-Emperor-Has-No-Clothes/) by Mihail Eric. Adapted and extended by Joerg Kulbartz (joerg@kulbartz.de).

> **Key docs:** [`agent.md`](agent.md) — orientation for agents/contributors · [`outline.md`](outline.md) — strategy & roadmap · [`bugs.md`](bugs.md) — known issues · [`file_organization.md`](file_organization.md) — code map

---

## 🚀 Features

- **Secure File Operations** — Read, edit, and list files with path validation and access controls
- **Complete Git Integration** — Full workflow automation: status, diff, log, add, and commit
- **AI-Powered Assistance** — Natural language interaction with Claude AI for coding tasks
- **Security-First Design** — Restricted file system access and protection against path traversal
- **Multiple Execution Modes** — Normal, debug, verbose, and batch modes for different use cases
- **Comprehensive Logging** — Conversation and operation logging for debugging and audit trails
- **Conversation Pruning** — Automatically trims history to stay within token limits
- **API Error Handling** — Graceful recovery from timeouts, rate limits, and connection errors

---

## 📋 Requirements

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com/)
- Git repository (for git operations)

---

## ⚡ Quick Start

1. **Clone and install:**
   ```bash
   git clone <repository-url>
   cd ntCode
   pip install -r requirements.txt
   ```

2. **Configure your API key:**
   ```bash
   cp .env.example .env
   # Edit .env and set ANTHROPIC_API_KEY
   ```

3. **Run:**
   ```bash
   python ntCode.py
   ```

---

## 🔧 Configuration

### Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `ANTHROPIC_API_KEY` | string | **required** | Your Anthropic API key |
| `DEFAULT_MODEL` | string | `claude-3-5-sonnet-20241022` | Claude model to use |
| `NTCODE_DEBUG` | true/false | false | Enable detailed debugging and logging |
| `NTCODE_VERBOSE` | true/false | false | Enable interactive tool approval |
| `NTCODE_LOG_CONVERSATIONS` | true/false | true | Enable conversation logging to file |
| `NTCODE_API_TIMEOUT` | seconds | `60` | Timeout for Anthropic API calls |
| `NTCODE_SYSTEM_PROMPT_FILE` | path | `system_prompt.md` | Path to the system-prompt stub file (relative to repo root, or absolute). Edit `system_prompt.md` to customise the base instructions, inlined context files, and tool-use format. |
| `CALLING_CONVENTION` | `auto`\|`ntcode`\|`xml`\|`json_block`\|`gemma` | *(auto)* | Force a specific tool-calling format instead of auto-detecting from the model name. Also accepted as `NTCODE_CALLING_CONVENTION`. |

### Execution Modes

#### Normal Mode (Default)
```bash
python ntCode.py
```
- Clean execution without debug output
- Tools execute automatically
- Conversations logged to `ntcode.log`

#### Debug Mode
```bash
NTCODE_DEBUG=true python ntCode.py
```
- Detailed logging to console and file
- Full conversation history and API timing logged
- Tool invocation details shown

#### Verbose Mode
```bash
NTCODE_VERBOSE=true python ntCode.py
```
- Interactive approval required before each tool executes
- Useful for security verification and learning

#### Combined Debug + Verbose
```bash
NTCODE_DEBUG=true NTCODE_VERBOSE=true python ntCode.py
```
- Maximum visibility and control
- Best for development and security auditing

#### Batch Mode
```bash
python ntCode.py --batch tasks.txt --out results.txt
```
- Reads instructions from a plain-text file (one per line; `#` lines and blank lines are skipped)
- Writes all responses to `results.txt` in a structured format: `=== [N] You: <instruction> ===` / response / blank line
- Slash-commands (`/reset`, `/save`, `/savepoint`, `/restore`, …) work exactly as in the TUI
- Tool-approval prompts (VERBOSE_MODE) are auto-approved with a log warning
- Useful for reproducible automation and testing

#### Disable Conversation Logging
```bash
NTCODE_LOG_CONVERSATIONS=false python ntCode.py
```
- Disables writing to `ntcode.log`
- Useful for privacy or storage constraints

#### Override Tool-Calling Format
```bash
CALLING_CONVENTION=xml python ntCode.py
```
- Forces a specific tool-calling convention instead of auto-detecting from the model name
- Useful when a model uses a non-standard format or auto-detection picks the wrong family
- Also settable as `NTCODE_CALLING_CONVENTION=xml`

---

## 🛠️ Available Tools

### File Operations

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with UTF-8 / latin-1 encoding detection |
| `edit_file` | Replace first occurrence of a string, or create/overwrite a file |
| `list_files` | List contents of a directory |

### Git Operations

| Tool | Description |
|------|-------------|
| `git_status` | Show staged, unstaged, and untracked files |
| `git_add` | Stage one or more files for commit |
| `git_commit` | Commit staged changes with a message or auto-generated one |
| `git_diff` | Show staged or unstaged diffs, optionally filtered by file |
| `git_log` | Show commit history, optionally filtered by file |

### Web Operations

| Tool | Description |
|------|-------------|
| `search_web` | Search the web using DuckDuckGo |
| `read_web` | Fetch a webpage and extract its main text content |

---

## ⚙️ Runtime Configuration

All environment variables can be viewed and changed at runtime via the `/config` slash command — no restart needed.

### View settings
```
/config                        # show all settings (grouped, with change markers)
/config help GIT_TIMEOUT       # show description, current value, and default for one key
```

### Change settings
```
/config set DEFAULT_MODEL claude-3-5-sonnet-20241022
/config set GIT_TIMEOUT 60
/config set VERBOSE_MODE true
/config set OPENAI_TEMPERATURE 0.3
```

Type coercion is automatic: booleans accept `true/false/yes/no/1/0`; integers and floats accept numeric strings.

### Save and load
```
/config save                   # save to ntcode_config.json
/config save my_settings.json  # save to a named file
/config load                   # load from ntcode_config.json
/config load my_settings.json  # load from a named file
```

Saved files are plain JSON and can be edited by hand.  Unknown keys in a file are silently skipped; validation errors are reported per-key without aborting the load.

### Reset
```
/config reset                  # restore all settings to startup defaults
/config reset GIT_TIMEOUT      # restore one setting to its startup default
```

### Configurable keys

| Key | Type | Description |
|-----|------|-------------|
| `LLM_PROVIDER` | str | Active provider (`anthropic` \| `openai`) |
| `DEFAULT_MODEL` | str | Anthropic model name |
| `ANTHROPIC_API_KEY` | str | Anthropic API key (masked in display) |
| `OPENAI_MODEL` | str | OpenAI-compatible model name |
| `OPENAI_BASE_URL` | str | OpenAI-compatible endpoint URL |
| `OPENAI_API_KEY` | str | OpenAI API key (masked in display) |
| `OPENAI_MAX_TOKENS` | int | Max tokens for OpenAI responses (0 = server default) |
| `CALLING_CONVENTION` | str | Tool-calling format: `''`/`auto` = infer from model; `ntcode` \| `xml` \| `json_block` \| `gemma` = force a format |
| `OPENAI_TEMPERATURE` | float | Sampling temperature for OpenAI (0.0–2.0) |
| `API_TIMEOUT` | float | LLM API call timeout (seconds) |
| `GIT_TIMEOUT` | int | Git command timeout (seconds) |
| `OPENAI_TIMEOUT` | float | OpenAI endpoint timeout (seconds) |
| `OPENAI_MAX_RETRIES` | int | Max retries for OpenAI endpoint |
| `TOKEN_LIMIT_PER_MINUTE` | int | Token rate limit per minute |
| `MAX_CONVERSATION_LENGTH` | int | Max task-context messages before pruning |
| `MAX_FILE_SIZE` | int | Max file size in bytes for read/edit |
| `SYSTEM_PROMPT_FILE` | str | Path to the system-prompt stub file |
| `DEBUG_MODE` | bool | Enable detailed debug logging |
| `VERBOSE_MODE` | bool | Enable interactive tool-approval prompts |
| `LOG_CONVERSATIONS` | bool | Log conversations to `ntcode.log` |

---

## 🎭 Roles

Roles let you give the agent a focused persona, a restricted toolset, and a custom system prompt — all activated with a single command.

### Using roles

```
/role                          # list available roles
/role load developer           # activate the developer role
/role show                     # show details of the currently active role
/role unload                   # deactivate and restore defaults
```

### Built-in roles

| Role | Tools | Description |
|------|-------|-------------|
| **developer** | All tools | Full-access developer: file editing, git workflow, and web research. |
| **researcher** | `read_file`, `list_files`, `search_web`, `read_web` | Read-only file access plus web search. Uses a custom system prompt for research-focused responses. |
| **executive** | `read_file`, `list_files`, `search_web`, `read_web` | Read-only file access plus web research. Uses a concise, executive-style system prompt. |
| **researcher** | `read_file`, `list_files`, `search_web`, `read_web` | Read-only file access plus web search. Uses a custom system prompt for research-focused responses. |
| **executive** | `read_file`, `list_files`, `search_web`, `read_web` | Read-only file access plus web research. Uses a concise, executive-style system prompt. |

### Tool-Calling Format

ntCode auto-detects the correct tool-calling syntax from the model name:

| Family | Syntax | Auto-detected for |
|--------|--------|-------------------|
| `ntcode` | `tool: NAME({...})` | Claude, GPT-\*, and all other models (default) |
| `xml` | `<tool_call>{...}</tool_call>` | Qwen2.5-Instruct, Qwen3 |
| `json_block` | ` ```json {"tool": ...} ``` ` | Mistral, Mixtral |
| `gemma` | `<\|tool_call>call:tool:NAME({...})<tool_call\|>` | Gemma 3/4 instruct |

To override auto-detection, set `CALLING_CONVENTION` (or `NTCODE_CALLING_CONVENTION`) to the family name:

```bash
# In .env:
CALLING_CONVENTION=xml

# Or on the command line:
CALLING_CONVENTION=xml python ntCode.py
```

Setting it to `auto` (or leaving it empty) restores model-name inference.

---

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

   [config]                                           # optional
   OPENAI_TEMPERATURE = "0.7"
   ```
2. (Optional) Add a system-prompt stub in `roles/prompts/myrole.md`. Include `{{TOOLS}}` where you want the tool list injected.
3. Activate with `/role load myrole`.

---

## 🔒 Security Features

- **Path Validation** — All file operations restricted to current directory and subdirectories
- **File Size Limit** — 10 MB maximum for read/edit operations
- **Path Traversal Protection** — Blocks `..` sequences and symlinks that escape allowed paths
- **Git Scope Validation** — Git operations validated within repository bounds
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

- **`ntcode.log`** — Conversation logs, tool executions, API timing, and token usage
- Created automatically when `NTCODE_LOG_CONVERSATIONS=true` (default)
- Debug mode adds full request/response detail

---

## 🐛 Known Issues

See [`bugs.md`](bugs.md) for full details and diagnostic analysis of each issue.

1. **Malformed JSON in tool calls** — Can crash the application; fix in progress (highest priority).
2. **API timeouts on very long requests** — Largely handled gracefully, but some timeout paths lack root-cause logging.
3. **Claude duplicates tool-use documentation** — Claude occasionally re-narrates tool invocations; under investigation.
4. **Large individual messages** — Conversation is pruned at `MAX_CONVERSATION_LENGTH` messages, but a single very large message can still approach token limits.

---

## 🗺️ Roadmap

### Planned Architecture
- **Frontend** — Chat UI, help system, log viewer
- **Middleware** — Message routing, LLM abstraction, full wire-level logging
- **Backend** — Pluggable tool system, MCP abstraction, multi-provider LLM support

### Future Features
- Issue tracker integration (read bugs and tasks)
- Internet research tool
- Conversation save/load (restart sessions)
- Automated file backups before edits
- Web interface
- Plugin system for custom tools

---

## 📁 Project Structure

```
ntCode/
├── frontend/          # TUI and Batch interfaces
├── tools/             # Tool implementations
├── utils/             # Backend infrastructure (LLM, security, etc.)
├── tests/             # Test suite
├── experiments/       # Experimental scripts
├── ntCode.py          # Main entry point
├── README.md          # This file
└── ...                # Configuration and documentation
```

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push your changes: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 🙏 Acknowledgments

- Original concept by [Mihail Eric](https://www.mihaileric.com/The-Emperor-Has-No-Clothes/)
- Built with [Claude AI](https://www.anthropic.com/) by Anthropic

---

**Note:** This is an experimental AI coding assistant. Always review generated changes and keep backups before making significant modifications to your projects.