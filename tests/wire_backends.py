"""Backends that the wire-contract tests (tests/test_wire_contract.py) run against.

A backend turns a provider-neutral conversation into an HTTP request, sends it
to a fake server supplied by the test, and turns the response back into text
plus tool calls::

    backend = make_backend(profile, handler)
    result = backend.complete(system, messages, tools)
    # {"text": str, "tool_calls": [{"id": str | None, "name": str, "args": dict}]}

*handler* receives a :class:`CapturedRequest` and returns the JSON body to
reply with.  Backends wrap it with :func:`mock_transport` for whichever HTTP
library they use: the Anthropic SDK moved from ``httpx`` to ``httpx2`` in
1.x, and requirements.txt does not pin it, so the tests must not depend on
either.

The conversation format is the one the fixtures use (see
tests/fixtures/wire/README.md): messages hold a list of ``text``,
``tool_call`` and ``tool_result`` blocks, and tools are JSON-schema specs.

``LegacyBackend`` adapts the current code (AnthropicLLM / OpenAILLM plus the
text parsers in utils.tool_format) to that interface, reproducing what the
agent loop does today.  The rewrite adds a new backend here, and the legacy
one and every ``legacy_xfail`` marker go away with the old code.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List
from unittest.mock import patch

import httpx

BACKEND_NAME = os.environ.get("NTCODE_WIRE_BACKEND", "legacy")


@dataclass
class CapturedRequest:
    """An HTTP request as seen by the fake server, independent of HTTP library."""

    method: str
    path: str
    headers: Dict[str, str]   # lower-cased names
    body: Any                 # parsed JSON


Handler = Callable[[CapturedRequest], Any]


def mock_transport(http_module: Any, handler: Handler) -> Any:
    """Return ``http_module.MockTransport`` answering every request via *handler*.

    *http_module* is ``httpx`` or ``httpx2``; both expose the same API.
    """
    def respond(request: Any) -> Any:
        captured = CapturedRequest(
            method=request.method,
            path=request.url.path,
            headers={k.lower(): v for k, v in request.headers.items()},
            body=json.loads(request.content) if request.content else None,
        )
        return http_module.Response(200, json=handler(captured))

    return http_module.MockTransport(respond)


def anthropic_http_module() -> Any:
    """The HTTP library the installed Anthropic SDK is built on."""
    requires = importlib.metadata.requires("anthropic") or []
    if any(r.split()[0].split(";")[0].startswith("httpx2") for r in requires):
        import httpx2
        return httpx2
    return httpx


class _NoRateLimit:
    """Stand-in for utils.rate_limiter._rate_limiter so tests never sleep."""

    def wait_for_capacity(self, _estimated: int) -> int:
        return 0

    def record_actual(self, _reservation: int, _tokens: int) -> None:
        pass

    def status(self) -> str:
        return "rate limiting disabled in tests"


def _render_legacy_call(family: str, name: str, args: Dict[str, Any]) -> str:
    """Render a tool call the way the model would have written it in *family*."""
    if family == "xml":
        return "<tool_call>\n" + json.dumps({"name": name, "arguments": args}) + "\n</tool_call>"
    if family == "json_block":
        return "```json\n" + json.dumps({"tool": name, "args": args}) + "\n```"
    if family == "gemma":
        return f"<|tool_call>call:tool:{name}({json.dumps(args)})<tool_call|>"
    return f"tool: {name}({json.dumps(args)})"


class LegacyBackend:
    """The current utils.llm / utils.openai_llm / utils.tool_format stack."""

    def __init__(self, profile: Dict[str, Any], handler: Handler) -> None:
        from utils import config as cfg
        from utils.tool_format import _detect_family

        self.provider = profile["provider"]
        self.model = profile["model"]

        # The legacy code reads provider and calling convention from module
        # globals; tests/conftest.py restores them after each test.
        cfg.LLM_PROVIDER = self.provider
        cfg.CALLING_CONVENTION = (
            profile.get("dialect", "") if profile["tool_mode"] == "text" else ""
        )
        self.family = _detect_family(self.provider, self.model)

        if self.provider == "anthropic":
            import anthropic
            from utils.llm import AnthropicLLM

            http = anthropic_http_module()
            self.llm = AnthropicLLM(api_key="test-key", model=self.model)
            self.llm.client = anthropic.Anthropic(
                api_key="test-key",
                http_client=http.Client(transport=mock_transport(http, handler)),
                max_retries=0,
            )
        else:
            from utils.openai_llm import OpenAILLM

            self.llm = OpenAILLM(
                base_url="http://wire.test/v1", api_key="test-key",
                model=self.model, max_retries=1,
            )
            self.llm._http = httpx.Client(
                transport=mock_transport(httpx, handler),
                headers=self.llm._http.headers,
            )

    def _system(self, system: str, tools: List[Dict[str, Any]]) -> Any:
        # Legacy injects the text-protocol tool block into the system prompt
        # (utils/prompt.py) for every provider.
        if tools:
            from tools.registry import TOOL_REGISTRY
            from utils.tool_format import format_tools_for_provider

            names = {t["name"] for t in tools}
            registry = {n: fn for n, fn in TOOL_REGISTRY.items() if n in names}
            system = system + "\n\n" + format_tools_for_provider(
                self.provider, self.model, registry
            )
        if self.provider == "anthropic":
            # What SessionHeader.system_block() sends.
            from utils.llm import apply_cache_control

            return [apply_cache_control({"type": "text", "text": system})]
        return system

    def _messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Mirrors ConversationManager.add_user / add_assistant and the way
        # utils/agent.py stores tool results.
        out: List[Dict[str, Any]] = []
        for msg in messages:
            texts: List[str] = []
            for block in msg["content"]:
                if block["type"] == "text":
                    texts.append(block["text"])
                elif block["type"] == "tool_call":
                    texts.append(_render_legacy_call(self.family, block["name"], block["args"]))
                elif block["type"] == "tool_result":
                    out.append({"role": "user", "content": [
                        {"type": "text", "text": f"tool_result({json.dumps(block['content'])})"}
                    ]})
            if texts:
                out.append({"role": msg["role"], "content": [
                    {"type": "text", "text": "\n".join(texts)}
                ]})
        return out

    def complete(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        from utils.tool_format import get_parser_for_provider

        with patch("utils.llm._rate_limiter", _NoRateLimit()), \
                patch("utils.openai_llm._rate_limiter", _NoRateLimit()):
            text = self.llm.call(self._system(system, tools), self._messages(messages))

        calls = get_parser_for_provider(self.provider, self.model)(text)
        return {
            "text": text,
            "tool_calls": [{"id": None, "name": n, "args": a} for n, a in calls],
        }


_BACKENDS = {"legacy": LegacyBackend}


def make_backend(profile: Dict[str, Any], handler: Handler):
    """Build the backend selected by NTCODE_WIRE_BACKEND for *profile*."""
    try:
        cls = _BACKENDS[BACKEND_NAME]
    except KeyError:
        raise ValueError(
            f"Unknown NTCODE_WIRE_BACKEND={BACKEND_NAME!r}; known: {sorted(_BACKENDS)}"
        ) from None
    return cls(profile, handler)
