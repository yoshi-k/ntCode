import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import anthropic

from utils.config import (
    DEFAULT_MODEL,
    API_MAX_TOKENS,
    API_TIMEOUT,
    LOG_CONVERSATIONS,
    DEBUG_MODE,
    logger,
)
from utils.rate_limiter import _rate_limiter


# ---------------------------------------------------------------------------
# LLM provider abstraction
# ---------------------------------------------------------------------------


class LLM(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def call(self, system: str, messages: List[Dict[str, str]]) -> str:
        """
        Send a conversation to the LLM and return the response text.
        :param system: System prompt string.
        :param messages: List of {"role": ..., "content": ...} dicts (no system messages).
        :return: Response text from the model.
        """


class AnthropicLLM(LLM):
    """LLM implementation backed by the Anthropic Claude API."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = API_MAX_TOKENS,
        timeout: float = API_TIMEOUT,
    ):
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    @staticmethod
    def _estimate_tokens(
        system: str, messages: List[Dict[str, str]], max_tokens: int
    ) -> int:
        """Cheap pre-request token estimate (heuristic: 1 token ≈ 4 chars).

        We add *max_tokens* as a pessimistic upper bound for the reply so
        the rate limiter reserves enough headroom for both prompt and
        completion before the real numbers are known.
        """
        total_chars = len(system)
        for msg in messages:
            content = msg.get("content", "")
            total_chars += (
                len(content) if isinstance(content, str) else len(json.dumps(content))
            )
        return (total_chars // 4) + max_tokens

    def call(self, system: str, messages: List[Dict[str, str]]) -> str:
        """
        Call the Anthropic Claude API and return the response text.
        Raises provider-specific exceptions; callers should handle them.

        Rate limiting: before each API call the method blocks via
        ``_rate_limiter.wait_for_capacity()`` until the rolling 60-second
        token window has enough headroom.  After the call the reservation is
        corrected with the actual token counts reported by the API.
        """
        if LOG_CONVERSATIONS:
            logger.info(f"Sending {len(messages)} messages to LLM (model={self.model})")
            if DEBUG_MODE:
                logger.debug(f"Messages: {json.dumps(messages, indent=2)}")

        # --- Rate limiting: reserve capacity before hitting the API -------
        estimated = self._estimate_tokens(system, messages, self.max_tokens)
        logger.debug(f"Estimated token cost for this request: {estimated}")
        reservation_id = _rate_limiter.wait_for_capacity(estimated)
        # ------------------------------------------------------------------

        start_time = time.time()

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            timeout=self.timeout,
        )

        elapsed = time.time() - start_time
        response_text = response.content[0].text
        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0
        actual_tokens = input_tokens + output_tokens

        # --- Rate limiting: correct the optimistic reservation ------------
        _rate_limiter.record_actual(reservation_id, actual_tokens)
        # ------------------------------------------------------------------

        if LOG_CONVERSATIONS:
            logger.info(
                f"Received response ({len(response_text)} chars) in {elapsed:.2f}s "
                f"| tokens: {input_tokens} in / {output_tokens} out "
                f"(total: {actual_tokens}) | {_rate_limiter.status()}"
            )
            if DEBUG_MODE:
                logger.debug(f"Response: {response_text}")

        return response_text


import os


def _build_llm() -> LLM:
    """
    Instantiate the LLM provider selected by the ``LLM_PROVIDER`` env var.

    ``"anthropic"`` (default)
        Uses :class:`AnthropicLLM` with the Anthropic SDK.
        Requires ``ANTHROPIC_API_KEY``.

    ``"openai"``
        Uses :class:`~utils.openai_llm.OpenAILLM` — connects to any
        OpenAI-compatible HTTP endpoint (Ollama, LM Studio, vLLM, OpenAI,
        Groq, …).  Requires ``OPENAI_BASE_URL``, ``OPENAI_API_KEY``,
        ``OPENAI_MODEL`` in ``.env``.
    """
    from utils.config import LLM_PROVIDER  # late import avoids circular deps

    if LLM_PROVIDER == "openai":
        from utils.openai_llm import OpenAILLM
        from utils.config import (
            OPENAI_BASE_URL,
            OPENAI_API_KEY,
            OPENAI_MODEL,
            OPENAI_MAX_TOKENS,
            OPENAI_TEMPERATURE,
            OPENAI_TIMEOUT,
            OPENAI_MAX_RETRIES,
        )
        logger.info(
            f"[LLM] Provider: openai-compatible  "
            f"url={OPENAI_BASE_URL}  model={OPENAI_MODEL}"
        )
        return OpenAILLM(
            base_url=OPENAI_BASE_URL,
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
            timeout=OPENAI_TIMEOUT,
            max_retries=OPENAI_MAX_RETRIES,
        )

    # Default: Anthropic
    logger.info(f"[LLM] Provider: anthropic  model={os.environ.get('NTCODE_MODEL', DEFAULT_MODEL)}")
    return AnthropicLLM(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("NTCODE_MODEL", DEFAULT_MODEL),
    )


# Active LLM instance used throughout the application.
# Swap provider by setting LLM_PROVIDER in .env — no code changes needed.
llm: LLM = _build_llm()


def execute_llm_call(conversation: List[Dict[str, str]]) -> str:
    """Prepare the conversation and delegate to the active LLM provider."""
    system_content = ""
    messages = []
    for msg in conversation:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            messages.append(msg)

    # Conversation pruning is handled in run_coding_agent_loop() before this call.

    try:
        return llm.call(system_content, messages)
    except anthropic.APITimeoutError as e:
        logger.error(f"API timeout error: {str(e)}")
        return (
            "\u23f1\ufe0f Request timed out. The conversation may be too long or the request too "
            "complex. Try:\n- Breaking your request into smaller parts\n"
            "- Starting a fresh conversation\n- Reducing the amount of context"
        )
    except anthropic.RateLimitError as e:
        logger.error(f"Rate limit error: {str(e)}")
        return "\U0001f6ab Rate limit exceeded. Please wait a moment before trying again."
    except anthropic.APIConnectionError as e:
        logger.error(f"API connection error: {str(e)}")
        return "\U0001f310 Failed to connect to Claude API. Please check your internet connection and try again."
    except anthropic.AuthenticationError as e:
        logger.error(f"Authentication error: {str(e)}")
        return "\U0001f511 Authentication failed. Please check your ANTHROPIC_API_KEY in your .env file."
    except anthropic.APIError as e:
        logger.error(f"API error: {str(e)}")
        return f"\u274c Claude API error: {str(e)}"
    except Exception as e:
        logger.error(f"LLM call failed: {str(e)}")
        return f"\U0001f4a5 Unexpected error calling LLM: {str(e)}"
