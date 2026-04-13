"""
utils/openai_llm.py
-------------------
OpenAI-compatible LLM provider for ntCode.

Drop-in replacement for AnthropicLLM that speaks the OpenAI Chat Completions
wire protocol, supported by:

  Provider          Base URL
  ----------------  -----------------------------------------
  Ollama            http://localhost:11434/v1
  LM Studio         http://localhost:1234/v1
  vLLM              http://localhost:8000/v1
  LocalAI           http://localhost:8080/v1
  OpenAI            https://api.openai.com/v1
  Groq              https://api.groq.com/openai/v1
  Together AI       https://api.together.xyz/v1

Activate by adding to .env:

    LLM_PROVIDER=openai
    OPENAI_BASE_URL=http://localhost:11434/v1
    OPENAI_API_KEY=ollama          # any string works for local servers
    OPENAI_MODEL=llama3

No extra packages required — httpx is already in requirements.txt.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import httpx

from utils.llm import LLM
from utils.rate_limiter import _rate_limiter
from utils.config import (
    LOG_CONVERSATIONS,
    DEBUG_MODE,
    logger,
)


class OpenAILLM(LLM):
    """
    LLM implementation that connects to any OpenAI-compatible Chat Completions
    endpoint using plain HTTP (via httpx).

    The ``call()`` method follows the same contract as ``AnthropicLLM.call()``:
    it accepts a system prompt and a list of conversation messages, blocks on
    the rate limiter, makes the API call, corrects the rate-limiter reservation
    with actual token counts, logs timing/usage, and returns the response text.

    Parameters
    ----------
    base_url:
        Root URL of the API server **without** a trailing slash.
        ``/chat/completions`` is appended automatically.
    api_key:
        Bearer token.  Local servers (Ollama, LM Studio) accept any
        non-empty string; use ``"ollama"`` as the conventional placeholder.
    model:
        Model identifier the server recognises, e.g. ``"llama3"``.
    max_tokens:
        Maximum tokens to generate.  ``0`` (default) omits the field so
        the server uses its own default.
    temperature:
        Sampling temperature (0 - 2).  Defaults to 0.7.
    timeout:
        Total HTTP request timeout in seconds.
    max_retries:
        Retry attempts on 5xx / network errors.  Uses exponential back-off
        starting at *retry_delay* seconds, doubling each attempt.
    retry_delay:
        Initial wait between retries in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 0,
        temperature: float = 0.7,
        timeout: float = 120.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        if max_retries < 1:
            raise ValueError(
                f"[OpenAILLM] max_retries must be >= 1, got {max_retries}"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens          # 0 = omit from request
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._endpoint = f"{self.base_url}/chat/completions"

        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        logger.info(
            f"[OpenAILLM] Ready - endpoint={self._endpoint}  model={self.model}"
        )

    # ------------------------------------------------------------------
    # LLM interface
    # ------------------------------------------------------------------

    def call(self, system: str, messages: List[Dict[str, str]]) -> str:
        """
        Send a chat-completion request and return the assistant reply text.

        Integrates with the shared rate limiter and logger exactly like
        ``AnthropicLLM.call()`` so the rest of ntCode needs no changes.
        """
        if LOG_CONVERSATIONS:
            logger.info(
                f"[OpenAILLM] Sending {len(messages)} messages  (model={self.model})"
            )
            if DEBUG_MODE:
                logger.debug(f"[OpenAILLM] Messages: {json.dumps(messages, indent=2)}")

        # -- rate limiting ----------------------------------------------
        estimated = self._estimate_tokens(system, messages)
        logger.debug(f"[OpenAILLM] Estimated token cost: {estimated}")
        reservation_id = _rate_limiter.wait_for_capacity(estimated)
        # --------------------------------------------------------------

        payload = self._build_payload(system, messages)
        start = time.time()
        raw = self._post_with_retry(payload)
        elapsed = time.time() - start

        text, input_tokens, output_tokens = self._parse(raw)
        actual_tokens = input_tokens + output_tokens

        # -- correct rate-limiter reservation --------------------------
        _rate_limiter.record_actual(reservation_id, actual_tokens)
        # --------------------------------------------------------------

        if LOG_CONVERSATIONS:
            logger.info(
                f"[OpenAILLM] Response ({len(text)} chars) in {elapsed:.2f}s "
                f"| tokens: {input_tokens} in / {output_tokens} out "
                f"(total: {actual_tokens}) | {_rate_limiter.status()}"
            )
            if DEBUG_MODE:
                logger.debug(f"[OpenAILLM] Response text: {text}")

        return text

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(system: str, messages: List[Dict[str, str]]) -> int:
        """Heuristic token estimate: 1 token ~= 4 characters."""
        total_chars = len(system)
        for msg in messages:
            content = msg.get("content", "")
            total_chars += (
                len(content) if isinstance(content, str) else len(json.dumps(content))
            )
        return max(1, total_chars // 4)

    @staticmethod
    def _flatten_content(content: "str | list") -> str:
        """Reduce a content value to a plain string.

        Anthropic-style content blocks (list of dicts with a ``type`` key)
        are joined by concatenating all ``text`` block values.  Cache-control
        markers and other non-text block types are silently dropped because
        OpenAI-compatible endpoints only accept plain strings in the
        ``content`` field.

        Args:
            content: Either a plain string or a list of content-block dicts
                     (as produced by ConversationManager.messages_for_api()).

        Returns:
            A single plain string suitable for the OpenAI ``content`` field.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(parts)
        # Fallback for any other unexpected type
        return str(content)

    @staticmethod
    def _is_native_fc_model(model: str) -> bool:
        """Return True if *model* is a real OpenAI GPT model that uses native
        function calling via the ``tools`` parameter.

        Real OpenAI models (gpt-4o, gpt-4, gpt-3.5-turbo, o1, o3, o4, etc.)
        do NOT reliably follow the text-protocol ``tool: NAME({...})``
        instructions in the system prompt — they expect the ``tools`` field in
        the API payload instead.

        Local models via Ollama/LM Studio/vLLM continue to use the text
        protocol, so they are not affected.
        """
        m = model.lower()
        return (
            m.startswith("gpt-")
            or m.startswith("o1")
            or m.startswith("o3")
            or m.startswith("o4")
            or m.startswith("chatgpt-")
        )

    @staticmethod
    def _build_tools_schema() -> List[Dict[str, Any]]:
        """Build the OpenAI function-calling ``tools`` list from TOOL_REGISTRY.

        Each entry follows the OpenAI JSON Schema spec::

            {
              "type": "function",
              "function": {
                "name": "...",
                "description": "...",
                "parameters": {
                  "type": "object",
                  "properties": {...},
                  "required": [...]
                }
              }
            }

        Python type annotations are mapped to JSON Schema types; unannotated
        parameters default to ``"string"``.
        """
        import inspect
        from tools.registry import TOOL_REGISTRY

        _ANN_TO_JSON: Dict[Any, str] = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
        }

        tools_schema: List[Dict[str, Any]] = []
        for name, fn in TOOL_REGISTRY.items():
            sig = inspect.signature(fn)
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for pname, param in sig.parameters.items():
                ann = param.annotation
                # Handle List[str] and similar typing generics
                if hasattr(ann, "__name__"):
                    # Plain type like str, int, bool
                    json_type = _ANN_TO_JSON.get(ann, "string")
                    prop: Dict[str, Any] = {"type": json_type, "description": pname}
                else:
                    origin = getattr(ann, "__origin__", None)
                    if origin is list:
                        type_args = getattr(ann, "__args__", (str,))
                        item_type = _ANN_TO_JSON.get(type_args[0], "string") if type_args else "string"
                        prop = {
                            "type": "array",
                            "items": {"type": item_type},
                            "description": pname,
                        }
                    else:
                        prop = {"type": "string", "description": pname}

                if param.default is not inspect.Parameter.empty:
                    prop["default"] = param.default
                else:
                    required.append(pname)

                properties[pname] = prop

            fn_schema: Dict[str, Any] = {
                "name": name,
                "description": (fn.__doc__ or "").strip(),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            }
            if required:
                fn_schema["parameters"]["required"] = required

            tools_schema.append({"type": "function", "function": fn_schema})

        return tools_schema

    def _build_payload(self, system: "str | list", messages: List[Dict[str, Any]]) -> dict:
        """Assemble the JSON body for /chat/completions.

        Handles both plain-string and structured-list content values so that
        messages produced by ConversationManager (which may carry
        cache_control blocks) are flattened to plain strings before being
        sent to the OpenAI-compatible endpoint.

        For real OpenAI GPT models, includes the ``tools`` parameter so that
        native function calling is activated.  The ``_parse()`` method then
        converts any ``tool_calls`` in the response back to ntcode text so
        the rest of the stack needs no changes.

        Raises:
            ValueError: If a message is missing the required ``role`` key.
        """
        # Flatten system prompt in case it is a list of content blocks
        system_str = self._flatten_content(system)

        # OpenAI spec: system role sits at index 0
        openai_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_str}]

        for i, m in enumerate(messages):
            if "role" not in m:
                raise ValueError(
                    f"[OpenAILLM] Message at index {i} is missing required 'role' key: {m!r}"
                )
            role = m["role"]
            raw_content = m.get("content", "")
            openai_messages.append({"role": role, "content": self._flatten_content(raw_content)})

        body: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": self.temperature,
        }
        if self.max_tokens:          # omit when 0 - let the server decide
            body["max_tokens"] = self.max_tokens

        # Pass native function-calling schema for real OpenAI GPT models.
        # Local/other models use the text-protocol instructions in the system
        # prompt instead; adding "tools" would confuse them or cause errors.
        if self._is_native_fc_model(self.model):
            tools_schema = self._build_tools_schema()
            if tools_schema:
                body["tools"] = tools_schema
                body["tool_choice"] = "auto"
                logger.debug(
                    "[OpenAILLM] Added %d tool(s) to payload for native function calling.",
                    len(tools_schema),
                )

        return body

    def _post_with_retry(self, payload: dict) -> dict:
        """
        POST to /chat/completions with exponential-backoff retries.

        * Retries on 5xx responses and network/timeout errors.
        * Raises immediately on 4xx (client error - no point retrying).
        """
        delay = self.retry_delay
        last_error: Exception = RuntimeError("No attempts made")

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._http.post(self._endpoint, json=payload)

                if resp.status_code == 200:
                    logger.debug(
                        f"[OpenAILLM] POST {self._endpoint} -> 200  (attempt {attempt})"
                    )
                    return resp.json()

                # 4xx - client-side error, do not retry
                if 400 <= resp.status_code < 500:
                    self._raise_for_4xx(resp)

                # 5xx - transient server error, retry
                last_error = RuntimeError(
                    f"HTTP {resp.status_code}: {resp.text[:200]}"
                )
                logger.warning(
                    f"[OpenAILLM] Server error {resp.status_code} on attempt "
                    f"{attempt}/{self.max_retries} - retrying in {delay:.1f}s"
                )

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                logger.warning(
                    f"[OpenAILLM] Network error on attempt {attempt}/{self.max_retries}: "
                    f"{exc!r} - retrying in {delay:.1f}s"
                )

            if attempt < self.max_retries:
                time.sleep(delay)
                delay *= 2      # exponential back-off

        raise RuntimeError(
            f"[OpenAILLM] All {self.max_retries} attempts to {self._endpoint} failed. "
            f"Last error: {last_error}"
        )

    @staticmethod
    def _raise_for_4xx(resp: httpx.Response) -> None:
        """Translate HTTP 4xx codes into descriptive exceptions."""
        code = resp.status_code
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except Exception:
            detail = resp.text
        if code == 401:
            raise PermissionError(
                f"[OpenAILLM] 401 Unauthorized - check OPENAI_API_KEY. ({detail})"
            )
        if code == 403:
            raise PermissionError(f"[OpenAILLM] 403 Forbidden. ({detail})")
        if code == 404:
            raise ValueError(
                f"[OpenAILLM] 404 Not Found - wrong OPENAI_BASE_URL or OPENAI_MODEL? "
                f"({detail})"
            )
        if code == 429:
            raise RuntimeError(
                f"[OpenAILLM] 429 Rate limited by remote server. ({detail})"
            )
        raise RuntimeError(f"[OpenAILLM] HTTP {code}: {detail}")

    @staticmethod
    def _parse(raw: dict) -> tuple[str, int, int]:
        """
        Extract (text, input_tokens, output_tokens) from a /chat/completions
        response dict.  Token counts gracefully default to 0 when the server
        omits the ``usage`` field (some local servers do this).

        Handles two response shapes:

        1. Plain text reply -- ``choices[0].message.content`` is a non-empty
           string.  Returned as-is.

        2. Native function-calling reply -- ``choices[0].message.content`` is
           ``null`` and ``choices[0].message.tool_calls`` contains one or more
           structured tool invocations (as returned by real OpenAI endpoints
           such as GPT-4o when they decide to use their native tool-calling
           API rather than following the text-protocol instructions in the
           system prompt).  Each entry is converted into an ntcode-format
           ``tool: NAME({...})`` text line so the existing ntcode parser can
           handle it unchanged.
        """
        try:
            message = raw["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(
                f"[OpenAILLM] Unexpected response shape - missing choices[0].message.\n"
                f"raw={json.dumps(raw)[:500]}"
            ) from exc

        content: str = message.get("content") or ""

        # If content is empty the model may have used native tool_calls instead.
        if not content:
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                lines: List[str] = []
                for tc in tool_calls:
                    try:
                        fn = tc["function"]
                        name: str = fn["name"]
                        # arguments is a JSON string in the OpenAI wire format.
                        args_str: str = fn.get("arguments", "{}")
                        # Validate it parses as JSON so the ntcode parser won't
                        # choke; re-serialise to ensure compact single-line form.
                        args_obj = json.loads(args_str)
                        args_compact = json.dumps(args_obj, ensure_ascii=False)
                        lines.append(f"tool: {name}({args_compact})")
                        logger.debug(
                            "[OpenAILLM] Converted native tool_call to ntcode: %s",
                            lines[-1],
                        )
                    except (KeyError, json.JSONDecodeError) as exc:
                        logger.warning(
                            "[OpenAILLM] Skipping malformed tool_call entry %r: %s",
                            tc,
                            exc,
                        )
                content = "\n".join(lines)
                if content:
                    logger.info(
                        "[OpenAILLM] Converted %d native tool_call(s) to ntcode text.",
                        len(lines),
                    )

        usage = raw.get("usage") or {}
        input_tokens: int = usage.get("prompt_tokens", 0)
        output_tokens: int = usage.get("completion_tokens", 0)
        return content, input_tokens, output_tokens

    def close(self) -> None:
        """Close the underlying httpx connection pool."""
        self._http.close()

    def __enter__(self) -> "OpenAILLM":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"OpenAILLM(base_url={self.base_url!r}, model={self.model!r}, "
            f"temperature={self.temperature}, max_tokens={self.max_tokens})"
        )
