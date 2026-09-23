"""Anthropic Messages API adapter with native tool use.

Conversion between :mod:`core.types` and the Messages API:

==================  ==========================================================
core.types          Messages API
==================  ==========================================================
system prompt       ``system`` text block with a ``cache_control`` breakpoint
ToolSpec            ``tools`` entry: ``name``, ``description``, ``input_schema``
TextBlock           ``text`` block (empty text is dropped; the API rejects it)
ToolCall            assistant ``tool_use`` block (``id``, ``name``, ``input``)
ToolResult          user ``tool_result`` block (``tool_use_id``, ``content``,
                    ``is_error`` only when true), placed before any text
OpaqueBlock         any other assistant block (e.g. ``thinking``), re-sent
                    unchanged when it came from this provider
==================  ==========================================================

Prompt caching uses two breakpoints: one on the system block (tools and
system prompt are stable across a session) and top-level automatic caching,
which moves a breakpoint to the end of the conversation on every request so
each step of a tool loop reuses the previous step's prefix.  Caching is
generally available; no beta header is sent.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence

import anthropic

from core.types import (
    AssistantTurn,
    Block,
    Message,
    OpaqueBlock,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)
from providers.base import Provider
from providers.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)
from utils.config import logger

PROVIDER_NAME = "anthropic"
_EPHEMERAL: Dict[str, str] = {"type": "ephemeral"}


class AnthropicProvider(Provider):
    """Claude through the Anthropic Python SDK.

    Args:
        model:        Model id, e.g. ``"claude-sonnet-4-6"``.
        api_key:      API key; ``None`` lets the SDK resolve credentials
                      (``ANTHROPIC_API_KEY``, ``ant auth login`` profile, ...).
        max_tokens:   Output cap per reply.
        timeout:      Request timeout in seconds.
        max_retries:  SDK retries for connection errors, 408/409/429 and 5xx.
        client:       Pre-built ``anthropic.Anthropic`` client (tests).
        rate_limiter: Optional ntCode token rate limiter
                      (``wait_for_capacity`` / ``record_actual``).
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        max_tokens: int = 8192,
        timeout: float = 600.0,
        max_retries: int = 2,
        client: Optional[anthropic.Anthropic] = None,
        rate_limiter: Any = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._rate_limiter = rate_limiter
        self._client = client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------

    def build_request(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> Dict[str, Any]:
        """Return the keyword arguments for ``client.messages.create``."""
        request: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [m for m in (_message_to_wire(msg) for msg in messages) if m],
            # Automatic caching: breakpoint at the end of the conversation.
            "cache_control": dict(_EPHEMERAL),
        }
        if system:
            request["system"] = [
                {"type": "text", "text": system, "cache_control": dict(_EPHEMERAL)}
            ]
        if tools:
            request["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        return request

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AssistantTurn:
        request = self.build_request(system, messages, tools)

        reservation = None
        if self._rate_limiter is not None:
            reservation = self._rate_limiter.wait_for_capacity(
                _estimate_tokens(request) + self.max_tokens
            )

        start = time.time()
        try:
            response = self._client.messages.create(**request)
        except anthropic.APIError as exc:
            logger.error(
                "[anthropic] request failed after %.2fs (model=%s, messages=%d): %s",
                time.time() - start, self.model, len(request["messages"]), exc,
            )
            raise _translate_error(exc) from exc

        turn = _turn_from_response(response)
        if self._rate_limiter is not None:
            self._rate_limiter.record_actual(
                reservation, turn.usage.input_tokens + turn.usage.output_tokens
            )
        logger.info(
            "[anthropic] %s in %.2fs: stop=%s tokens in=%d out=%d cache_read=%d cache_write=%d tool_calls=%d",
            self.model, time.time() - start, turn.stop_reason,
            turn.usage.input_tokens, turn.usage.output_tokens,
            turn.usage.cache_read_tokens, turn.usage.cache_write_tokens,
            len(turn.message.tool_calls),
        )
        return turn

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model!r})"


# ---------------------------------------------------------------------------
# core.types -> wire
# ---------------------------------------------------------------------------

def _message_to_wire(msg: Message) -> Optional[Dict[str, Any]]:
    """Convert one message; ``None`` when nothing in it can be sent."""
    blocks: List[Dict[str, Any]] = []
    if msg.role == "user":
        # tool_result blocks must come first in the user turn.
        blocks.extend(_result_to_wire(b) for b in msg.results)
        blocks.extend(
            {"type": "text", "text": b.text}
            for b in msg.content if isinstance(b, TextBlock) and b.text
        )
    else:
        for b in msg.content:
            if isinstance(b, TextBlock):
                if b.text:
                    blocks.append({"type": "text", "text": b.text})
            elif isinstance(b, ToolCall):
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.args})
            elif isinstance(b, OpaqueBlock) and b.provider == PROVIDER_NAME:
                blocks.append(b.data)
    if not blocks:
        return None
    return {"role": msg.role, "content": blocks}


def _result_to_wire(result: ToolResult) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": "tool_result", "tool_use_id": result.call_id}
    if result.content:
        out["content"] = result.content
    if result.is_error:
        out["is_error"] = True
    return out


def _estimate_tokens(request: Dict[str, Any]) -> int:
    """Rough pre-request estimate for the rate limiter: 1 token ~ 4 chars."""
    size = sum(len(json.dumps(request.get(k, ""), ensure_ascii=False))
               for k in ("system", "tools", "messages"))
    return max(1, size // 4)


# ---------------------------------------------------------------------------
# wire -> core.types
# ---------------------------------------------------------------------------

def _turn_from_response(response: Any) -> AssistantTurn:
    blocks: List[Block] = []
    for block in response.content:
        kind = getattr(block, "type", None)
        if kind == "text":
            blocks.append(TextBlock(block.text))
        elif kind == "tool_use":
            blocks.append(ToolCall(block.id, block.name, dict(block.input or {})))
        else:
            # thinking, redacted_thinking, server-tool blocks, ...: kept so
            # they can be sent back unchanged on the next request.
            blocks.append(OpaqueBlock(PROVIDER_NAME, block.to_dict()))

    usage = response.usage
    return AssistantTurn(
        message=Message("assistant", tuple(blocks)),
        stop_reason=response.stop_reason or "",
        usage=Usage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        ),
    )


def _translate_error(exc: anthropic.APIError) -> ProviderError:
    """Map an SDK exception to a ProviderError, most specific first."""
    kw: Dict[str, Any] = {"provider": PROVIDER_NAME}
    if isinstance(exc, anthropic.APIStatusError):
        kw["status"] = exc.status_code
        retry_after = exc.response.headers.get("retry-after")
        if retry_after:
            try:
                kw["retry_after"] = float(retry_after)
            except ValueError:
                pass

    # APITimeoutError subclasses APIConnectionError, so it is checked first.
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderTimeoutError(str(exc), **kw)
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderConnectionError(str(exc), **kw)
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ProviderAuthError(str(exc), **kw)
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderRateLimitError(str(exc), **kw)
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ProviderServerError(str(exc), **kw)
        return ProviderRequestError(str(exc), **kw)
    return ProviderError(str(exc), **kw)
