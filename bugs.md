# Known Bugs — ntCode

This document tracks active bugs and their diagnostic analysis. Check here before starting any work.

> See **Next Immediate Actions** at the bottom for the prioritised fix list.

---

## Open Bugs

### 1. Claude duplicates tool-use documentation
- [ ] **Symptom**: Claude's responses sometimes re-narrate or re-document tool invocations that have already been executed and recorded, inflating conversation history.
- **Current evidence**: Debug logs show tool invocations are parsed correctly, but `extract_tool_invocations()` may also match natural-language prose that describes tool use.
- **Diagnostic needs**:
  - Log the exact wire payload sent to and received from the API (request body + response body).
  - Check `extract_tool_invocations()` regex/parser for false positives on prose.
  - Inspect whether the system prompt encourages Claude to narrate its own tool use.
- **Likely root causes**:
  - System prompt phrasing invites Claude to describe what it is about to do before doing it.
  - Parser over-matches natural-language mentions of tool names.

### 2. Timeout logging gaps
- [ ] **Symptom**: When a request times out, no root cause appears in the logs — only a generic timeout message.
- **Current evidence**: Anthropic API calls have timeout support in `AnthropicLLM.call()`, but elapsed time and request size are not always logged before the exception propagates.
- **Diagnostic needs**:
  - Log conversation history size (token estimate) immediately before every API call.
  - Log elapsed time even when the call raises an exception.
  - Test with progressively larger conversation histories to find the breaking point.
- **Likely root causes**:
  - Log statement only reached on success path, not in exception handler.
  - Large conversation histories sent with each request despite `_prune_conversation()`.

---

## Resolved Bugs

- ✅ **Malformed JSON crashes the application** — `extract_tool_invocations()` in `utils/agent.py` uses `except json.JSONDecodeError` (not bare `except Exception`) and logs bad payloads at WARNING level with the parse error included. Agent never crashes on malformed LLM output.
- ✅ **`test_api_key.py` hard-coded model and interactive prompt** — Now reads `ANTHROPIC_API_KEY` from environment/`.env` (no interactive prompt), and uses `DEFAULT_MODEL` from `utils/config.py` overridable via `NTCODE_MODEL` env var. Prints the model under test before the API call.
- ✅ **API timeout handling** — `AnthropicLLM.call()` includes timeout support; `execute_llm_call()` catches and humanises timeout exceptions.
- ✅ **Conversation memory leak** — `agent.py` prunes conversation history via `_prune_conversation()` (cap: `MAX_CONVERSATION_LENGTH`).
- ✅ **Debug `input()` pauses in agent loop** — Removed after frontend/agent split.
- ✅ **Hard-coded model name in main app** — Now read from `NTCODE_MODEL` env var via `config.py`.
- ✅ **No token rate limiting** — `TokenRateLimiter` enforces a 30 000 token/min sliding window.

---

## Next Immediate Actions

1. **Investigate tool-use duplication** *(Bug #1 above)* — Add wire-level request/response logging to identify whether the system prompt or the parser is the root cause.
2. **Improve error messages in tools** — Replace generic `Exception` text in tool files with user-friendly, actionable messages (distinguish "file not found" vs "permission denied" vs "file too large").

---

## Test Gaps

The following areas have no test coverage and need a `tests/test_conversation_manager.py`:

### Prompt-caching helpers (`utils/llm.py`)
- [ ] `apply_cache_control(block)` — returns new dict with `cache_control` key; original dict unmodified.
- [ ] `mark_last_content_block(content)` — only the last block is cache-marked; all others unchanged.
- [ ] `mark_last_content_block([])` — raises `ValueError` on empty list.

### `SessionHeader`
- [ ] `system_block()` — returns a one-element list; the block has `cache_control`.
- [ ] `as_user_message()` — role is `"user"`; last content block has `cache_control`.
- [ ] `as_assistant_ack()` — role is `"assistant"`; content is the expected ack string.
- [ ] `as_message_pair()` — returns exactly two messages in the correct order.
- [ ] `_load_docs()` — missing files are skipped with a warning, not raised.

### `ConversationManager` — basic state
- [ ] `add_user` / `add_assistant` — correct role and block structure appended.
- [ ] `start_task()` — clears task messages; optional description added as first user turn.
- [ ] `task_message_count` — reflects current length.
- [ ] `messages_for_api()` — header pair always prepended before task messages.
- [ ] `prune_task_messages(n)` — trims to `n`, keeps tail, never touches header.
- [ ] `as_flat_conversation()` — strips block structure; correct role/content pairs.
- [ ] `restore_from_flat()` — round-trips correctly: save → flat → restore → flat matches.

### `ConversationManager` — named save points
- [ ] `save_point(name)` captures current state; later mutations don't affect the snapshot.
- [ ] `restore(name)` replaces task messages with the snapshot; message count matches.
- [ ] Overwriting a save point with the same name reflects the newer state.
- [ ] `restore` after further changes rolls back cleanly.
- [ ] `delete_save_point(name)` removes the point; subsequent `restore` raises `KeyError`.
- [ ] `save_point_names` returns sorted list of active names.
- [ ] `save_point("")` raises `ValueError`.
- [ ] `restore("nonexistent")` raises `KeyError`.
- [ ] `delete_save_point("nonexistent")` raises `KeyError`.
- [ ] Save point survives `prune_task_messages()` (save points not stored in task list).
- [ ] Save point survives `start_task()` (save points are not cleared by reset).

### `AnthropicLLM` (unit, no API calls)
- [ ] `_needs_caching_beta()` — returns `True` when system list has `cache_control`.
- [ ] `_needs_caching_beta()` — returns `True` when a message content block has `cache_control`.
- [ ] `_needs_caching_beta()` — returns `False` when no markers present.
