# ntCode AI Coding Assistant

An AI-powered coding assistant that integrates with Claude AI to provide secure file manipulation, git workflow automation, and interactive development assistance. Built with security-first principles and comprehensive tool integration.

> Originally inspired by ["The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code"](https://www.mihaileric.com/The-Emperor-Has-No-Clothes/) by Mihail Eric. Adapted and extended by Joerg Kulbartz (joerg@kulbartz.de).

---

## 🚀 Features

- **Secure File Operations** — Read, edit, and list files with path validation and access controls
- **Complete Git Integration** — Full workflow automation: status, diff, log, add, and commit
- **AI-Powered Assistance** — Natural language interaction with Claude AI for coding tasks
- **Security-First Design** — Restricted file system access and protection against path traversal
- **Multiple Execution Modes** — Debug, verbose, and normal modes for different use cases
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
| `NTCODE_MODEL` | string | `claude-sonnet-4-6` | Claude model to use |
| `NTCODE_DEBUG` | true/false | false | Enable detailed debugging and logging |
| `NTCODE_VERBOSE` | true/false | false | Enable interactive tool approval |
| `NTCODE_LOG_CONVERSATIONS` | true/false | true | Enable conversation logging to file |
| `NTCODE_API_TIMEOUT` | seconds | `60` | Timeout for Anthropic API calls |

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

#### Disable Conversation Logging
```bash
NTCODE_LOG_CONVERSATIONS=false python ntCode.py
```
- Disables writing to `ntcode.log`
- Useful for privacy or storage constraints

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

1. **API timeouts on very long requests** — Handled gracefully; user sees a friendly message and can retry
2. **Malformed JSON in tool calls** — Logged and skipped; does not crash the application
3. **Large individual messages** — Conversation is pruned at 50 messages (`MAX_CONVERSATION_LENGTH`), but single very large messages can still approach token limits

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
├── ntCode.py           # Main application
├── outline.md          # Project roadmap and ideas
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
├── .gitignore          # Git ignore rules
├── tests/              # Test suite
│   └── test_api_key.py
└── README.md           # This file
```

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push to the branch: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 🙏 Acknowledgments

- Original concept by [Mihail Eric](https://www.mihaileric.com/The-Emperor-Has-No-Clothes/)
- Built with [Claude AI](https://www.anthropic.com/) by Anthropic

---

**Note:** This is an experimental AI coding assistant. Always review generated changes and keep backups before making significant modifications to your projects.
