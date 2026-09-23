# ntCode — Prompt Architecture & Calling Conventions

This document explains how the system prompt is assembled at runtime,
how tool descriptions are injected into it, and how to add support for
a new model's tool-calling convention.

---

## Table of contents

1. [The system prompt stub](#1-the-system-prompt-stub)
2. [How the prompt is built at runtime](#2-how-the-prompt-is-built-at-runtime)
3. [The `{{TOOLS}}` placeholder and calling conventions](#3-the-tools-placeholder-and-calling-conventions)
4. [Built-in calling conventions](#4-built-in-calling-conventions)
   - 4.1 [ntcode (default)](#41-ntcode-default--claude-gpt--llama)
   - 4.2 [xml (Qwen)](#42-xml--qwen25-instruct-qwen3)
   - 4.3 [json_block (Mistral / Mixtral)](#43-json_block--mistral--mixtral)
5. [How the active convention is selected](#5-how-the-active-convention-is-selected)
6. [Adding a new calling convention](#6-adding-a-new-calling-convention)
7. [Customising the prose part of the prompt](#7-customising-the-prose-part-of-the-prompt)
8. [Prompt caching](#8-prompt-caching)
9. [Debugging the assembled prompt](#9-debugging-the-assembled-prompt)

---

## 1. The system prompt stub

The source of truth for the system prompt is **`system_prompt.md`** at the
repo root.  It is a plain Markdown file with two kinds of special directive:

```
{{FILE:relative/path.md}}
```
Replaced at runtime with the full text of the named file, relative to the
repo root.  Use this to inline documentation, context files, or anything
you want the model to see on every request without duplicating it in the
stub.

```
{{TOOLS}}
```
Replaced at runtime with the formatted tool-description block.  The exact
format depends on which model is active (see §3 below).  There should be
exactly one `{{TOOLS}}` in the stub — the build step replaces the first
occurrence only.

The current stub looks like this:

```markdown
You are a coding assistant …

When you want to use a tool, reply with exactly one line in the format:
'tool: TOOL_NAME({JSON_ARGS})' …

## Project context

{{FILE:agent.md}}
{{FILE:file_organization.md}}

## Available tools

{{TOOLS}}
```

> **Note:** The prose instructions at the top (the `tool: NAME({…})` syntax
> description) belong to the `ntcode` calling convention and should be
> updated or removed when targeting a model that uses a different convention.
> See §7 for how to maintain per-model stub variants.

---

## 2. How the prompt is built at runtime

The build pipeline lives in **`utils/prompt.py`** and runs once per process
(the result is cached).  The steps are:

```
system_prompt.md
      │
      ▼
_resolve_file_directives()      ← inlines every {{FILE:path}}
      │
      ▼
_build_tool_block()             ← calls format_tools_for_provider()
      │                            which picks the right formatter
      ▼                            for the active provider / model
build_system_prompt()  →  cached string  →  sent to LLM on every request
```

**`_resolve_file_directives(text, base)`**
- Scans for `{{FILE:path}}` directives.
- Reads each file relative to the repo root.
- Inlines its content in place.
- If a file is missing, logs a warning and leaves a `<!-- FILE NOT FOUND -->`
  comment so the problem is visible to the model.
- Any literal `{{TOOLS}}` strings found *inside* an inlined file are
  temporarily replaced with an internal sentinel so they are not treated as
  injection targets — only the one `{{TOOLS}}` in the stub itself is expanded.

**`_build_tool_block()`**
- Reads `LLM_PROVIDER` and the active model name from `utils/config.py`.
- Calls `utils.tool_format.format_tools_for_provider(provider, model,
  TOOL_REGISTRY)` to obtain the formatted tool descriptions.
- Returns that string to be substituted for `{{TOOLS}}`.

**`invalidate_cache()`** in `utils/prompt.py` clears the module-level cache
so the next call to `build_system_prompt()` re-reads all files from disk.
Call this in tests or after a runtime provider switch.

---

## 3. The `{{TOOLS}}` placeholder and calling conventions

Different models have been trained to emit tool calls in different textual
formats.  Getting this wrong — showing a model tool descriptions in the
wrong syntax, or trying to parse its output with the wrong parser — is the
most common source of tool-use failures.

ntCode handles this in one place: **`utils/tool_format.py`**.  It contains:

| Symbol | Purpose |
|---|---|
| `_detect_family(provider, model)` | Maps a provider + model name to a format family string. |
| `_FORMAT_REGISTRY` | Maps family name → formatter function. |
| `_PARSER_REGISTRY` | Maps family name → parser function. |
| `format_tools_for_provider(provider, model, registry)` | Public API: returns the `{{TOOLS}}` block for a given model. |
| `get_parser_for_provider(provider, model)` | Public API: returns the response-parser callable for a given model. |

The formatter and the parser for the same family are always paired:
the formatter writes tool descriptions in a syntax the model has been
trained on, and the parser reads the model's output in exactly that syntax.

The active parser is selected once at agent startup (in `utils/agent.py`) and
reused for every turn:

```python
_active_parser = get_parser_for_provider(LLM_PROVIDER, _resolve_active_model())
```

`extract_tool_invocations(text)` in `utils/agent.py` is a thin wrapper around
`_active_parser`.

---

## 4. Built-in calling conventions

### 4.1 `ntcode` (default) — Claude, GPT-*, Llama, Phi, Gemma

**Trigger:** any model whose name does not contain `qwen`, `mistral`, or
`mixtral`.

**How the model is asked to call a tool** (injected via the prose at the top
of `system_prompt.md` *and* via the tool descriptions):

```
tool: TOOL_NAME({"arg": "value"})
```

The line must start with `tool:`, be on a line by itself, use compact
single-line JSON, and close with `)`.  No other text on that line.

**Tool description block** example (produced by `_format_tools_ntcode`):

```
TOOL
===

    Name: read_file
    Description:
    Gets the full content of a file provided by the user.
    :param filename: The name of the file to read.
    :return: The full content of the file.

    Signature: (filename: str) -> Dict[str, Any]

===============
```

**Parser** (`_parse_ntcode`): scans line-by-line for `tool:` prefix, splits
on first `(`, strips the trailing `)`, JSON-parses the body.  Strict: skips
lines with missing parentheses, unknown tool names, non-dict JSON, or invalid
JSON.

**Tool result** fed back to the model:

```
tool_result({"key": "value", ...})
```

#### Native tool calling (the default)

The text formats in this section are only used when `CALLING_CONVENTION`
names one of them. By default both providers use native tool calling:

- **Claude** (`providers/anthropic.py`): tools are sent as `tools` with
  `input_schema`; calls come back as `tool_use` blocks and results go back as
  `tool_result` blocks.
- **OpenAI-compatible endpoints** (`providers/openai_chat.py`): tools are sent
  as `tools` function definitions; the server parses the model's tool-call
  syntax with the model's chat template and returns `tool_calls`; results go
  back as `role: "tool"` messages with the matching `tool_call_id`.

In both cases the conversation is stored as `core.types` messages with
`ToolCall` and `ToolResult` blocks, and `{{TOOLS}}` in the system prompt is
replaced by a short note (`NATIVE_TOOLS_NOTE`).

---

### 4.2 `xml` — Qwen2.5-Instruct, Qwen3

**Trigger:** model name contains `qwen` (case-insensitive).

Qwen instruction-tuned models have been trained to emit tool calls in a
`<tool_call>` XML-style block.  Using any other format produces unreliable
results with these models.

**How the model is asked to call a tool:**

```xml
<tool_call>
{"name": "tool_name", "arguments": {"arg": "value"}}
</tool_call>
```

The JSON body sits between the tags.  `arguments` is the canonical key;
the parser also accepts `args` as an alias for robustness.

**Tool description block** (produced by `_format_tools_xml`): a header
explaining the `<tool_call>` syntax followed by one JSON-schema object per
tool:

```json
{
  "name": "read_file",
  "description": "Gets the full content of a file …",
  "parameters": {
    "filename": {"type": "str"}
  }
}
```

**Parser** (`_parse_xml`): uses a regex to find `<tool_call>…</tool_call>`
blocks (DOTALL), JSON-parses the body, validates `name` and `arguments`.

**Tool result** fed back: same `tool_result({…})` format as ntcode — the
result format does not change between conventions, only the invocation format.

---

### 4.3 `json_block` — Mistral, Mixtral

**Trigger:** model name contains `mistral` or `mixtral` (case-insensitive).

---

### 4.4 `gemma` — Gemma 3/4 instruct models

**Trigger:** model name contains `gemma` (case-insensitive).

Gemma instruct models (e.g. `gemma-4`, `google/gemma-3-27b-it`) emit tool calls
using pipe-angle-bracket delimiter tokens and a `call:tool:` prefix:

```
<|tool_call>call:tool:list_files({"path": "."})<tool_call|>
```

The model sometimes also produces JS-style unquoted keys:

```
<|tool_call>call:tool:list_files({path: "."})<tool_call|>
```

**Tool description block** (produced by `_format_tools_gemma`): a header explaining
the `<|tool_call>...<tool_call|>` syntax with a concrete example, followed by
one JSON-schema object per tool (same schema shape as the xml/json_block formatters).

**Parser** (`_parse_gemma`): uses a regex to find `<|tool_call>…<tool_call|>` blocks,
strips the optional `call:tool:` prefix, splits on the first `(` to extract the
tool name, then attempts strict `json.loads` on the argument body. If that fails,
`_fix_unquoted_keys()` quotes bare identifier keys before retrying. Logs a warning
and skips on any unrecoverable parse error.

**Tool result** fed back: same `tool_result({…})` format as all other conventions.

Smaller Mistral fine-tunes accessed via llama.cpp reliably produce fenced
JSON blocks when prompted with this format.

**How the model is asked to call a tool:**

````
```json
{"tool": "tool_name", "args": {"arg": "value"}}
```
````

Note the top-level keys are `tool` (not `name`) and `args` (not `arguments`).

**Tool description block** (produced by `_format_tools_json_block`): a header
explaining the fenced-block syntax followed by one JSON-schema object per
tool (same schema shape as the xml formatter).

**Parser** (`_parse_json_block`): uses a regex to find ` ```json … ``` ` or
` ``` … ``` ` fences (DOTALL), JSON-parses the body, validates `tool` and
`args` keys.

---

## 5. How the active convention is selected

Native tool calling is used unless `CALLING_CONVENTION` names a text format
(`utils.tool_format.openai_tool_mode()`). For the legacy text path,
`_detect_family(provider, model)` in `utils/tool_format.py` returns the
explicit `CALLING_CONVENTION`; its model-name rules below only matter for
code that calls it without one set:

```python
def _detect_family(provider: str, model: str) -> str:
    m = model.lower()
    if "qwen" in m:
        return "xml"
    if "mistral" in m or "mixtral" in m:
        return "json_block"
    if "gemma" in m:
        return "gemma"
    return "ntcode"   # default
```

The `provider` argument is available for future use (e.g. if the same model
name is served by two providers with different conventions).

The model name comes from:
- `OPENAI_MODEL` env var when `LLM_PROVIDER=openai`
- `NTCODE_MODEL` env var (falling back to `DEFAULT_MODEL`) when
  `LLM_PROVIDER=anthropic`

So running `start_qwen.sh`, which sets `OPENAI_MODEL="Qwen/Qwen3-27B"`,
automatically selects the `xml` formatter and parser for that session.

---

## 6. Adding a new calling convention

Text formats live in `providers/text_tools.py`. Each is a `Dialect` subclass
with four parts:

- `header`: the instructions placed before the tool list in the system prompt;
- `render_call(call)`: a `ToolCall` written the way the model writes it, used
  to replay earlier calls in the conversation;
- `find_calls(text)`: `(start, end, ToolCall)` spans for every call in a
  reply. Read arguments with `_decode_at()` (a `json.JSONDecoder.raw_decode`
  wrapper) rather than a regular expression, so arguments may span lines and
  contain the closing delimiter inside strings. When a call is recognisable
  but its arguments are not a JSON object, still return it, built with
  `_call(name, None, raw_text)`: the agent then tells the model what was wrong;
- optionally `render_results(results)`, if the model expects tool results in a
  particular shape (the default is one `tool_result(...)` per result).

Then:

1. Add an instance to `DIALECTS` at the bottom of the module.
2. Add the name to `_calling_convention_validator` in `utils/config_manager.py`.
3. Add wire-contract fixtures in `tests/fixtures/wire/` with
   `"tool_mode": "text", "dialect": "<name>"`: at least one response (a raw
   reply with a call) and one request (a conversation with a call and its
   result), and cases in `tests/test_text_tools.py` for the dialect's edge
   cases.

Prefer native tool calling where the server supports it: with a server that
parses the model's tool calls (llama.cpp `--jinja`, vLLM with a tool-call
parser, Ollama), no dialect is needed at all.

---

## 7. Customising the prose part of the prompt

Everything outside `{{TOOLS}}` and `{{FILE:…}}` directives is free-form
prose.  You can:

- Change the assistant persona (first paragraph).
- Add or remove `{{FILE:path}}` directives to give the model more or less
  project context.  Common candidates: `outline.md`, `bugs.md`, a
  `CONVENTIONS.md` you write for your project.
- Add static instructions (coding style, language preference, etc.) anywhere
  in the file.
- Create multiple stub files and switch between them with
  `NTCODE_SYSTEM_PROMPT_FILE`.

**What not to put in the stub:**  Large files that change frequently
(e.g. the full source of a module you are editing).  Those will bust the
server-side prompt cache on every change.  Pass them as user messages instead,
or as tool results from `read_file`.

---

## 8. Prompt caching

With Claude, `providers/anthropic.py` sets two cache breakpoints on every
request (prompt caching is generally available; no beta header):

- a `cache_control` marker on the **system block**, which holds the system
  prompt plus any documentation files not already inlined
  (`SessionHeader.system_with_docs()`); the tool definitions come before it
  and are cached with it;
- top-level **automatic caching**, which places a breakpoint at the end of the
  conversation, so each step of a tool loop reuses the previous step's
  prefix.

Check `cache_read` in the `[anthropic]` log lines to confirm cache hits.

**Implications for prompt changes:**
- The cache is per-process.  Restarting ntCode starts a fresh cache.
- Calling `invalidate_cache()` in `utils/prompt.py` clears the *local*
  Python cache (forces re-reading files from disk) but does *not* invalidate
  the Anthropic server-side cache for the current session.
- `{{FILE:…}}` directives are resolved once at startup.  If you edit an
  inlined file mid-session, restart ntCode to pick up the changes.

With native tool calling the `{{TOOLS}}` placeholder becomes a short note
(`NATIVE_TOOLS_NOTE` in `utils/prompt.py`), because the tool definitions are
sent in the request's `tools` field instead.

---

## 9. Debugging the assembled prompt

**In the TUI**, type `/prompt` to print the fully assembled system prompt
(all `{{FILE:…}}` directives inlined, `{{TOOLS}}` replaced) to the terminal.
This is the exact string sent to the LLM.

**In the log**, set `NTCODE_DEBUG=true` in your `.env` file.  Every
`build_system_prompt()` call logs:
```
INFO  prompt: loading stub from /path/to/system_prompt.md
INFO  prompt: built (12345 chars)
INFO  [tool_format] provider=openai model=Qwen/Qwen3-27B -> family=xml formatter=_format_tools_xml
```
If a `{{FILE:…}}` target is missing you will see:
```
WARNING  prompt: {{FILE:missing.md}} not found — skipping
```
If the stub has no `{{TOOLS}}` placeholder:
```
WARNING  prompt: stub contains no {{TOOLS}} placeholder — tool descriptions not injected
```

**To inspect the tool block alone** without starting the full agent:
```python
from tools.registry import TOOL_REGISTRY
from utils.tool_format import format_tools_for_provider
print(format_tools_for_provider("openai", "Qwen/Qwen3-27B", TOOL_REGISTRY))
```

**To verify detection** for a model you are about to try:
```python
from utils.tool_format import _detect_family
print(_detect_family("openai", "your-model-name"))  # ntcode / xml / json_block
```
