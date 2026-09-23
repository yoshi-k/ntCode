"""Wire-contract tests: what goes over HTTP to each provider, and what comes back.

Each JSON file in tests/fixtures/wire/ is one case (format described in
tests/fixtures/wire/README.md):

* ``kind: "response"`` — a raw provider response is served to the backend;
  the text and tool calls it extracts must match ``expect_result``.
* ``kind: "request"`` — a conversation is sent; the captured HTTP request must
  match ``expect_request``.

Requests are intercepted with a mock HTTP transport (see
tests/wire_backends.py), so these tests check the exact payload the code puts
on the wire, not an intermediate structure.

Cases the code currently handling a profile gets wrong carry
``legacy_xfail`` and are run as strict xfails: they must fail today, and a
fix that makes one pass turns it into a failure until the marker is removed.
They must fail with an AssertionError, or with the builtin exception named
in ``legacy_xfail_raises``, so an unrelated crash is not mistaken for the
expected failure.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.wire_backends import CapturedRequest, make_backend

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "wire"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))

_DEFAULT_MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]

# Minimal valid replies served for "request" cases.
_CANNED = {
    "anthropic": {
        "id": "msg_canned", "type": "message", "role": "assistant",
        "model": "claude", "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    },
    "openai": {
        "id": "chatcmpl-canned", "object": "chat.completion", "created": 0,
        "model": "m", "choices": [{"index": 0, "finish_reason": "stop",
                                   "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    },
}


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalise(value: Any) -> Any:
    """Make payloads comparable: OpenAI ``arguments`` strings are compared as
    parsed JSON, since whitespace in the serialisation is not part of the
    contract."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "arguments" and isinstance(v, str):
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    pass
            out[k] = _normalise(v)
        return out
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    return value


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return "" if content is None else str(content)


def _run(fixture: Dict[str, Any], reply: Dict[str, Any]):
    captured: List[CapturedRequest] = []

    def handler(request: CapturedRequest) -> Dict[str, Any]:
        captured.append(request)
        return reply

    backend = make_backend(fixture["profile"], handler)
    result = backend.complete(
        fixture.get("system", "You are ntCode."),
        fixture.get("messages", _DEFAULT_MESSAGES),
        fixture.get("tools", []),
    )
    assert len(captured) == 1, f"expected exactly one HTTP request, got {len(captured)}"
    return captured[0], result


def _check_response(fixture: Dict[str, Any]) -> None:
    _, result = _run(fixture, fixture["raw_response"])
    expect = fixture["expect_result"]

    if "text" in expect:
        assert result["text"] == expect["text"]

    got = [(c["name"], c["args"]) for c in result["tool_calls"]]
    want = [(c["name"], c["args"]) for c in expect["tool_calls"]]
    assert got == want

    for got_call, want_call in zip(result["tool_calls"], expect["tool_calls"]):
        if want_call["id"] is not None:
            assert got_call["id"] == want_call["id"], "tool-call id must be preserved"


def _check_request(fixture: Dict[str, Any]) -> None:
    provider = fixture["profile"]["provider"]
    request, _ = _run(fixture, _CANNED[provider])
    expect = fixture["expect_request"]
    body = request.body

    assert request.method == "POST"
    assert request.path == expect["path"]

    for key, want in expect.get("body_includes", {}).items():
        assert key in body, f"request body is missing {key!r}"
        assert _normalise(body[key]) == _normalise(want), f"request body[{key!r}] differs"

    for key in expect.get("body_excludes", []):
        assert key not in body, f"request body must not contain {key!r}"

    for header in expect.get("headers_absent", []):
        assert header not in request.headers, f"request must not send header {header!r}"

    props = expect.get("properties", {})
    messages = body.get("messages", [])
    non_system = [m for m in messages if m.get("role") != "system"]

    if props.get("roles_alternate"):
        roles = [m["role"] for m in non_system]
        repeats = [i for i in range(1, len(roles)) if roles[i] == roles[i - 1]]
        assert not repeats, f"roles do not alternate: {roles}"

    if "system_contains" in props:
        if "system" in body:
            system_text = _text_of(body["system"])
        else:
            system_text = _text_of(messages[0]["content"]) if messages and messages[0]["role"] == "system" else ""
        for needle in props["system_contains"]:
            assert needle in system_text, f"system prompt does not contain {needle!r}"

    for check in props.get("message_contains", []):
        i = check["index"]
        assert i < len(non_system), f"no message at index {i}: {[m['role'] for m in non_system]}"
        msg = non_system[i]
        assert msg["role"] == check["role"], f"message {i} has role {msg['role']!r}"
        assert check["substring"] in _text_of(msg.get("content")), (
            f"message {i} does not contain {check['substring']!r}"
        )


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_wire_contract(path: Path, request: pytest.FixtureRequest) -> None:
    fixture = _load(path)
    if "legacy_xfail" in fixture:
        # Only the expected kind of failure counts; anything else (an import
        # error, a bug in the harness) is reported as a real failure.
        raises = getattr(builtins, fixture.get("legacy_xfail_raises", "AssertionError"))
        request.applymarker(pytest.mark.xfail(
            reason=fixture["legacy_xfail"], strict=True, raises=raises,
        ))

    if fixture["kind"] == "response":
        _check_response(fixture)
    else:
        _check_request(fixture)


_PROFILE_KEYS = {"provider", "model", "tool_mode"}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_is_well_formed(path: Path) -> None:
    fixture = _load(path)
    assert fixture["kind"] in {"response", "request"}
    assert fixture.get("description"), "every fixture needs a description"

    profile = fixture["profile"]
    assert _PROFILE_KEYS <= set(profile)
    assert profile["provider"] in {"anthropic", "openai"}
    assert profile["tool_mode"] in {"native", "text"}
    if profile["tool_mode"] == "text":
        assert profile.get("dialect") in {"ntcode", "xml", "json_block", "gemma"}

    for tool in fixture.get("tools", []):
        assert {"name", "description", "parameters"} <= set(tool)
        assert tool["parameters"].get("type") == "object"

    if fixture["kind"] == "response":
        assert "raw_response" in fixture
        for call in fixture["expect_result"]["tool_calls"]:
            assert {"id", "name", "args"} <= set(call)
    else:
        assert fixture.get("messages")
        assert fixture["expect_request"]["path"].startswith("/v1/")


def test_fixtures_exist() -> None:
    assert FIXTURES, f"no fixtures found in {FIXTURE_DIR}"
