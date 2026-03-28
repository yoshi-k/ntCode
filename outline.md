# Ideas
ntCoder is a exploration of ai coder written by vibecoding. The original implementation was copied from 
> Implementation of The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code
> https://www.mihaileric.com/The-Emperor-Has-No-Clothes/ 
and copied from there by Joerg Kulbartz joerg@kulbartz.de 

## Restart
Save conversation to file, such that one can restart a new version of ntCoder

Reset conversation from a clean cached version. Just systemprompt. 
## Tests
System needs ability to conduct test before git.
(Or perhaps tests and test of test coverage as git action.) 

## Environment
Should automatically backup and have restricted priviledges

## Workflow ideas
Issue Tracker -> ntCoder.py -> git -> CI 
At first issue tracker probably just .org or .md file 
later real issue tracker 

## Architecture
Front-end Middleware Backend architecture

### Frontend to display messages and handle all ui. 
Chat with llm, help, query of logs and backend message flow
- ✅ **DONE**: `frontend/agent_loop.py` is now a pure TUI shell (`input`/`print` only).
  It starts `run_agent()` in a background thread and communicates exclusively through
  the `Connector` class. No LLM or tool code remains in the frontend.

### Middleware to route messages to tools and to communicate with the llm 
Needs to handle tool implementation
Logs interactions, and all messages send and received.
- ✅ **DONE**: `utils/agent.py` contains the pure agent loop (conversation history,
  LLM calls, tool dispatch, tool invocation parsing). Zero UI code.
- ✅ **DONE**: `utils/connector.py` is the stable, thread-safe API between any
  frontend and the agent. Two-directional queues with blocking `Event`-based receives
  (no busy-wait). Supports `shutdown()` for clean teardown.
  `frontend/connector.py` is a backward-compat re-export shim (imports from `utils.connector`).

### Backend 
Tools, in particular a good mcp abstraction
LLMs abstracted for different providers
- ✅ **DONE**: Minimal LLM provider abstraction implemented
  - `LLM` abstract base class (`abc.ABC`) with single method `call(system, messages) -> str`
  - `AnthropicLLM(LLM)` wraps the Anthropic SDK; logs token counts and elapsed time
  - Exception handling (timeouts, rate limits, auth errors) remains in `execute_llm_call()`, not in the class
  - Active provider instantiated as module-level `llm: LLM = AnthropicLLM(...)` from env vars
  - Swapping providers requires only a one-line reassignment of `llm`



#### Tools
- git Integration, commit, commit messages, 
write good diffs to understand what the coder did

- bug tracker
needs ability to read bugs and issues from bug tracker

- researcher 
read the internet


## Better logging for timeout
In case of timeout no cause is in the logs

## Token limits
✅ **DONE**: Sliding-window token rate limiter implemented (30 000 tokens / 60 s).
- `TokenRateLimiter` class with a rolling 60-second `deque` of `(timestamp, tokens)` pairs
- `wait_for_capacity(n)` blocks before every API call until capacity is available, then reserves the tokens atomically
- `record_actual(actual, estimated)` corrects the reservation with real usage from `response.usage`
- Thread-safe via `threading.Lock`; limit tunable via `NTCODE_TOKEN_LIMIT_PER_MINUTE` env var
- Integrated as the single choke-point inside `AnthropicLLM.call()`; status printed in every log line

# Usage

## Running ntCode

The ntCode application supports multiple execution modes controlled by environment variables:

### Normal Mode (Default)
```bash
python ntCode.py
```
- Clean execution without debug output
- Tools execute automatically
- Conversations logged to `ntcode.log`
- Best for regular usage

### Debug Mode
```bash
NTCODE_DEBUG=true python ntCode.py
```
- Detailed logging to console and file
- Full conversation history logged
- API request/response details shown
- Tool invocation details logged
- Best for troubleshooting and development

### Verbose Mode
```bash
NTCODE_VERBOSE=true python ntCode.py
```
- Interactive tool approval required
- User can see and approve each tool execution before it runs
- Helpful for security verification and learning
- Best for testing new prompts or when security is critical

### Combined Debug + Verbose Mode
```bash
NTCODE_DEBUG=true NTCODE_VERBOSE=true python ntCode.py
```
- Full debugging with interactive approval
- Maximum visibility and control
- Best for development and security auditing

### Disable Conversation Logging
```bash
NTCODE_LOG_CONVERSATIONS=false python ntCode.py
```
- Disables conversation logging to file
- Useful for privacy or storage concerns

## Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `NTCODE_DEBUG` | true/false | false | Enable detailed debugging and logging |
| `NTCODE_VERBOSE` | true/false | false | Enable interactive tool approval |
| `NTCODE_LOG_CONVERSATIONS` | true/false | true | Enable conversation logging to file |
| `ANTHROPIC_API_KEY` | string | required (Anthropic) | Your Anthropic API key. Not needed when using `LLM_PROVIDER=openai`. |
| `NTCODE_TOKEN_LIMIT_PER_MINUTE` | integer | 30000 | Max tokens consumed per 60-second sliding window |
| `LLM_PROVIDER` | `anthropic` / `openai` | `anthropic` | Select the LLM backend. Set to `openai` to route via `OpenAILLM` (e.g. to a local llama.cpp server). |
| `OPENAI_API_KEY` | string | required if openai | API key for the OpenAI-compatible endpoint. |
| `OPENAI_BASE_URL` | URL | — | Base URL of the OpenAI-compatible server (e.g. `http://nt-angband.local:8080/v1`). |
| `OPENAI_MODEL` | string | — | Model name to request from the OpenAI-compatible endpoint. |

## Log Files

- **ntcode.log**: Contains conversation logs, tool executions, and debug information
- Automatically created when `NTCODE_LOG_CONVERSATIONS=true` (default)
- Useful for reviewing conversation history and debugging issues

## Security Features

- **Path Validation**: All file operations are restricted to current directory and subdirectories
- **File Size Limits**: 10MB maximum file size for read/edit operations
- **Git Safety**: Git operations are validated and secured
- **Verbose Mode**: Allows manual approval of each tool execution for maximum security

# Current bugs
Timeout with very long requests
Claude has a tendency to document tool use in a way that duplicates tool use
try to figure out what is actually send on the wire. 
If the llm returns malformed json the application crashes.

## Bug Analysis & Diagnostic Requirements

### 1. Timeout with very long requests
**Current Evidence**: 30-second timeout in `run_git_command()` but no timeout handling for Anthropic API calls.

**Diagnostic Needs**:
- Add comprehensive logging to track API request/response times
- Monitor conversation history size - large conversations could cause timeouts
- Check for timeout handling in `execute_llm_call()` function
- Test with progressively longer inputs to find breaking point

**Likely Root Causes**:
- Anthropic API has built-in timeouts that aren't handled
- Large conversation histories being sent with each request
- No conversation pruning mechanism

### 2. Claude duplicates tool use documentation
**Current Evidence**: Debug code shows tool invocations are parsed but may be over-documented.

**Diagnostic Needs**:
- Examine actual wire protocol - what's sent to/from Claude
- Log conversation array to detect tool result duplication
- Check `extract_tool_invocations()` parsing logic for edge cases
- Monitor conversation flow for circular tool calls

**Likely Root Causes**:
- Tool results added to conversation but Claude includes them in responses
- `extract_tool_invocations()` may over-parse natural language mentions
- System prompt may encourage documentation of tool usage

### 3. Malformed JSON crashes application
**Current Evidence**: `extract_tool_invocations()` has bare `except Exception:` but `json.loads()` could still crash.

**Diagnostic Needs**:
- Add comprehensive error handling around `json.loads()` calls
- Log malformed JSON attempts to understand failure patterns
- Test with intentionally malformed JSON responses
- Add validation before JSON parsing

**Vulnerable Code Location**:
```python
args = json.loads(json_str)  # This could crash without proper handling
```

## Planned Diagnostic Implementation

### Phase 1: Enhanced Logging System
- Comprehensive debug logger with file output
- API call timing and size monitoring
- Conversation history tracking
- Tool invocation pattern detection

### Phase 2: Error Recovery & Validation
- Safe JSON parsing with error recovery
- Conversation size management and pruning
- Timeout handling for API calls
- Circular tool call detection

### Phase 3: Wire Protocol Analysis
- Log actual requests/responses to/from Claude
- Track conversation state changes
- Monitor tool result handling
- Identify duplication patterns 

# Code Review and TODO List for ntCode.py

## Project Overview

ntCode is a comprehensive AI coding assistant that integrates with Claude AI and provides secure file manipulation and git workflow tools. The project shows excellent security implementation and solid architecture, but needs attention to stability, documentation, and user experience improvements.

### Security Implementation Status: ✅ STRONG
The code implements robust security measures including path validation, directory restrictions, file size limits, and protection against path traversal attacks.

## Project Strengths

1. **Clear Structure**: Well-organized code with distinct functions for each tool
2. **Type Hints**: Good use of type annotations throughout
3. **Path Handling**: Robust path resolution with `resolve_abs_path()`
4. **Tool Registry Pattern**: Clean abstraction for tool management
5. **Security Implementation**: ✅ **EXCELLENT** - Comprehensive security validation system
6. **File Safety**: Protection against large files, path traversal, and unauthorized access
7. **Git Integration**: ✅ **COMPLETE** - All 5 git workflow tools fully implemented and tested
8. **Encoding Handling**: Graceful handling of different file encodings
9. **Path Validation**: Multi-layer security with symlink protection

## HIGH PRIORITY TODOs

### 1. Bug Fixes & Stability
- [ ] **Fix JSON parsing crashes** - Add robust error handling for malformed JSON in `extract_tool_invocations()`
- [x] **Add API timeout handling** - ✅ `AnthropicLLM` makes the Anthropic API request with timeout support; `execute_llm_call()` catches and humanises timeout exceptions.
- [x] **Fix conversation memory leak** - ✅ `agent.py` prunes conversation history via `_prune_conversation()`.
- [x] **Remove debug code** - ✅ Refactor separated TUI from agent; no debug `input()` pauses remain in the agent loop.

### 2. Configuration & Environment
- [x] **Create .env.example file** - ✅ `.env.example` exists with all supported environment variables.
- [x] **Add model configuration** - ✅ `config.py` reads model name and all `NTCODE_*` settings from environment variables.
- [x] **Implement proper logging levels** - ✅ `config.py` configures the `logging` framework with console and file handlers; no bare `print()` statements in agent or tool code.
- [ ] **Add requirements.txt validation** - Ensure all dependencies are properly listed

### 3. Code Quality
- [x] **Refactor tool execution logic** - ✅ `registry.py` `execute_tool_safely()` introspects signatures and fills defaults dynamically; no if-elif chain.
- [x] **Add type validation** - ✅ `execute_tool_safely()` validates parameters before execution.
- [x] **Extract constants** - ✅ All constants and magic values centralised in `config.py`.
- [x] **Split large functions** - ✅ `run_coding_agent_loop()` is now a thin TUI shell; agent logic lives in `utils/agent.py`.

## MEDIUM PRIORITY TODOs

### 4. Testing & Documentation
- [x] **Create comprehensive README** - ✅ `README.md` covers quick-start, configuration, execution modes, tools, security, and roadmap.
- [x] **Add unit tests** - ✅ `tests/` contains `test_security.py`, `test_basic.py`, and `test_extract_tool_invocations.py`.
- [x] **Document all environment variables** - ✅ Environment variable table in Usage section above; also in `README.md`.
- [x] **Add API documentation** - ✅ All tools documented in `file_organization.md` and advertised via `get_tool_str_representation()` in `registry.py`.

### 5. Features & UX
- [ ] **Add help command** - Implement user help system for available commands
- [ ] **Implement conversation save/load** - Allow users to save and restore sessions
- [ ] **Add file backup before editing** - Backup files before making changes
- [ ] **Create batch operations** - Allow multiple files to be processed at once

### 6. Security & Safety
- [ ] **Add file extension validation** - Validate file types for safety
- [x] **Implement rate limiting** - ✅ Sliding-window token rate limiter (30k TPM) implemented in `TokenRateLimiter`
- [ ] **Add operation confirmation** - Require confirmation for destructive operations
- [ ] **Audit security validation** - Review and test all security measures

## LOW PRIORITY TODOs

### 7. Architecture & Extensibility
- [ ] **Create plugin system** - Allow custom tools to be added
- [ ] **Add web interface option** - Create optional web UI
- [ ] **Implement tool analytics** - Track tool usage statistics  
- [ ] **Add conversation branching** - Allow conversation forking

### 8. Advanced Features
- [ ] **Intelligent commit messages** - Use AI to generate better git commit messages
- [ ] **Code analysis tools** - Add tools for code quality analysis
- [ ] **Integration with issue trackers** - Implement bug tracker integration as outlined
- [ ] **Research capabilities** - Add internet research tools

## QUICK WINS (Can be done immediately)
- [x] **Fix the empty tests directory** - ✅ Three test files now exist in `tests/`.
- [ ] **Update the API key test** - Fix the model name in `test_api_key.py` (uses wrong model)
- [x] **Clean up debug output** - ✅ Agent/tool refactor removed all `input("Wait")` pauses.
- [ ] **Add proper error messages** - Replace generic errors with user-friendly messages

## IMPLEMENTATION STATUS

### ✅ Completed Features
- **Security Framework**: ✅ **EXCELLENT** - Comprehensive security validation system implemented
- **File Operations**: ✅ **COMPLETE** - All file read/write/list operations with proper validation
- **Git Integration**: ✅ **COMPLETE** - All 5 git workflow tools fully implemented and tested
- **Path Validation**: ✅ **COMPLETE** - Multi-layer security with symlink protection
- **Error Handling**: ✅ **IMPLEMENTED** - Comprehensive exception handling for file operations
- **LLM Provider Abstraction**: ✅ **DONE** - `LLM` ABC + `AnthropicLLM` subclass; `execute_llm_call()` delegates to `llm.call()`; provider swappable via module-level `llm` variable
- **Token Rate Limiting**: ✅ **DONE** - `TokenRateLimiter` enforces 30 000 tokens/min sliding window; integrated into `AnthropicLLM.call()`; configurable via `NTCODE_TOKEN_LIMIT_PER_MINUTE`

### 🔧 Current Implementation Issues
1. **JSON Parsing**: Tool invocation parsing can crash on malformed JSON — still open.
2. ~~**API Timeouts**: No timeout handling for Anthropic API calls~~ — ✅ resolved.
3. ~~**Memory Management**: Conversation history grows without bounds~~ — ✅ resolved via `_prune_conversation()`.
4. ~~**Debug Code**: Unnecessary debug prints and input pauses remain~~ — ✅ resolved.
5. ~~**Hard-coded Configuration**: Model name and limits are not configurable~~ — ✅ resolved via `config.py`.

## DEVELOPMENT PHASES

### Phase 1: Stability & Core Fixes (High Priority)
**Target**: Make the system robust and production-ready
- Fix JSON parsing crashes
- Add API timeout handling
- Implement conversation pruning
- Remove debug artifacts
- Add proper configuration management

### Phase 2: Documentation & Testing (Medium Priority)  
**Target**: Improve maintainability and reliability
- Create comprehensive README
- Build unit test suite
- Document all APIs and environment variables
- Add user help system

### Phase 3: Enhanced Features (Low Priority)
**Target**: Expand functionality and user experience
- Add conversation save/load
- Implement plugin system
- Create web interface option
- Add advanced git features

## NEXT IMMEDIATE ACTIONS
1. **Fix debug code**: Remove `input("Wait")` line that blocks execution
2. **Update API test**: Fix model name in `test_api_key.py`
3. **Add basic tests**: Create initial test structure in `tests/` directory
4. **Create .env.example**: Document required environment variables
5. **Add error recovery**: Implement robust JSON parsing with fallbacks

## PROJECT VISION

ntCode aims to become a comprehensive AI-powered development environment with:
- **Secure Execution**: Robust security without sacrificing functionality
- **Git Integration**: Complete workflow automation for version control
- **Extensible Architecture**: Plugin system for custom tools and integrations
- **User-Friendly Interface**: Both CLI and optional web interface
- **Production Ready**: Comprehensive testing, documentation, and error handling

The foundation is solid - now we need to polish the rough edges and expand the feature set systematically.
