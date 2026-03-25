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
        Sampling temperature (0 – 2).  Defaults to 0.7.
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
            f"[OpenAILLM] Ready — endpoint={self._endpoint}  model={self.model}"
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

        # ── rate limiting ──────────────────────────────────────────────
        estimated = self._estimate_tokens(system, messages)
        logger.debug(f"[OpenAILLM] Estimated token cost: {estimated}")
        reservation_id = _rate_limiter.wait_for_capacity(estimated)
        # ──────────────────────────────────────────────────────────────

        payload = self._build_payload(system, messages)
        start = time.time()
        raw = self._post_with_retry(payload)
        elapsed = time.time() - start

        text, input_tokens, output_tokens = self._parse(raw)
        actual_tokens = input_tokens + output_tokens

        # ── correct rate-limiter reservation ───────────────────────────
        _rate_limiter.record_actual(reservation_id, actual_tokens)
        # ──────────────────────────────────────────────────────────────

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
        """Heuristic token estimate: 1 token ≈ 4 characters."""
        total_chars = len(system)
        for msg in messages:
            content = msg.get("content", "")
            total_chars += (
                len(content) if isinstance(content, str) else len(json.dumps(content))
            )
        return max(1, total_chars // 4)

    def _build_payload(self, system: str, messages: List[Dict[str, str]]) -> dict:
        """Assemble the JSON body for /chat/completions."""
        # OpenAI spec: system role sits at index 0
        openai_messages = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": self.temperature,
        }
        if self.max_tokens:          # omit when 0 — let the server decide
            body["max_tokens"] = self.max_tokens
        return body

    def _post_with_retry(self, payload: dict) -> dict:
        """
        POST to /chat/completions with exponential-backoff retries.

        * Retries on 5xx responses and network/timeout errors.
        * Raises immediately on 4xx (client error — no point retrying).
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

                # 4xx — client-side error, do not retry
                if 400 <= resp.status_code < 500:
                    self._raise_for_4xx(resp)

                # 5xx — transient server error, retry
                last_error = RuntimeError(
                    f"HTTP {resp.status_code}: {resp.text[:200]}"
                )
                logger.warning(
                    f"[OpenAILLM] Server error {resp.status_code} on attempt "
                    f"{attempt}/{self.max_retries} — retrying in {delay:.1f}s"
                )

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                logger.warning(
                    f"[OpenAILLM] Network error on attempt {attempt}/{self.max_retries}: "
                    f"{exc!r} — retrying in {delay:.1f}s"
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
                f"[OpenAILLM] 401 Unauthorized — check OPENAI_API_KEY. ({detail})"
            )
        if code == 403:
            raise PermissionError(f"[OpenAILLM] 403 Forbidden. ({detail})")
        if code == 404:
            raise ValueError(
                f"[OpenAILLM] 404 Not Found — wrong OPENAI_BASE_URL or OPENAI_MODEL? "
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
        """
        try:
            text: str = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(
                f"[OpenAILLM] Unexpected response shape — missing choices[0].message.content.\n"
                f"raw={json.dumps(raw)[:500]}"
            ) from exc

        usage = raw.get("usage") or {}
        input_tokens: int = usage.get("prompt_tokens", 0)
        output_tokens: int = usage.get("completion_tokens", 0)
        return text, input_tokens, output_tokens

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
