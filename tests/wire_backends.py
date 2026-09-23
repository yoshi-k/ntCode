"""Backends that the wire-contract tests (tests/test_wire_contract.py) run against.

A backend turns a provider-neutral conversation into an HTTP request, sends it
to a fake server supplied by the test, and turns the response back into text
plus tool calls::

    backend = make_backend(profile, handler)
    result = backend.complete(system, messages, tools)
    # {"text": str, "tool_calls": [{"id": str | None, "name": str, "args": dict}]}

*handler* receives a :class:`CapturedRequest` and returns the JSON body to
reply with.  Backends wrap it with :func:`mock_transport` for whichever HTTP
library their SDK uses (``httpx`` in older releases, ``httpx2`` in current
ones), so the tests depend on neither.

The conversation format is the one the fixtures use (see
tests/fixtures/wire/README.md): messages hold a list of ``text``,
``tool_call`` and ``tool_result`` blocks, and tools are JSON-schema specs.

The backend is chosen by the fixture's provider and tool mode:

* ``anthropic`` -> :class:`providers.anthropic.AnthropicProvider`.
* ``openai``, ``tool_mode: native`` -> :class:`providers.openai_chat.OpenAIChatProvider`.
* ``openai``, ``tool_mode: text`` -> that provider wrapped in
  :class:`providers.text_tools.TextToolsProvider` with the fixture's dialect.
"""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

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


def openai_backend(profile: Dict[str, Any], handler: Handler) -> ProviderBackend:
    import openai
    from providers.openai_chat import OpenAIChatProvider
    from providers.text_tools import TextToolsProvider, get_dialect

    http = sdk_http_module("openai")
    client = openai.OpenAI(
        api_key="test-key",
        base_url="http://wire.test/v1",
        http_client=http.Client(transport=mock_transport(http, handler)),
        max_retries=0,
    )
    provider = OpenAIChatProvider(profile["model"], client=client)
    if profile["tool_mode"] == "text":
        provider = TextToolsProvider(provider, get_dialect(profile["dialect"]))
    return ProviderBackend(provider)


_BACKENDS = {"anthropic": anthropic_backend, "openai": openai_backend}


def make_backend(profile: Dict[str, Any], handler: Handler):
    """Build the backend for *profile*'s provider and tool mode."""
    return _BACKENDS[profile["provider"]](profile, handler)
