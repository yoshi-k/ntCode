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

### Middleware to route messages to tools and to communicate with the llm 
Needs to handle tool implementation
Logs interactions, and all messages send and received.

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
Monitor token limits and implement throtteling.

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
| `ANTHROPIC_API_KEY` | string | required | Your Anthropic API key |

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
- [ ] **Add API timeout handling** - Implement timeout handling in `execute_llm_call()` function
- [ ] **Fix conversation memory leak** - Implement conversation history pruning to prevent infinite growth
- [ ] **Remove debug code** - Clean up debug prints and "Wait" input prompts in main loop

### 2. Configuration & Environment
- [ ] **Create .env.example file** - Document required environment variables
- [ ] **Add model configuration** - Make Claude model name configurable instead of hard-coded
- [ ] **Implement proper logging levels** - Replace print statements with proper logging
- [ ] **Add requirements.txt validation** - Ensure all dependencies are properly listed

### 3. Code Quality
- [ ] **Refactor tool execution logic** - Replace the large if-elif chain with dynamic parameter mapping
- [ ] **Add type validation** - Validate tool parameters before execution
- [ ] **Extract constants** - Move magic numbers and strings to configuration section
- [ ] **Split large functions** - Break down `run_coding_agent_loop()` into smaller functions

## MEDIUM PRIORITY TODOs

### 4. Testing & Documentation
- [ ] **Create comprehensive README** - Write proper documentation for setup and usage
- [ ] **Add unit tests** - Create test suite in the empty `tests/` directory
- [ ] **Document all environment variables** - Complete the environment variable documentation
- [ ] **Add API documentation** - Document all available tools and their parameters

### 5. Features & UX
- [ ] **Add help command** - Implement user help system for available commands
- [ ] **Implement conversation save/load** - Allow users to save and restore sessions
- [ ] **Add file backup before editing** - Backup files before making changes
- [ ] **Create batch operations** - Allow multiple files to be processed at once

### 6. Security & Safety
- [ ] **Add file extension validation** - Validate file types for safety
- [ ] **Implement rate limiting** - Add API call rate limiting
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
- [ ] **Fix the empty tests directory** - Add basic test structure
- [ ] **Update the API key test** - Fix the model name in `test_api_key.py` (uses wrong model)
- [ ] **Clean up debug output** - Remove the `input("Wait")` line that pauses execution
- [ ] **Add proper error messages** - Replace generic errors with user-friendly messages

## IMPLEMENTATION STATUS

### ✅ Completed Features
- **Security Framework**: ✅ **EXCELLENT** - Comprehensive security validation system implemented
- **File Operations**: ✅ **COMPLETE** - All file read/write/list operations with proper validation
- **Git Integration**: ✅ **COMPLETE** - All 5 git workflow tools fully implemented and tested
- **Path Validation**: ✅ **COMPLETE** - Multi-layer security with symlink protection
- **Error Handling**: ✅ **IMPLEMENTED** - Comprehensive exception handling for file operations
- **LLM Provider Abstraction**: ✅ **DONE** - `LLM` ABC + `AnthropicLLM` subclass; `execute_llm_call()` delegates to `llm.call()`; provider swappable via module-level `llm` variable

### 🔧 Current Implementation Issues
1. **JSON Parsing**: Tool invocation parsing can crash on malformed JSON
2. **API Timeouts**: No timeout handling for Anthropic API calls
3. **Memory Management**: Conversation history grows without bounds
4. **Debug Code**: Unnecessary debug prints and input pauses remain
5. **Hard-coded Configuration**: Model name and limits are not configurable

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
