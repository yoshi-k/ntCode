# Ideas
ntCoder is a exploration of ai coder written by vibecoding. The original implementation was copied from 
> Implementation of The Emperor Has No Clothes: How to Code Claude Code in 200 Lines of Code
> https://www.mihaileric.com/The-Emperor-Has-No-Clothes/ 
and copied from there by Joerg Kulbartz joerg@kulbartz.de 
Now this is going to become a exploration of 

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

#### Tools
- git Integration, commit, commit messages, 
write good diffs to understand what the coder did

- bug tracker
needs ability to read bugs and issues from bug tracker

- researcher 
read the internet


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

# Code Review and Improvement Outline for ntCode.py

## Code Review Summary

This is a Python implementation of a coding assistant that integrates with Claude AI and provides secure file manipulation tools. The code creates a conversational loop where users can interact with Claude, which can execute file operations through defined tools with comprehensive security validation.

### Security Implementation Status: ✅ STRONG
The code implements robust security measures including path validation, directory restrictions, file size limits, and protection against path traversal attacks.

## Strengths

1. **Clear Structure**: The code is well-organized with distinct functions for each tool
2. **Type Hints**: Good use of type annotations throughout
3. **Path Handling**: Robust path resolution with `resolve_abs_path()`
4. **Tool Registry Pattern**: Clean abstraction for tool management
5. **Error Handling**: Comprehensive error handling in file operations
6. **Security Implementation**: ✅ **EXCELLENT** - Comprehensive security validation system
7. **File Safety**: Protection against large files, path traversal, and unauthorized access
8. **Encoding Handling**: Graceful handling of different file encodings
9. **Path Validation**: Multi-layer security with symlink protection

## Issues and Areas for Improvement

### 1. Error Handling and Robustness
- **File Operations**: ✅ **IMPLEMENTED** - Comprehensive exception handling for file I/O operations
- **API Calls**: Missing error handling for Anthropic API failures
- **Silent Failures**: Tool invocation parsing fails silently
- **Resource Management**: ✅ **IMPLEMENTED** - Proper file handling with Path objects
- **Encoding Handling**: ✅ **IMPLEMENTED** - UTF-8 with latin-1 fallback for binary files

### 2. Security Concerns
- **Path Traversal**: ✅ **IMPLEMENTED** - Full path validation with `validate_file_access()` function
- **File Size Limits**: ✅ **IMPLEMENTED** - 10MB file size limit enforced
- **Directory Restrictions**: ✅ **IMPLEMENTED** - Access limited to current directory and subdirectories
- **Symlink Protection**: ✅ **IMPLEMENTED** - Validates symlink targets to prevent escape
- **Path Traversal Detection**: ✅ **IMPLEMENTED** - Prevents ".." path traversal attempts

### 3. Code Quality Issues
- **Hard-coded Values**: Model name and token limits are hard-coded
- **Magic Numbers**: ✅ **PARTIALLY FIXED** - Security constants now defined at top (MAX_FILE_SIZE, ALLOWED_BASE_PATHS)
- **Debugging Code**: ✅ **MOSTLY CLEAN** - Minimal debug prints remain
- **Color Constants**: ✅ **IMPLEMENTED** - Terminal color codes properly defined
- **Configuration**: Security settings properly configured at module level

### 4. Architecture and Design
- **Tool Invocation Logic**: Complex if-elif chain for tool execution
- **Conversation Management**: No limit on conversation history size
- **Global State**: Global `claude_client` variable
- **Mixed Responsibilities**: Main loop handles both UI and API logic

### 5. User Experience
- **Limited Feedback**: Minimal error messages for users
- **No Help System**: No way to get help or list available commands
- **No Configuration**: No way to configure model, tokens, etc.

## Suggested Improvements Outline

### Phase 1: Critical Fixes (Security & Stability)

#### 1.1 Enhanced Error Handling
- [x] **COMPLETED** - Add try-catch blocks around file operations
- [ ] Implement proper error handling for API calls
- [ ] Add logging system for debugging
- [x] **COMPLETED** - Validate file paths and prevent path traversal

#### 1.2 Security Improvements
- [x] **COMPLETED** - Implement file size limits for read operations (10MB)
- [x] **COMPLETED** - Add configurable allowed directories (ALLOWED_BASE_PATHS)
- [x] **COMPLETED** - Comprehensive path validation with `validate_file_access()`
- [ ] Validate file extensions for safety
- [ ] Add rate limiting for API calls
- [x] **COMPLETED** - Symlink security validation

### Phase 2: Enhanced Architecture

#### 2.1 Tool System Enhancement
- [ ] Implement dynamic tool parameter mapping
- [ ] Add tool parameter validation and type checking
- [ ] Create tool metadata system for better introspection
- [ ] Add tool usage analytics and monitoring

#### 2.2 Session Management
- [ ] Implement conversation history limits and pruning
- [ ] Add session save/restore functionality
- [ ] Create conversation export capabilities
- [ ] Implement conversation branching/forking

#### 2.3 Code Organization
- [ ] Encapsulate global client state
- [ ] Create configuration management class
- [ ] Split into logical modules (tools, security, conversation)
- [ ] Add comprehensive type validation

### Phase 3: Enhanced Functionality

#### 3.1 Better User Experience
- [ ] Add help command and documentation
- [ ] Implement conversation history management
- [ ] Add command history and recall
- [ ] Improve error messages and feedback

#### 3.2 Extended Tool Capabilities
- [ ] Add file search functionality
- [ ] Implement directory creation/deletion
- [ ] Add file backup before editing
- [ ] Create batch operation support

#### 3.3 Advanced Features
- [ ] Add conversation export/import
- [ ] Implement tool usage statistics
- [ ] Add plugin system for custom tools
- [ ] Create web interface option

### Phase 4: Testing & Documentation

#### 4.1 Testing Infrastructure
- [ ] Add unit tests for all functions
- [ ] Create integration tests
- [ ] Add mock tests for API interactions
- [ ] Implement end-to-end testing

#### 4.2 Documentation
- [ ] Create comprehensive README
- [ ] Add API documentation
- [ ] Write user guide
- [ ] Add developer documentation

## Implementation Priority

1. **High Priority**: Security fixes, error handling, path validation
2. **Medium Priority**: Code refactoring, configuration management
3. **Low Priority**: Enhanced features, web interface

## Specific Code Improvements

### Example: Better Error Handling
```python
def read_file_tool(filename: str) -> Dict[str, Any]:
    try:
        full_path = resolve_abs_path(filename)
        validate_file_access(full_path)  # New validation function
        
        if full_path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError(f"File too large: {full_path}")
            
        content = full_path.read_text(encoding='utf-8')
        return {"file_path": str(full_path), "content": content}
    except Exception as e:
        logger.error(f"Error reading file {filename}: {e}")
        return {"error": str(e), "file_path": filename}
```

### Example: Tool Registry Improvement
```python
class Tool:
    def __init__(self, name: str, func: Callable, description: str):
        self.name = name
        self.func = func
        self.description = description
        
    def execute(self, **kwargs):
        return self.func(**kwargs)
```

## Conclusion

The code provides a solid foundation for a coding assistant but needs significant improvements in error handling, security, and architecture. The suggested phases provide a structured approach to enhancement while maintaining functionality during development.
