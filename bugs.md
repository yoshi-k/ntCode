# Known Bugs — ntCode

This document tracks active bugs and their diagnostic analysis. Check here before starting any work.

> See **Next Immediate Actions** at the bottom for the prioritised fix list.

---

## Open Bugs

---

## Resolved Bugs

- ✅ **Real OpenAI models don't invoke tools** — `OpenAILLM._build_payload()` now calls
  `_is_native_fc_model()` to detect `gpt-*`, `o1`, `o3`, `o4`, `chatgpt-*` models and
  injects a full OpenAI function-calling `tools` schema (built by `_build_tools_schema()`
  from `TOOL_REGISTRY`) plus `"tool_choice": "auto"` into the API payload.  The existing
  `_parse()` method already handled the response side: it converts `tool_calls` entries
  in the response back to `tool: NAME({...})` ntcode text so the rest of the stack needs
  no changes.  Local models (Ollama, LM Studio, etc.) are unaffected — `tools` is only
  added for detected GPT model names.

- ✅ **Timeout logging gaps** — `AnthropicLLM.call()` now wraps the API call in `try/finally`; elapsed time, model, estimated token count, and message count are logged at ERROR level whenever an exception is raised, before re-raising.
- ✅ **Claude duplicates tool-use documentation** — System prompt and `extract_tool_invocations()` parser reviewed; false positives resolved.
- ✅ **Malformed JSON crashes the application** — `extract_tool_invocations()` in `utils/agent.py` uses `except json.JSONDecodeError` (not bare `except Exception`) and logs bad payloads at WARNING level with the parse error included. Agent never crashes on malformed LLM output.
- ✅ **`test_api_key.py` hard-coded model and interactive prompt** — Now reads `ANTHROPIC_API_KEY` from environment/`.env` (no interactive prompt), and uses `DEFAULT_MODEL` from `utils/config.py` overridable via `NTCODE_MODEL` env var. Prints the model under test before the API call.
- ✅ **API timeout handling** — `AnthropicLLM.call()` includes timeout support; `execute_llm_call()` catches and humanises timeout exceptions.
- ✅ **Conversation memory leak** — `agent.py` prunes conversation history via `_prune_conversation()` (cap: `MAX_CONVERSATION_LENGTH`).
- ✅ **Debug `input()` pauses in agent loop** — Removed after frontend/agent split.
- ✅ **Hard-coded model name in main app** — Now read from `NTCODE_MODEL` env var via `config.py`.
- ✅ **No token rate limiting** — `TokenRateLimiter` enforces a 30 000 token/min sliding window.

---

## Next Immediate Actions

1. **Improve error messages in tools** — Replace generic `Exception` text in tool files with user-friendly, actionable messages (distinguish "file not found" vs "permission denied" vs "file too large").

---

## Recently Resolved

- ✅ **Gemma4 tool calling broken** — Gemma 3/4 instruct models (served via llama.cpp) emit tool calls in a unique format: `<|tool_call>call:tool:NAME({...})<tool_call|>` with optional JS-style unquoted keys. The `ntcode` parser could not parse this. Fixed by adding a `gemma` family to `utils/tool_format.py`: `_detect_family()` now returns `"gemma"` for any model name containing `"gemma"` (case-insensitive); `_format_tools_gemma()` instructs the model to use its native delimiter syntax with strict JSON; `_parse_gemma()` handles the delimiter tokens, strips the `call:tool:` prefix, and fixes unquoted keys via `_fix_unquoted_keys()` before JSON parsing. Full test coverage added in `tests/test_tool_format.py`.

---

## Test Gaps

### Roles subsystem (`utils/roles.py`, `tests/test_roles.py`)
✅ Covered by `tests/test_roles.py`:
- `_parse_role_dict()` — minimal role, missing section, empty name, tools list, invalid tools type, config overrides, RAG sources, system_prompt_file validation.
- `RoleDefinition.allows_tool()` — empty list (all allowed), specific allowlist.
- `list_roles()` — empty dir, nonexistent dir, multiple roles, broken TOML skipped.
- `_resolve_role_path()` — by name, case-insensitive, not found, absolute path.
- `load_role()` / `unload_role()` — activation, config restore, bad config rollback, system-prompt file override/restore.
- `is_tool_allowed()` — no role active, with allowlist.
- `handle_role_command()` — all sub-commands via `frontend.common`.
- `dispatch_line("/role ...")` — LOCAL result returned.
- `execute_tool_safely()` — blocks disallowed tool, allows permitted tool.



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
