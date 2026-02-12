# Git Tools Testing Documentation

This document provides testing scenarios and examples for all 5 git workflow tools implemented in ntCode.py.

## 1. Git Status Tool

The `git_status_tool()` function shows repository status with categorized file listings.

**Purpose**: Display current repository state including staged, unstaged, and untracked files
**Parameters**: None
**Returns**: Repository status with branch info and file categorizations

### Test Scenarios:
- Basic repository status retrieval
- Parsing of staged, unstaged, and untracked files
- Branch information display
- Clean repository detection
- Summary statistics

## 2. Git Diff Tool

The `git_diff_tool(file_path, staged)` function displays file differences with optional filtering.

**Purpose**: Show file changes with detailed diff output
**Parameters**: 
- `file_path` (str): Optional file to show diff for (empty for all files)
- `staged` (bool): Whether to show staged changes (True) or unstaged (False)
**Returns**: Diff output with change statistics

### Test Scenarios:
- Show all unstaged changes
- Show all staged changes
- Show changes for specific file
- Diff output parsing and statistics
- Error handling for invalid files

## 3. Git Add Tool

The `git_add_tool(file_paths)` function stages files for commit with validation.

**Purpose**: Stage files for commit with comprehensive validation
**Parameters**: 
- `file_paths` (List[str]): List of file paths to stage
**Returns**: Result with staged files info and validation status

### Test Scenarios:
- Stage single file
- Stage multiple files
- Error handling for invalid files
- File path validation
- Success confirmation and staged file listing

## 4. Git Commit Tool

The `git_commit_tool(message, auto_generate)` function performs smart commits with optional auto-generated messages.

**Purpose**: Commit staged changes with manual or auto-generated messages
**Parameters**: 
- `message` (str): Commit message to use (optional if auto_generate is True)
- `auto_generate` (bool): Whether to auto-generate commit message based on staged changes
**Returns**: Commit result with commit info and staged files

### Test Scenarios:
- Commit with manual message
- Commit with auto-generated message
- Error handling when no files are staged
- Validation of commit message requirements
- Post-commit information display

## 5. Git Log Tool

The `git_log_tool(max_entries, file_path)` function shows commit history with filtering options.

**Purpose**: Display commit history with structured output and filtering
**Parameters**: 
- `max_entries` (int): Maximum number of log entries to return (default 10)
- `file_path` (str): Optional file path to show history for (empty for all commits)
**Returns**: Structured commit history with detailed information

### Test Scenarios:
- Show recent commit history
- Show commit history for specific file
- Limit number of entries
- Parse commit information (hash, author, date, message)
- Handle repositories with no commits

---

## Testing Workflow

1. **Preparation**: Ensure you're in a git repository with some changes
2. **Status Check**: Use git_status_tool() to see current state
3. **View Changes**: Use git_diff_tool() to examine modifications
4. **Stage Files**: Use git_add_tool() to stage desired changes
5. **Commit Changes**: Use git_commit_tool() to commit staged files
6. **View History**: Use git_log_tool() to see commit history

## Expected Outputs

Each tool returns a structured dictionary with:
- `success` (bool): Whether the operation succeeded
- `error` (str): Error message if operation failed
- Tool-specific data fields with relevant information

## Error Handling

All tools include comprehensive error handling for:
- Invalid file paths
- Permission errors
- Git repository validation
- Command execution failures
- Parameter validation