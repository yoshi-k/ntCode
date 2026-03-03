# ntCode AI Coding Assistant

An AI-powered coding assistant that integrates with Claude AI to provide secure file manipulation, git workflow automation, and interactive development assistance. Built with security-first principles and comprehensive tool integration.

## 🚀 Features

- **Secure File Operations**: Read, edit, and list files with comprehensive path validation and access controls
- **Complete Git Integration**: Full workflow automation with status, diff, log, add, and commit operations
- **AI-Powered Assistance**: Natural language interaction with Claude AI for coding tasks
- **Security-First Design**: Restricted file system access, path validation, and protection against common vulnerabilities
- **Multiple Execution Modes**: Debug, verbose, and normal modes for different use cases
- **Comprehensive Logging**: Detailed conversation and operation logging for debugging and audit trails

## 📋 Requirements

- Python 3.7+
- Anthropic API key
- Git repository (for git operations)
- Required Python packages (see `requirements.txt`)

## ⚡ Quick Start

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd ntCode
   pip install -r requirements.txt
   ```

2. **Set up your API key**:
   ```bash
   cp .env.example .env
   # Edit .env and add your ANTHROPIC_API_KEY
   ```

3. **Run the assistant**:
   ```bash
   python ntCode.py
   ```

## 🔧 Configuration

### Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `ANTHROPIC_API_KEY` | string | **required** | Your Anthropic API key |
| `NTCODE_DEBUG` | true/false | false | Enable detailed debugging and logging |
| `NTCODE_VERBOSE` | true/false | false | Enable interactive tool approval |
| `NTCODE_LOG_CONVERSATIONS` | true/false | true | Enable conversation logging to file |

### Execution Modes

#### Normal Mode (Default)
```bash
python ntCode.py
```
- Clean execution without debug output
- Tools execute automatically
- Conversations logged to `ntcode.log`
- Best for regular usage

#### Debug Mode
```bash
NTCODE_DEBUG=true python ntCode.py
```
- Detailed logging to console and file
- Full conversation history logged
- API request/response details shown
- Tool invocation details logged
- Best for troubleshooting and development

#### Verbose Mode
```bash
NTCODE_VERBOSE=true python ntCode.py
```
- Interactive tool approval required
- User can see and approve each tool execution before it runs
- Helpful for security verification and learning
- Best for testing new prompts or when security is critical

#### Combined Debug + Verbose Mode
```bash
NTCODE_DEBUG=true NTCODE_VERBOSE=true python ntCode.py
```
- Full debugging with interactive approval
- Maximum visibility and control
- Best for development and security auditing

## 🛠️ Available Tools

### File Operations
- **`read_file`** - Read file contents with encoding detection
- **`edit_file`** - Replace text or create new files
- **`list_files`** - List directory contents

### Git Operations
- **`git_status`** - Show repository status (staged, unstaged, untracked files)
- **`git_add`** - Stage files for commit with validation
- **`git_commit`** - Smart commit with optional auto-generated messages
- **`git_diff`** - Display file differences (staged or unstaged)
- **`git_log`** - Show commit history with filtering options

## 🔒 Security Features

- **Path Validation**: All file operations are restricted to current directory and subdirectories
- **File Size Limits**: 10MB maximum file size for read/edit operations
- **Access Controls**: Protection against path traversal attacks and unauthorized access
- **Git Safety**: Git operations are validated and secured within repository bounds
- **Symlink Protection**: Safe handling of symbolic links with target validation
- **Interactive Approval**: Verbose mode allows manual approval of each tool execution

## 📁 Project Structure

```
ntCode/
├── ntCode.py          # Main application
├── outline.md         # Project roadmap and ideas
├── requirements.txt   # Python dependencies
├── tests/            # Test directory
│   └── test_api_key.py
├── .env.example      # Environment variables template
├── .gitignore        # Git ignore rules
└── README.md         # This file
```

## 💡 Usage Examples

### Basic File Operations
```
You: Read the contents of main.py
Assistant: tool: read_file({"filename": "main.py"})
```

### Git Workflow
```
You: Check git status and stage all modified files
Assistant: tool: git_status()
# ... shows current status ...
Assistant: tool: git_add({"file_paths": ["modified_file.py", "another_file.js"]})
```

### Code Editing
```
You: Replace the function definition in utils.py
Assistant: tool: edit_file({"path": "utils.py", "old_str": "def old_function():", "new_str": "def new_function():"})
```

## 📊 Logging

- **ntcode.log**: Contains conversation logs, tool executions, and debug information
- Automatically created when `NTCODE_LOG_CONVERSATIONS=true` (default)
- Useful for reviewing conversation history and debugging issues
- Debug mode provides additional detailed logging

## 🐛 Known Issues

1. **Timeout with very long requests** - Large conversations may cause API timeouts
2. **JSON parsing crashes** - Malformed JSON from Claude can crash the application
3. **Conversation memory growth** - Long sessions accumulate conversation history without pruning

## 🗺️ Roadmap

### Planned Architecture
- **Frontend**: Display messages and handle UI interactions
- **Middleware**: Route messages to tools and communicate with LLM
- **Backend**: Tool implementations and LLM provider abstractions

### Future Features
- **Issue Tracker Integration**: Read and manage bugs from issue trackers
- **Research Tools**: Internet research capabilities
- **Enhanced Git Features**: Intelligent commit messages and workflow automation
- **Plugin System**: Extensible tool architecture
- **Web Interface**: Optional web-based UI

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is inspired by "The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code" by Mihail Eric (https://www.mihaileric.com/The-Emperor-Has-No-Clothes/) and adapted by Joerg Kulbartz.

## 🙏 Acknowledgments

- Original implementation concept by Mihail Eric
- Enhanced and secured by Joerg Kulbartz (joerg@kulbartz.de)
- Built with Claude AI by Anthropic

## 📞 Support

For issues, questions, or contributions, please open an issue on the repository or contact the maintainer.

---

**Note**: This is an experimental AI coding assistant. Always review code changes and ensure you have backups before making significant modifications to your projects.