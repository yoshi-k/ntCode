# Code Review: `utils/llm.py` and `utils/openai_llm.py`

Reviewed by: AI code review  
Files: `utils/llm.py`, `utils/openai_llm.py`

---

## Overall Assessment

Both files are well-structured and clearly the product of deliberate design. The
module-level docstrings are thorough, the public API is clean, and the
responsibility split between the two files is logical. That said, there are a
number of bugs, inconsistencies, and quality issues worth addressing before
this code is relied on in production.

---

## Bugs

### BUG-1 — `execute_llm_call` catches `anthropic` exceptions for OpenAI calls (`llm.py`, line ~540)

**Severity: High**

The `except` clauses in `execute_llm_call` are all `anthropic.*` exception
types:

```python
except anthropic.APITimeoutError as e: ...
except anthropic.RateLimitError as e: ...
except anthropic.APIConnectionError as e: ...
except anthropic.AuthenticationError as e: ...
except anthropic.APIError as e: ...
```

When the active provider is `OpenAILLM`, errors raised by `OpenAILLM.call()`
are `httpx.TimeoutException`, `PermissionError`, `ValueError`, or plain
`RuntimeError`. None of these match the `anthropic.*` handlers. The only
catcher that will fire is the bare `except Exception`, which returns a generic
"Unexpected error" message instead of a useful diagnostic.

Specific examples of harm:
- A 401 from the OpenAI-compatible server raises `PermissionError` with a
  helpful message; the caller sees `💥 Unexpected error calling LLM: …` instead.
- A network timeout raises `httpx.TimeoutException`; the user gets no
  actionable advice about timeouts.

**Fix:** Either move error handling into each `LLM.call()` implementation and
have them raise a shared `LLMError` hierarchy, or add `httpx` and common
built-in exception types to the `execute_llm_call` handlers alongside the
`anthropic` ones.

---

### BUG-2 — `_build_payload` silently drops content blocks from structured messages (`openai_llm.py`, line ~160)

**Severity: Medium**

`_build_payload` reads `m["content"]` directly without checking whether it is
a string or a list of content blocks:

```python
openai_messages = [{"role": "system", "content": system}] + [
    {"role": m["role"], "content": m["content"]} for m in messages
]
```

When `ConversationManager.messages_for_api()` is used, messages can carry
`cache_control` blocks or multi-part content lists. Passing a `list` as the
`content` value to an OpenAI-compatible server that expects a string will
typically result in a `400 Bad Request`. The error message from
`_raise_for_4xx` will mention HTTP 400 but will not explain that the content
shape was wrong, making this hard to debug.

**Fix:** In `_build_payload`, detect list content and flatten it to a plain
string (concatenating all `text` blocks), or document clearly that
`ConversationManager` with cache markers is incompatible with `OpenAILLM`.

---

### BUG-3 — `_build_payload` will raise `KeyError` on messages without a `role` key (`openai_llm.py`, line ~160)

**Severity: Low–Medium**

The list comprehension `{"role": m["role"], "content": m["content"]}` performs
no defensive access. If a message dict is missing `role` or `content` (e.g.
due to a bug in `ConversationManager` or a caller constructing messages
manually), a raw `KeyError` propagates up through `_post_with_retry` and
eventually reaches `execute_llm_call`, where only `Exception` catches it —
yielding a generic error with no context about which message was malformed.

**Fix:** Use `.get()` with sensible defaults or add a validation step, and
raise a descriptive `ValueError` early.

---

### BUG-4 — `save_point` / `restore` perform a shallow copy, not a deep copy (`llm.py`, line ~310)

**Severity: Medium**

The snapshot is taken with:

```python
self._save_points[name] = [dict(m) for m in self._task_messages]
```

`dict(m)` copies only the top-level keys. Each message has a `content` key
whose value is a `list` of block dicts. That inner list is **not** copied;
both the snapshot and the live `_task_messages` share the same list object.
Mutating a content block in the live conversation (e.g. adding or removing
`cache_control`) will silently corrupt the snapshot.

The same problem exists in `restore()`:

```python
self._task_messages = [dict(m) for m in self._save_points[name]]
```

**Fix:** Use `copy.deepcopy` for both snapshot and restore operations.

---

### BUG-5 — `OpenAILLM` is never closed; the `httpx.Client` connection pool leaks (`openai_llm.py`)

**Severity: Low–Medium**

`OpenAILLM` exposes `close()`, `__enter__`, and `__exit__` for context-manager
usage, but the module-level `llm` singleton in `llm.py` is created with
`_build_llm()` and never closed — not at `switch_provider()` time and not at
process exit. When `switch_provider()` replaces the active `llm`, the previous
`OpenAILLM` instance is garbage-collected without `close()` being called,
leaking the underlying connection pool.

**Fix:** In `switch_provider()`, call `llm.close()` (guarded by
`hasattr(llm, "close")`) before replacing it. `AnthropicLLM` has no `close()`
so the guard keeps the code generic.

---

### BUG-6 — `_post_with_retry` sleeps after the last failed attempt (`openai_llm.py`, line ~185)

**Severity: Low**

The retry loop structure is:

```python
for attempt in range(1, self.max_retries + 1):
    ...   # may set last_error
    if attempt < self.max_retries:
        time.sleep(delay)
        delay *= 2
```

The `if attempt < self.max_retries` guard is correct in preventing a sleep
after the final attempt, but it is easy to break this guard accidentally during
refactoring. More importantly, when `max_retries=1` the loop body executes
exactly once and falls through to the `raise RuntimeError` with the message
`"All 1 attempts … failed"`. The singular/plural wording is mildly confusing
but not harmful. However, the initial `last_error = RuntimeError("No attempts
made")` sentinel can surface if `max_retries <= 0` — the loop body never runs
and the sentinel is raised. There is no validation of `max_retries`.

**Fix:** Add `if max_retries <= 0: raise ValueError("max_retries must be >= 1")`
in `__init__`.

---

## Code Quality Issues

### QUALITY-1 — Inconsistent f-string vs `%`-style logging

The codebase mixes two logging styles throughout both files:

```python
# f-string (does string interpolation even if log level is suppressed)
logger.info(f"Sending {len(messages)} messages to LLM (model={self.model})")

# %-style (lazy: interpolation only happens if the message is emitted)
logger.info("ConversationManager: save_point %r captured (%d messages)", name, n)
```

The `%`-style is the Python logging best practice because it avoids the
formatting cost when the log level is disabled. `llm.py` uses `%`-style in
`ConversationManager` but f-strings in `AnthropicLLM.call()`. `openai_llm.py`
uses f-strings exclusively. This should be standardised to `%`-style.

---

### QUALITY-2 — `execute_llm_call` has a mutable default argument

```python
def execute_llm_call(
    conversation: List[Dict[str, Any]],
    system_override: Any = None,
    messages_override: List[Dict[str, Any]] = None,   # <-- mutable default
) -> str:
```

Using `None` as the default and then checking `is not None` is correct
behaviour here, but the type annotation says `List[Dict[str, Any]]` while
the actual default is `None`. This is technically a type-annotation lie. It
should be annotated as `Optional[List[Dict[str, Any]]]`.

---

### QUALITY-3 — `LLM.call()` return type annotation is missing from the abstract method

```python
@abstractmethod
def call(self, system: Any, messages: List[Dict[str, Any]]) -> str:
```

The annotation is present. However, `OpenAILLM.call()` is declared as:

```python
def call(self, system: str, messages: List[Dict[str, str]]) -> str:
```

The parameter types are narrower than the abstract base (`str` instead of
`Any`, `List[Dict[str, str]]` instead of `List[Dict[str, Any]]`). This
violates the Liskov Substitution Principle: calling code typed against `LLM`
may pass a structured `system` list (as `ConversationManager` does), which
`OpenAILLM` is not declared to accept. MyPy will flag this. The signatures
should be consistent with the base class.

---

### QUALITY-4 — `as_flat_conversation` loses structured content silently

`as_flat_conversation()` collapses multi-block content into a single joined
string:

```python
text = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
```

This discards tool-result blocks, image blocks, or any non-text content type
silently. If `restore_from_flat()` is then called, the restored conversation
will be missing those blocks. The method docstring does not warn about this
loss. Either document the limitation clearly or raise an error if non-text
blocks are present.

---

### QUALITY-5 — `_build_llm` is called at module import time

```python
# Active LLM instance.
llm: LLM = _build_llm()
```

This executes `_build_llm()` the moment `utils.llm` is first imported, which:
- Reads environment variables immediately (can fail loudly at test import time
  if `ANTHROPIC_API_KEY` is absent).
- Creates an `httpx.Client` for `OpenAILLM` (opens a connection pool) at
  import time.
- Makes testing harder — tests that import anything from `utils.llm` must
  mock the environment before the import, or use `importlib.reload`.

**Fix:** Use lazy initialisation (initialise `llm = None` and build on first
call) or move the singleton creation into `main()`/startup code, not at
module level.

---

### QUALITY-6 — `SessionHeader._load_docs` reads files at `__init__` time relative to CWD

Doc paths like `"agent.md"` are resolved relative to the current working
directory at the time `SessionHeader` is constructed. If `ntCode` is ever
started from a directory other than the repo root, or if tests change the CWD,
the files will not be found and the warning will be silently swallowed. There
is no fallback that indicates to the user that the session header is running
without documentation context.

**Fix:** Resolve paths relative to the project root (e.g. `Path(__file__).parent.parent`)
or at least log a clear warning at a higher severity (e.g. `logger.error`)
when no docs loaded successfully.

---

### QUALITY-7 — Magic string `"prompt-caching-2024-07-31"` appears twice

In `AnthropicLLM.call()`:

```python
betas=["prompt-caching-2024-07-31"],
```

This string appears once in the `call()` method. It is also referenced by name
in the module docstring and the `SessionHeader` docstring. It should be a
named constant at the top of the file so a version bump requires only one
change:

```python
_PROMPT_CACHE_BETA = "prompt-caching-2024-07-31"
```

---

### QUALITY-8 — No `__all__` defined in `llm.py`

The module exports many symbols (`LLM`, `AnthropicLLM`, `SessionHeader`,
`ConversationManager`, `execute_llm_call`, `switch_provider`, `llm`, etc.).
Without `__all__`, `from utils.llm import *` would pull in all of them
including private helpers (`_build_llm`, `_EPHEMERAL`, `_ASSISTANT_ACK`, etc.).
Defining `__all__` makes the public API explicit and helps IDEs and static
analysers.

---

## Minor / Style Issues

| # | File | Issue |
|---|------|-------|
| S-1 | `llm.py` | `apply_cache_control` and `mark_last_content_block` use `list[...]` (lowercase) generics, while `LLM` and `AnthropicLLM` use `List[...]` from `typing`. The codebase should pick one style (lowercase generics require Python 3.9+; if 3.9+ is guaranteed, drop the `typing` imports). |
| S-2 | `openai_llm.py` | `_parse` is a `@staticmethod` that is only called from `call()`. It could be a module-level function, but as a static method it is fine. The docstring should mention what happens when `choices` is an empty list — currently `IndexError` is caught by the `except (KeyError, IndexError)` clause but the error message says "missing choices[0].message.content" which is slightly misleading for the empty-list case. |
| S-3 | `llm.py` | `_build_llm` contains a `_DEFAULT_URLS` dict inside `switch_provider`, but `switch_provider` also contains the same dict. The duplication between `_build_llm` and `switch_provider` means that adding a new provider alias requires updating two places. |
| S-4 | `openai_llm.py` | `retry_delay` is documented in the class docstring but not in `__init__` parameters — `__init__` has no per-parameter docstring at all. |
| S-5 | `llm.py` | `current_provider_name()` uses `getattr(llm, "model", "?")` which silently hides the case where the model attribute is missing. Since both concrete implementations always set `self.model`, this is safe today but fragile against future providers. |

---

## Summary Table

| ID | Severity | File | Description |
|----|----------|------|-------------|
| BUG-1 | High | `llm.py` | `execute_llm_call` only catches `anthropic` exceptions; OpenAI errors fall through to generic handler |
| BUG-2 | Medium | `openai_llm.py` | `_build_payload` breaks on structured (list) content blocks |
| BUG-3 | Medium | `openai_llm.py` | `_build_payload` raises bare `KeyError` on malformed messages |
| BUG-4 | Medium | `llm.py` | `save_point`/`restore` use shallow copy; inner content lists are shared |
| BUG-5 | Medium | `llm.py` | `OpenAILLM` `httpx.Client` is never closed on `switch_provider` |
| BUG-6 | Low | `openai_llm.py` | No validation of `max_retries <= 0` |
| QUALITY-1 | Low | both | Inconsistent f-string vs `%`-style logging |
| QUALITY-2 | Low | `llm.py` | Missing `Optional` in type annotation for `messages_override` |
| QUALITY-3 | Medium | `openai_llm.py` | `OpenAILLM.call()` signature narrower than `LLM.call()` — LSP violation |
| QUALITY-4 | Medium | `llm.py` | `as_flat_conversation` silently drops non-text content blocks |
| QUALITY-5 | Medium | `llm.py` | `_build_llm()` runs at import time, complicating testing and early failure |
| QUALITY-6 | Low | `llm.py` | Doc paths resolved relative to CWD; fragile outside repo root |
| QUALITY-7 | Low | `llm.py` | Beta string `"prompt-caching-2024-07-31"` should be a named constant |
| QUALITY-8 | Low | `llm.py` | No `__all__` defined |
