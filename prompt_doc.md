# ntCode — Prompt Architecture & Tool Calling

This document explains how the system prompt is assembled, how tools reach
the model (natively or through a text dialect), and how to add a new text
dialect.

---

## Table of contents

1. [The system prompt stub](#1-the-system-prompt-stub)
2. [How the prompt is built and sent](#2-how-the-prompt-is-built-and-sent)
3. [How tools reach the model](#3-how-tools-reach-the-model)
4. [Choosing native tools or a text dialect](#4-choosing-native-tools-or-a-text-dialect)
5. [Adding a new text dialect](#5-adding-a-new-text-dialect)
6. [Customising the prose part of the prompt](#6-customising-the-prose-part-of-the-prompt)
7. [Prompt caching](#7-prompt-caching)
8. [Debugging the assembled prompt](#8-debugging-the-assembled-prompt)

---

## 1. The system prompt stub

The source of the system prompt is **`system_prompt.md`** at the repo root
(or the file named by `NTCODE_SYSTEM_PROMPT_FILE`, or a role's
`system_prompt_file`). It is plain Markdown with two directives:

```
{{FILE:relative/path.md}}
```
Replaced with the full text of the named file, relative to the repo root.
A missing file leaves a `<!-- FILE NOT FOUND: ... -->` comment and a warning
in the log.

```
{{TOOLS}}
```
Replaced with a short note that the tools are defined separately
(`TOOLS_NOTE` in `utils/prompt.py`). The tool definitions themselves are
never written into the stub; see §3. Only the first `{{TOOLS}}` in the stub
is replaced; a literal `{{TOOLS}}` inside an inlined file is left alone.

---

## 2. How the prompt is built and sent

```
system_prompt.md
      │  utils/prompt.py: build_system_prompt()
      │    - inline every {{FILE:path}}
      │    - {{TOOLS}} -> TOOLS_NOTE
      ▼
SessionHeader.system_with_docs()        (utils/llm.py)
      │    - append agent.md, outline.md, file_organization.md,
      │      skipping any the stub already inlines
      ▼
provider.complete(system, messages, tools)
```

The agent (`utils/agent.py`, `_native_step`) rebuilds this before every model
call, so edits to the stub, inlined files, `/config` or `/role` changes apply
on the next step. `tools` is the active role's allowed tools as JSON-Schema
specs from `core/tool_schema.py`.

---

## 3. How tools reach the model

There is one conversation format for all providers: `core.types` messages
whose assistant turns may hold `ToolCall` blocks and whose user turns may hold
`ToolResult` blocks. Each provider converts that to its wire format.

**Native tool calling** (the default):

- **Claude** (`providers/anthropic.py`): tools as `tools` entries with
  `input_schema`; calls come back as `tool_use` blocks and results go back as
  `tool_result` blocks with the matching id.
- **OpenAI-compatible endpoints** (`providers/openai_chat.py`): tools as
  `tools` function definitions; the server parses the model's own tool-call
  syntax with the model's chat template and returns `tool_calls`; results go
  back as `role: "tool"` messages with the matching `tool_call_id`. This
  covers llama.cpp (`--jinja`), vLLM (`--enable-auto-tool-choice
  --tool-call-parser <name>`), Ollama, LM Studio, Groq and OpenAI.

**Text dialects** (`providers/text_tools.py`), for servers or models without
tool support. `TextToolsProvider` wraps the OpenAI-compatible provider and
uses it for plain text: the tool definitions are appended to the system
prompt in the dialect's syntax, earlier calls are replayed as the model would
have written them, all results of one step go back as a single
`tool_result(...)` user message (so turns strictly alternate), and replies are
parsed back into prose and `ToolCall`s.

| Dialect | Call syntax | Typical models |
|---|---|---|
| `ntcode` | `tool: NAME({...})` at the start of a line | any instruction-following model |
| `xml` | `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` | Qwen2.5-Instruct, Qwen3 (Hermes style) |
| `json_block` | fenced ```` ```json {"tool": ..., "args": {...}} ``` ```` | Mistral, Mixtral |
| `gemma` | `<\|tool_call>call:tool:NAME({...})<tool_call\|>` | Gemma 3/4 instruct |

The parsers read arguments with a JSON decoder, so arguments may span lines
and contain the closing delimiter inside strings; `gemma` also accepts
JS-style unquoted keys. A call whose arguments are not a JSON object still
comes back (with `ToolCall.raw_arguments` set) and the agent answers it with
an error, so the model can correct itself.

---

## 4. Choosing native tools or a text dialect

- `LLM_PROVIDER=anthropic`: always native.
- `LLM_PROVIDER=openai`: native unless `CALLING_CONVENTION` (or
  `NTCODE_CALLING_CONVENTION`) names a dialect: `ntcode`, `xml`, `json_block`
  or `gemma`. Unset, `auto` and `native` all mean native.

Nothing is inferred from the model name. To check whether a server returns
structured tool calls for a model, run `scripts/capture_wire_fixture.py`
against it; if it reports none, use a text dialect (or, for llama.cpp, start
`llama-server` with `--jinja`).

The provider is always built from the configuration (`utils/llm.py`,
`_build_llm`). `/provider`, `/config set` and roles change the configuration
and call `rebuild_provider()`, so the client, model and tool mode never drift
apart.

---

## 5. Adding a new text dialect

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

## 6. Customising the prose part of the prompt

Everything outside `{{TOOLS}}` and `{{FILE:…}}` directives is free-form
prose. You can:

- Change the assistant persona (first paragraph).
- Add or remove `{{FILE:path}}` directives to give the model more or less
  project context. Common candidates: `outline.md`, `bugs.md`, a
  `CONVENTIONS.md` you write for your project.
- Add static instructions (coding style, language preference, etc.) anywhere
  in the file.
- Create multiple stub files and switch between them with
  `NTCODE_SYSTEM_PROMPT_FILE`, or per role with `system_prompt_file`.

Do not describe a tool-call syntax in the prose: the provider supplies the
tool definitions and, for text dialects, the syntax instructions.

**What not to put in the stub:** large files that change frequently (e.g.
the full source of a module you are editing). Every change invalidates the
server-side prompt cache from that point on. Let the model read them with
`read_file` instead.

---

## 7. Prompt caching

With Claude, `providers/anthropic.py` sets two cache breakpoints on every
request (prompt caching is generally available; no beta header):

- a `cache_control` marker on the **system block**, which holds the system
  prompt plus the documentation files (`SessionHeader.system_with_docs()`);
  the tool definitions come before it and are cached with it;
- top-level **automatic caching**, which places a breakpoint at the end of
  the conversation, so each step of a tool loop reuses the previous step's
  prefix.

Check `cache_read` in the `[anthropic]` log lines to confirm cache hits; the
`[openai]` lines show `cached` for servers that report it.

Caching is a prefix match: the prompt must be byte-identical between
requests. Editing the stub, an inlined file or one of the documentation files
mid-session (including through the agent's own `edit_file`) changes the prefix
and costs one uncached request.

---

## 8. Debugging the assembled prompt

**In the TUI**, `/prompt` prints the system prompt exactly as the active
provider sends it (`utils.llm.system_prompt_for_display()`): the stub with
files inlined, the documentation files, and for a text dialect the tool
descriptions it appends. Native providers send the tool definitions in the
request instead, so they do not appear there.

**In the log** (`ntcode.log`; set `NTCODE_DEBUG=true` to also print to the
console):
```
INFO  prompt: loading stub from /path/to/system_prompt.md
INFO  prompt: built (12345 chars)
INFO  [LLM] Provider: openai-compatible (native tools)  url=...  model=...
INFO  [openai] gemma-4 in 1.23s: stop=tool_use tokens in=... out=... cached=... tool_calls=1
INFO  [text/gemma] parsed 1 tool call(s): read_file
```
A missing `{{FILE:…}}` target logs
`WARNING prompt: {{FILE:missing.md}} not found — skipping`.

**To see what goes over the wire**, run the wire-contract tests
(`pytest tests/test_wire_contract.py`) or capture a real exchange with
`scripts/capture_wire_fixture.py`.
