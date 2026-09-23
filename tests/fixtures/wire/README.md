# Wire-contract fixtures

Each `*.json` file here is one test case for `tests/test_wire_contract.py`.
Together they specify what ntCode must put on the wire for each provider and
tool-calling mode, and what it must get back out of each kind of response.
They are the spec for the backend rewrite: the new code is done when every
fixture passes without a `legacy_xfail` marker.

The hand-written responses follow the documented Anthropic Messages and OpenAI
Chat Completions formats. Responses captured from real servers are better;
see [Capturing real responses](#capturing-real-responses).

## Common fields

| Field | Meaning |
|---|---|
| `kind` | `"response"` or `"request"` |
| `description` | What the case checks, in one sentence |
| `profile` | `provider` (`anthropic` / `openai`), `model`, `tool_mode` (`native` / `text`), and `dialect` (`ntcode` / `xml` / `json_block` / `gemma`) when `tool_mode` is `text` |
| `tools` | Tool specs: `name`, `description`, `parameters` (a JSON Schema object) |
| `messages` | Conversation sent to the backend (see below). Optional for responses |
| `system` | System prompt. Defaults to `"You are ntCode."` |
| `legacy_xfail` | Present when the current code gets the case wrong: the reason. The test then runs as a strict xfail, so fixing the bug makes it fail until the marker is removed |

### Conversation format

Provider-neutral. Every message has `role` (`user` / `assistant`) and a list
of content blocks:

```json
{"type": "text", "text": "..."}
{"type": "tool_call", "id": "toolu_01A", "name": "read_file", "args": {"filename": "README.md"}}
{"type": "tool_result", "call_id": "toolu_01A", "content": "...", "is_error": false}
```

Tool calls live in assistant messages; their results live in the next user
message, in call order. `is_error` is optional and defaults to `false`.

## `kind: "response"`

`raw_response` is served as the HTTP reply. The backend's result must match
`expect_result`:

- `tool_calls`: compared in order by `name` and `args`. An `id` of `null`
  means "not compared" (text-mode calls have no ids); any other `id` must be
  passed through unchanged, since the tool result has to reference it.
- `text` (optional): the reply text with any tool-call markup removed.

## `kind: "request"`

The captured HTTP request must match `expect_request`:

- `path`: URL path, e.g. `/v1/messages`.
- `body_includes`: top-level body keys whose values must match exactly.
  OpenAI `arguments` strings are compared as parsed JSON.
- `body_excludes`: top-level keys that must be absent.
- `headers_absent`: header names that must not be sent.
- `properties`: checks for text mode, where the exact wording is ours to
  choose:
  - `roles_alternate`: no two consecutive non-system messages share a role.
  - `system_contains`: substrings the system prompt must contain.
  - `message_contains`: `{index, role, substring}` checks against the
    non-system messages.

## Capturing real responses

`scripts/capture_wire_fixture.py` sends one native tool-calling request to a
real server and writes the raw response as a fixture in `captured/`, which
the tests do not load. Review `expect_result`, then move the file up into
this directory. For example, to check whether llama.cpp returns structured
`tool_calls` for Gemma 4:

```sh
python scripts/capture_wire_fixture.py --provider openai \
    --base-url http://192.168.2.126:8080/v1 \
    --model gemma-4-26B-A4B-it-UD-Q8_K_XL.gguf --name llamacpp_gemma4
```
