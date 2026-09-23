"""OpenAI Chat Completions adapter with native tool calling.

Works with any server that implements ``/v1/chat/completions`` with
``tools``: OpenAI, llama.cpp (``llama-server --jinja``), vLLM
(``--enable-auto-tool-choice --tool-call-parser ...``), Ollama, LM Studio,
Groq and others.  The server parses the model's tool-call syntax with the
model's own chat template and returns structured ``tool_calls``, so no
model-specific parsing happens here.

Conversion between :mod:`core.types` and the wire format:

==================  ==========================================================
core.types          Chat Completions
==================  ==========================================================
system prompt       first message, ``role: "system"``
ToolSpec            ``tools`` entry ``{"type": "function", "function": {...}}``
TextBlock           ``content`` string (text blocks joined with newlines)
ToolCall            assistant ``tool_calls`` entry; ``arguments`` is a JSON
                    string.  ``content`` is null when there is no text.
ToolResult          one ``role: "tool"`` message per result, with
                    ``tool_call_id``, in call order.  The format has no
                    error flag; error results carry their error in the
                    content.
OpaqueBlock         not sent (it belongs to another provider)
==================  ==========================================================

``finish_reason`` is mapped to the shared stop-reason vocabulary
(``tool_calls`` -> ``tool_use``, ``length`` -> ``max_tokens``, ``stop`` ->
``end_turn``, ``content_filter`` -> ``refusal``).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence

import openai

from core.types import (
    AssistantTurn,
    Block,
    Message,
    TextBlock,
    ToolCall,
    ToolSpec,
    Usage,
    new_call_id,
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

PROVIDER_NAME = "openai"

_STOP_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


class OpenAIChatProvider(Provider):
    """An OpenAI-compatible Chat Completions endpoint, via the openai SDK.

    Args:
        model:        Model name the server knows.
        base_url:     API root including ``/v1``, e.g. ``http://localhost:8080/v1``.
        api_key:      Bearer token; local servers accept any non-empty string.
        max_tokens:   Output cap; 0 leaves it to the server.
        temperature:  Sampling temperature; ``None`` leaves it to the server.
        timeout:      Request timeout in seconds.
        max_retries:  SDK retries for connection errors, 408/409/429 and 5xx.
        client:       Pre-built ``openai.OpenAI`` client (tests).
        rate_limiter: Optional ntCode token rate limiter.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "",
        api_key: str = "",
        max_tokens: int = 0,
        temperature: Optional[float] = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        client: Optional[openai.OpenAI] = None,
        rate_limiter: Any = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._rate_limiter = rate_limiter
        self._client = client or openai.OpenAI(
            base_url=base_url or None,
            # The SDK refuses to start without a key; local servers ignore it.
            api_key=api_key or "none",
            timeout=timeout,
            max_retries=max_retries,
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
        """Return the keyword arguments for ``client.chat.completions.create``."""
        wire: List[Dict[str, Any]] = []
        if system:
            wire.append({"role": "system", "content": system})
        for msg in messages:
            wire.extend(_message_to_wire(msg))

        request: Dict[str, Any] = {"model": self.model, "messages": wire}
        if tools:
            request["tools"] = [
                {"type": "function", "function": {
                    "name": t.name, "description": t.description, "parameters": t.parameters,
                }}
                for t in tools
            ]
        if self.max_tokens:
            request["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            request["temperature"] = self.temperature
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
            size = len(json.dumps(request, ensure_ascii=False)) // 4
            reservation = self._rate_limiter.wait_for_capacity(max(1, size) + self.max_tokens)

        start = time.time()
        try:
            response = self._client.chat.completions.create(**request)
        except openai.APIError as exc:
            logger.error(
                "[openai] request failed after %.2fs (model=%s, messages=%d): %s",
                time.time() - start, self.model, len(request["messages"]), exc,
            )
            raise _translate_error(exc) from exc

        turn = _turn_from_response(response)
        if self._rate_limiter is not None:
            self._rate_limiter.record_actual(
                reservation, turn.usage.input_tokens + turn.usage.output_tokens
            )
        logger.info(
            "[openai] %s in %.2fs: stop=%s tokens in=%d out=%d cached=%d tool_calls=%d",
            self.model, time.time() - start, turn.stop_reason,
            turn.usage.input_tokens, turn.usage.output_tokens,
            turn.usage.cache_read_tokens, len(turn.message.tool_calls),
        )
        return turn

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:
        return f"OpenAIChatProvider(model={self.model!r}, base_url={self.base_url!r})"


# ---------------------------------------------------------------------------
# core.types -> wire
# ---------------------------------------------------------------------------

def _message_to_wire(msg: Message) -> List[Dict[str, Any]]:
    """Convert one message; tool results become separate ``tool`` messages."""
    text = "\n".join(b.text for b in msg.content if isinstance(b, TextBlock) and b.text)

    if msg.role == "user":
        out = [
            {"role": "tool", "tool_call_id": r.call_id, "content": r.content}
            for r in msg.results
        ]
        if text:
            out.append({"role": "user", "content": text})
        return out

    calls = msg.tool_calls
    if not calls and not text:
        return []
    wire: Dict[str, Any] = {"role": "assistant", "content": text or None}
    if calls:
        wire["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {
                "name": c.name,
                "arguments": c.raw_arguments if c.raw_arguments is not None
                else json.dumps(c.args, ensure_ascii=False),
            }}
            for c in calls
        ]
    return [wire]


# ---------------------------------------------------------------------------
# wire -> core.types
# ---------------------------------------------------------------------------

def _parse_arguments(raw: Optional[str]) -> tuple[Dict[str, Any], Optional[str]]:
    """Return ``(args, raw_arguments)``; raw_arguments is set only on failure."""
    if raw is None or not raw.strip():
        return {}, None
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        return {}, raw
    if not isinstance(args, dict):
        return {}, raw
    return args, None


def _turn_from_response(response: Any) -> AssistantTurn:
    if not response.choices:
        raise ProviderError("response has no choices", provider=PROVIDER_NAME)
    choice = response.choices[0]
    message = choice.message

    blocks: List[Block] = []
    if message.content:
        blocks.append(TextBlock(message.content))
    for tc in message.tool_calls or []:
        fn = getattr(tc, "function", None)
        if fn is None:
            logger.warning("[openai] ignoring non-function tool call: %r", tc)
            continue
        args, raw = _parse_arguments(fn.arguments)
        if raw is not None:
            logger.warning("[openai] tool call %s has invalid arguments: %r", fn.name, raw)
        blocks.append(ToolCall(tc.id or new_call_id(), fn.name, args, raw))

    finish = choice.finish_reason or ""
    usage = response.usage
    cached = 0
    if usage is not None and getattr(usage, "prompt_tokens_details", None) is not None:
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
    return AssistantTurn(
        message=Message("assistant", tuple(blocks)),
        stop_reason=_STOP_REASONS.get(finish, finish),
        usage=Usage(
            input_tokens=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
            output_tokens=(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
            cache_read_tokens=cached,
        ),
    )


def _translate_error(exc: openai.APIError) -> ProviderError:
    """Map an SDK exception to a ProviderError, most specific first."""
    kw: Dict[str, Any] = {"provider": PROVIDER_NAME}
    if isinstance(exc, openai.APIStatusError):
        kw["status"] = exc.status_code
        retry_after = exc.response.headers.get("retry-after")
        if retry_after:
            try:
                kw["retry_after"] = float(retry_after)
            except ValueError:
                pass

    # APITimeoutError subclasses APIConnectionError, so it is checked first.
    if isinstance(exc, openai.APITimeoutError):
        return ProviderTimeoutError(str(exc), **kw)
    if isinstance(exc, openai.APIConnectionError):
        return ProviderConnectionError(str(exc), **kw)
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderAuthError(str(exc), **kw)
    if isinstance(exc, openai.RateLimitError):
        return ProviderRateLimitError(str(exc), **kw)
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return ProviderServerError(str(exc), **kw)
        return ProviderRequestError(str(exc), **kw)
    return ProviderError(str(exc), **kw)
