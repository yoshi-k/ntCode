"""Backends that the wire-contract tests (tests/test_wire_contract.py) run against.

A backend turns a provider-neutral conversation into an HTTP request, sends it
to a fake server supplied by the test, and turns the response back into text
plus tool calls::

    backend = make_backend(profile, handler)
    result = backend.complete(system, messages, tools)
    # {"text": str, "tool_calls": [{"id": str | None, "name": str, "args": dict}]}

*handler* receives a :class:`CapturedRequest` and returns the JSON body to
reply with.  Backends wrap it with :func:`mock_transport` for whichever HTTP
library they use: current Anthropic and OpenAI SDKs are built on ``httpx2``,
the legacy OpenAILLM on ``httpx``, so the tests must not depend on either.

The conversation format is the one the fixtures use (see
tests/fixtures/wire/README.md): messages hold a list of ``text``,
``tool_call`` and ``tool_result`` blocks, and tools are JSON-schema specs.

The backend is chosen by the fixture's provider and tool mode:

* ``anthropic`` -> :class:`ProviderBackend` around
  :class:`providers.anthropic.AnthropicProvider`.
* ``openai`` with ``tool_mode: native`` -> :class:`ProviderBackend` around
  :class:`providers.openai_chat.OpenAIChatProvider`.
* ``openai`` with ``tool_mode: text`` -> :class:`LegacyBackend`, which
  adapts the old OpenAILLM plus the text parsers in utils.tool_format,
  reproducing what the agent loop does today.  It goes away when the text
  dialects move onto the provider interface, together with the remaining
  ``legacy_xfail`` markers.
"""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List
from unittest.mock import patch

import httpx

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


def sdk_http_module(package: str) -> Any:
    """The HTTP library (``httpx`` or ``httpx2``) the installed SDK is built on."""
    requires = importlib.metadata.requires(package) or []
    if any(r.split()[0].split(";")[0].startswith("httpx2") for r in requires):
        import httpx2
        return httpx2
    return httpx


def anthropic_http_module() -> Any:
    """The HTTP library the installed Anthropic SDK is built on."""
    return sdk_http_module("anthropic")


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
    """The old utils.openai_llm / utils.tool_format stack."""

    def __init__(self, profile: Dict[str, Any], handler: Handler) -> None:
        # Import utils.llm before touching LLM_PROVIDER: it builds a client at
        # import time, and with LLM_PROVIDER=openai that imports
        # utils.openai_llm, which imports utils.llm back (a cycle that only
        # works when utils.llm is imported first).
        import utils.llm  # noqa: F401
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

        with patch("utils.openai_llm._rate_limiter", _NoRateLimit()):
            text = self.llm.call(self._system(system, tools), self._messages(messages))

        calls = get_parser_for_provider(self.provider, self.model)(text)
        return {
            "text": text,
            "tool_calls": [{"id": None, "name": n, "args": a} for n, a in calls],
        }


class ProviderBackend:
    """A new-style providers.base.Provider, fed the fixture conversation."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider

    def complete(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        from core.types import ToolSpec, message_from_dict

        turn = self.provider.complete(
            system,
            [message_from_dict(m) for m in messages],
            [ToolSpec(**t) for t in tools],
        )
        return {
            "text": turn.message.text,
            "tool_calls": [
                {"id": c.id, "name": c.name, "args": c.args}
                for c in turn.message.tool_calls
            ],
        }


def anthropic_backend(profile: Dict[str, Any], handler: Handler) -> ProviderBackend:
    import anthropic
    from providers.anthropic import AnthropicProvider

    http = anthropic_http_module()
    client = anthropic.Anthropic(
        api_key="test-key",
        http_client=http.Client(transport=mock_transport(http, handler)),
        max_retries=0,
    )
    return ProviderBackend(AnthropicProvider(profile["model"], client=client))


def openai_backend(profile: Dict[str, Any], handler: Handler) -> Any:
    if profile["tool_mode"] != "native":
        return LegacyBackend(profile, handler)

    import openai
    from providers.openai_chat import OpenAIChatProvider

    http = sdk_http_module("openai")
    client = openai.OpenAI(
        api_key="test-key",
        base_url="http://wire.test/v1",
        http_client=http.Client(transport=mock_transport(http, handler)),
        max_retries=0,
    )
    return ProviderBackend(OpenAIChatProvider(profile["model"], client=client))


_BACKENDS = {"anthropic": anthropic_backend, "openai": openai_backend}


def make_backend(profile: Dict[str, Any], handler: Handler):
    """Build the backend for *profile*'s provider and tool mode."""
    return _BACKENDS[profile["provider"]](profile, handler)
