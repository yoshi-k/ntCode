# Known Bugs — ntCode

This document tracks active bugs and their diagnostic analysis. Check here before starting any work.

> See **Next Immediate Actions** at the bottom for the prioritised fix list.

---

## Open Bugs

### 1. Malformed JSON crashes the application
- [ ] **Symptom**: If the LLM returns a tool invocation with malformed JSON arguments, the application crashes.
- **Vulnerable location** in `utils/agent.py` inside `extract_tool_invocations()`:
  ```python
  args = json.loads(json_str)  # crashes on malformed JSON
  ```
- **Diagnostic needs**:
  - Wrap every `json.loads()` call in `extract_tool_invocations()` with `except json.JSONDecodeError`.
  - Log the malformed payload so patterns can be identified.
  - Add a `DummyLLM` replay test with intentionally malformed JSON.
- **Fix**: Catch `json.JSONDecodeError`, log the bad string at WARNING level, and skip the invocation rather than crashing.

### 2. Timeout logging gaps
- [ ] **Symptom**: When a request times out, no root cause appears in the logs — only a generic timeout message.
- **Current evidence**: `run_git_command()` has a 30-second timeout; Anthropic API calls have timeout support in `AnthropicLLM.call()`, but the elapsed time and request size are not always logged before the exception propagates.
- **Diagnostic needs**:
  - Log conversation history size (token estimate) immediately before every API call.
  - Log elapsed time even when the call raises an exception.
  - Test with progressively larger conversation histories to find the breaking point.
- **Likely root causes**:
  - Log statement only reached on success path, not in exception handler.
  - Large conversation histories sent with each request despite `_prune_conversation()`.

### 3. Claude duplicates tool-use documentation
- [ ] **Symptom**: Claude's responses sometimes re-narrate or re-document tool invocations that have already been executed and recorded, inflating conversation history.
- **Current evidence**: Debug logs show tool invocations are parsed correctly, but `extract_tool_invocations()` may also match natural-language prose that describes tool use.
- **Diagnostic needs**:
  - Log the exact wire payload sent to and received from the API (request body + response body).
  - Check `extract_tool_invocations()` regex/parser for false positives on prose.
  - Inspect whether the system prompt encourages Claude to narrate its own tool use.
- **Likely root causes**:
  - System prompt phrasing invites Claude to describe what it is about to do before doing it.
  - Parser over-matches natural-language mentions of tool names.

---

## Resolved Bugs

- ✅ **API timeout handling** — `AnthropicLLM.call()` includes timeout support; `execute_llm_call()` catches and humanises timeout exceptions.
- ✅ **Conversation memory leak** — `agent.py` prunes conversation history via `_prune_conversation()` (cap: `MAX_CONVERSATION_LENGTH`).
- ✅ **Debug `input()` pauses in agent loop** — Removed after frontend/agent split.
- ✅ **Hard-coded model name** — Now read from `NTCODE_MODEL` env var via `config.py`.
- ✅ **No token rate limiting** — `TokenRateLimiter` enforces a 30 000 token/min sliding window.

---

## Next Immediate Actions

1. **Fix malformed JSON crash** *(Bug #1 — highest priority)* — Add `except json.JSONDecodeError` around `json.loads()` in `extract_tool_invocations()` in `utils/agent.py`; log and skip bad payloads.
2. **Update `test_api_key.py`** — The hard-coded model name is wrong and will fail against the current Anthropic API.
3. **Improve error messages in tools** — Replace generic `Exception` text in tool files with user-friendly, actionable messages (distinguish "file not found" vs "permission denied" vs "file too large").
