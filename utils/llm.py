"""LLM providers, prompt-caching helpers, and ConversationManager for ntCode.

This module contains:

* LLM / AnthropicLLM   - provider abstraction and Anthropic implementation.
* apply_cache_control   - stamps a content block with a cache_control marker.
* mark_last_content_block - marks the tail block of a list for caching.
* SessionHeader         - builds the stable, cached session-header prefix.
* ConversationManager   - task-scoped history with cache-point resets.
* execute_llm_call      - dispatch to the active provider (legacy + cache-aware).

The context helpers are defined here (not in a subpackage) so that they can
always be written to disk without requiring subdirectory creation::

    from utils.llm import SessionHeader, ConversationManager
"""

import copy
import json
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


# ===========================================================================
# Prompt-caching helpers
# ===========================================================================

_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}


def apply_cache_control(block: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *block* with a cache_control marker attached.

    The original dict is never mutated.  The marker instructs Claude to store
    everything up to and including this block in its server-side KV-cache
    (prompt-caching-2024-07-31 beta).

    Args:
        block: A single Claude content block, e.g.
               {"type": "text", "text": "..."}.

    Returns:
        A new dict equal to *block* plus
        "cache_control": {"type": "ephemeral"}.
    """
    return {**block, "cache_control": _EPHEMERAL}


def mark_last_content_block(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of *content* where only the last block is cache-marked.

    Claude allows at most four cache breakpoints per request; marking only
    the tail block of a logical section keeps breakpoint usage minimal.

    Args:
        content: A non-empty list of Claude content block dicts.

    Returns:
        A new list; all blocks unchanged except the last, which gains
        cache_control.

    Raises:
        ValueError: If *content* is empty.
    """
    if not content:
        raise ValueError("content list must not be empty")
    *head, tail = content
    return head + [apply_cache_control(tail)]


# ===========================================================================
# SessionHeader
# ===========================================================================

_ASSISTANT_ACK = (
    "Understood. I have read the project documentation "
    "(agent.md, outline.md, file_organization.md) and am ready to assist."
)


class SessionHeader:
    """Builds and owns the cacheable session-header prefix.

    The session header consists of two parts sent at the top of every API
    request:

    1. System block (the system= parameter) - the full system prompt (tool
       descriptions + instructions), marked with cache_control so Claude
       caches it server-side.

    2. User/assistant message pair - a user message embedding the core
       documentation files (agent.md, outline.md, file_organization.md)
       followed by a short assistant acknowledgement.  The last content
       block of the user message is also cache-marked.

    Together these form the session cache point: once Claude processes them
    on the first request, subsequent requests beginning with the same bytes
    hit the cache - faster and ~10x cheaper for the cached tokens.

    The header is stateless with respect to tasks - constructed once at
    agent startup and never mutated.  ConversationManager prepends it to
    every API call transparently.

    Attributes:
        system_prompt: Raw system-prompt string.
        doc_paths:     Ordered list of documentation file paths to embed.
    """

    def __init__(
        self,
        system_prompt: str,
        doc_paths: list[str] | None = None,
    ) -> None:
        """
        Args:
            system_prompt: The full system prompt, e.g. from
                           tools.registry.get_full_system_prompt().
            doc_paths:     Documentation files to embed in the user-turn
                           header message.  Defaults to the three canonical
                           ntCode docs when None.
        """
        self.system_prompt: str = system_prompt
        self.doc_paths: list[str] = doc_paths if doc_paths is not None else [
            "agent.md",
            "outline.md",
            "file_organization.md",
        ]
        # Eagerly load docs so missing-file errors surface at startup.
        self._doc_blocks: list[dict[str, Any]] = self._load_docs()

    def _load_docs(self) -> list[dict[str, Any]]:
        """Read each doc file and return one plain text content block per file."""
        blocks: list[dict[str, Any]] = []
        for path_str in self.doc_paths:
            path = Path(path_str)
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                logger.warning(
                    "SessionHeader: doc file not found, skipping: %s", path_str
                )
                continue
            except OSError as exc:
                logger.warning(
                    "SessionHeader: could not read %s: %s", path_str, exc
                )
                continue
            blocks.append({"type": "text", "text": f"### {path.name}\n{text}"})
        return blocks

    def system_block(self) -> list[dict[str, Any]]:
        """Return the value to pass as system= in the Anthropic API call.

        The system prompt is wrapped in a single cache-marked text block so
        Claude caches all tokens up to and including this block.

        Returns:
            [{"type": "text", "text": "...",
              "cache_control": {"type": "ephemeral"}}]
        """
        return [apply_cache_control({"type": "text", "text": self.system_prompt})]

    def as_user_message(self) -> dict[str, Any]:
        """Build the user-turn message that carries the documentation files.

        The last content block is cache-marked so Claude caches everything
        in this message together with the system prompt above it.

        Returns:
            {"role": "user", "content": [...]} ready for the messages list.
        """
        blocks = list(self._doc_blocks)
        if not blocks:
            blocks = [{"type": "text", "text": "(no documentation loaded)"}]
        return {"role": "user", "content": mark_last_content_block(blocks)}

    def as_assistant_ack(self) -> dict[str, Any]:
        """Return a minimal assistant acknowledgement to follow the header message.

        Claude requires strictly alternating user/assistant turns.  After the
        user-side header we inject a short canned reply so the next real user
        message is accepted without a turn-order error.

        Returns:
            {"role": "assistant", "content": [...]}
        """
        return {
            "role": "assistant",
            "content": [{"type": "text", "text": _ASSISTANT_ACK}],
        }

    def as_message_pair(self) -> list[dict[str, Any]]:
        """Return [user_header_message, assistant_ack].

        Prepend to every request's messages list so the session header is
        always in position and eligible for cache reuse.
        """
        return [self.as_user_message(), self.as_assistant_ack()]


# ===========================================================================
# ConversationManager
# ===========================================================================


class ConversationManager:
    """Manages the full conversation with cache-point awareness.

    The conversation is split into two logical regions:

    * Session header - the stable prefix owned by SessionHeader.
      Always prepended to every API call with Claude cache_control markers.
      Never discarded between tasks.

    * Task context - everything that follows the header for the current task.
      Discarded (reset to the cache point) when start_task() is called.

    Typical usage::

        from tools.registry import get_full_system_prompt
        from utils.llm import SessionHeader, ConversationManager

        header = SessionHeader(system_prompt=get_full_system_prompt())
        mgr    = ConversationManager(header)

        mgr.start_task("Refactor the login module")
        mgr.add_assistant("Reading the file...")
        mgr.add_user("tool_result(...)")

        system   = mgr.system_for_api()    # pass as system=
        messages = mgr.messages_for_api()  # pass as messages=

    Attributes:
        session_header: The SessionHeader that owns the cached prefix.
    """

    def __init__(self, session_header: SessionHeader) -> None:
        self.session_header: SessionHeader = session_header
        self._task_messages: list[dict[str, Any]] = []
        self._save_points: dict[str, list[dict[str, Any]]] = {}

    def start_task(self, task_description: str = "") -> None:
        """Begin a new task, resetting the conversation to the cache point.

        All messages accumulated since the last start_task() call are
        discarded.  The session header is preserved and re-sent with cache
        markers so Claude can reuse its server-side KV-cache.

        Args:
            task_description: If non-empty, added as the first user message
                of the new task context.
        """
        prev = len(self._task_messages)
        self._task_messages = []
        logger.info(
            "ConversationManager: reset to cache point (discarded %d message(s))", prev
        )
        if task_description:
            self.add_user(task_description)

    def add_user(self, text: str) -> None:
        """Append a plain user-role text message to the current task context."""
        self._task_messages.append(
            {"role": "user", "content": [{"type": "text", "text": text}]}
        )

    def add_assistant(self, text: str) -> None:
        """Append a plain assistant-role text message to the current task context."""
        self._task_messages.append(
            {"role": "assistant", "content": [{"type": "text", "text": text}]}
        )

    def add_message(
        self, role: str, content: "str | list[dict[str, Any]]"
    ) -> None:
        """Append a message with an arbitrary content payload.

        Args:
            role:    "user" or "assistant".
            content: Plain string (auto-wrapped) or a pre-built block list.
        """
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        self._task_messages.append({"role": role, "content": content})

    def system_for_api(self) -> list[dict[str, Any]]:
        """Return the system= parameter value for the Anthropic API."""
        return self.session_header.system_block()

    def messages_for_api(self) -> list[dict[str, Any]]:
        """Return [header_user, header_ack, *task_messages] for the API."""
        return self.session_header.as_message_pair() + list(self._task_messages)

    def prune_task_messages(self, max_messages: int) -> None:
        """Trim the task-local message list to at most *max_messages* entries.

        Keeps the most recent messages.  The session header is never pruned.
        """
        if len(self._task_messages) > max_messages:
            before = len(self._task_messages)
            self._task_messages = self._task_messages[-max_messages:]
            logger.info(
                "ConversationManager: pruned %d -> %d task messages",
                before, len(self._task_messages),
            )

    def as_flat_conversation(self) -> list[dict[str, Any]]:
        """Return a flat conversation list for JSON serialisation (save/load).

        The returned list has role=user/assistant messages only (no cache
        markers), suitable for json.dump and later restore via
        restore_from_flat().
        """
        result: list[dict[str, Any]] = []
        for msg in self._task_messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, list):
                text = " ".join(
                    b.get("text", "") for b in content if b.get("type") == "text"
                )
            else:
                text = str(content)
            result.append({"role": role, "content": text})
        return result

    def restore_from_flat(self, flat: list[dict[str, Any]]) -> None:
        """Replace the task context with a previously serialised flat list."""
        self._task_messages = []
        for msg in flat:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "user":
                self.add_user(text)
            else:
                self.add_assistant(text)

    # ------------------------------------------------------------------
    # Named save points (in-memory rollback)
    # ------------------------------------------------------------------

    def save_point(self, name: str) -> None:
        """Snapshot the current task context under *name*.

        Stores a deep copy of the task-message list so that future mutations
        do not affect the saved state.  Calling save_point() with the same
        name overwrites the previous snapshot.

        Args:
            name: Arbitrary label for the save point (e.g. "before-refactor").
        """
        if not name:
            raise ValueError("save_point name must not be empty")
        self._save_points[name] = copy.deepcopy(self._task_messages)
        logger.info(
            "ConversationManager: save_point %r captured (%d messages)",
            name,
            len(self._task_messages),
        )

    def restore(self, name: str) -> None:
        """Restore the task context to the snapshot stored under *name*.

        The current task context is discarded and replaced with a deep copy
        of the saved snapshot.  The session header is never affected.

        Args:
            name: Label used in the matching save_point() call.

        Raises:
            KeyError: If no save point with *name* exists.
        """
        if name not in self._save_points:
            raise KeyError(f"No save point named {name!r}. "
                           f"Available: {sorted(self._save_points)}")
        self._task_messages = copy.deepcopy(self._save_points[name])
        logger.info(
            "ConversationManager: restored to save_point %r (%d messages)",
            name,
            len(self._task_messages),
        )

    def delete_save_point(self, name: str) -> None:
        """Remove a named save point, freeing its memory.

        Args:
            name: Label of the save point to delete.

        Raises:
            KeyError: If no save point with *name* exists.
        """
        if name not in self._save_points:
            raise KeyError(f"No save point named {name!r}. "
                           f"Available: {sorted(self._save_points)}")
        del self._save_points[name]
        logger.info("ConversationManager: deleted save_point %r", name)

    @property
    def save_point_names(self) -> list[str]:
        """Sorted list of currently stored save point names."""
        return sorted(self._save_points)

    @property
    def task_message_count(self) -> int:
        """Number of messages in the current task context (excluding header)."""
        return len(self._task_messages)

    def __repr__(self) -> str:  # pragma: no cover
        return f"ConversationManager(task_messages={self.task_message_count})"


# ===========================================================================
# LLM provider abstraction
# ===========================================================================


class LLM(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def call(self, system: Any, messages: List[Dict[str, Any]]) -> str:
        """Send a conversation to the LLM and return the response text.

        Args:
            system:   System prompt - either a plain string or a list of
                      content blocks (the latter carries cache_control markers
                      for Claude prompt caching).
            messages: Conversation history; no system messages included.

        Returns:
            Response text from the model.
        """


class AnthropicLLM(LLM):
    """LLM implementation backed by the Anthropic Claude API.

    Supports prompt caching: when *system* is passed as a list[dict] with
    cache_control markers (built by SessionHeader) the beta header
    prompt-caching-2024-07-31 is added automatically and cached tokens are
    billed at ~10x lower cost.  Cache read/write counts are logged.
    """

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
        system: Any, messages: List[Dict[str, Any]], max_tokens: int
    ) -> int:
        """Cheap pre-request token estimate (heuristic: 1 token ~= 4 chars).

        Handles both plain-string and structured-list system values.
        Adds max_tokens as a pessimistic upper bound for the reply.
        """
        if isinstance(system, str):
            system_chars = len(system)
        else:
            system_chars = sum(len(b.get("text", "")) for b in system)
        total_chars = system_chars
        for msg in messages:
            content = msg.get("content", "")
            total_chars += (
                len(content) if isinstance(content, str) else len(json.dumps(content))
            )
        return (total_chars // 4) + max_tokens

    @staticmethod
    def _needs_caching_beta(
        system: Any, messages: List[Dict[str, Any]]
    ) -> bool:
        """Return True if any content block carries a cache_control marker."""
        if isinstance(system, list):
            if any("cache_control" in b for b in system):
                return True
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                if any("cache_control" in b for b in content):
                    return True
        return False

    def call(self, system: Any, messages: List[Dict[str, Any]]) -> str:
        """Call the Anthropic Claude API and return the response text.

        Args:
            system:   Plain system-prompt string or a list of content blocks
                      (possibly with cache_control markers from SessionHeader).
            messages: Conversation history (user/assistant turns), also
                      possibly containing cache_control blocks.

        Rate limiting: blocks via _rate_limiter.wait_for_capacity() before
        each call and corrects the reservation with actual token counts after.

        Prompt caching: when system or any message content block carries a
        cache_control marker, the prompt-caching-2024-07-31 beta header is
        added automatically and cache statistics are logged.
        """
        if LOG_CONVERSATIONS:
            logger.info(f"Sending {len(messages)} messages to LLM (model={self.model})")
            if DEBUG_MODE:
                logger.debug(f"Messages: {json.dumps(messages, indent=2)}")

        estimated = self._estimate_tokens(system, messages, self.max_tokens)
        logger.debug(f"Estimated token cost for this request: {estimated}")
        reservation_id = _rate_limiter.wait_for_capacity(estimated)

        start_time = time.time()
        logger.debug(
            f"API call starting: model={self.model} "
            f"estimated_tokens={estimated} messages={len(messages)}"
        )

        try:
            if self._needs_caching_beta(system, messages):
                response = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system,
                    messages=messages,
                    timeout=self.timeout,
                    betas=["prompt-caching-2024-07-31"],
                )
            else:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system,
                    messages=messages,
                    timeout=self.timeout,
                )
        except Exception:
            elapsed = time.time() - start_time
            logger.error(
                f"API call failed after {elapsed:.2f}s "
                f"(model={self.model} estimated_tokens={estimated} "
                f"messages={len(messages)})"
            )
            raise

        elapsed = time.time() - start_time
        response_text = response.content[0].text
        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0
        actual_tokens = input_tokens + output_tokens

        _rate_limiter.record_actual(reservation_id, actual_tokens)

        if LOG_CONVERSATIONS:
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_info = ""
            if cache_read or cache_write:
                cache_info = f" | cache_read={cache_read} cache_write={cache_write}"
            logger.info(
                f"Received response ({len(response_text)} chars) in {elapsed:.2f}s "
                f"| tokens: {input_tokens} in / {output_tokens} out "
                f"(total: {actual_tokens}){cache_info} | {_rate_limiter.status()}"
            )
            if DEBUG_MODE:
                logger.debug(f"Response: {response_text}")

        return response_text


def _build_llm() -> LLM:
    """Instantiate the LLM provider selected by the LLM_PROVIDER env var.

    'anthropic' (default): AnthropicLLM. Requires ANTHROPIC_API_KEY.
    'openai': OpenAILLM - any OpenAI-compatible endpoint (Ollama, etc.).
              Requires OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL in .env.
    """
    from utils.config import LLM_PROVIDER

    if LLM_PROVIDER == "openai":
        from utils.openai_llm import OpenAILLM
        from utils.config import (
            OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL,
            OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE, OPENAI_TIMEOUT, OPENAI_MAX_RETRIES,
        )
        logger.info(
            f"[LLM] Provider: openai-compatible  "
            f"url={OPENAI_BASE_URL}  model={OPENAI_MODEL}"
        )
        return OpenAILLM(
            base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY, model=OPENAI_MODEL,
            max_tokens=OPENAI_MAX_TOKENS, temperature=OPENAI_TEMPERATURE,
            timeout=OPENAI_TIMEOUT, max_retries=OPENAI_MAX_RETRIES,
        )

    logger.info(f"[LLM] Provider: anthropic  model={os.environ.get('NTCODE_MODEL', DEFAULT_MODEL)}")
    return AnthropicLLM(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("NTCODE_MODEL", DEFAULT_MODEL),
    )


# Active LLM instance. Swap via LLM_PROVIDER env var or switch_provider().
llm: LLM = _build_llm()


# ---------------------------------------------------------------------------
# Runtime provider switching
# ---------------------------------------------------------------------------

_PROVIDER_ALIASES = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
    "ollama": "openai",
    "groq": "openai",
    "lmstudio": "openai",
}


def list_providers() -> list[str]:
    """Return the sorted list of recognised provider aliases."""
    return sorted(_PROVIDER_ALIASES.keys())


def current_provider_name() -> str:
    """Return a human-readable description of the currently active provider."""
    cls = type(llm).__name__
    model = getattr(llm, "model", "?")
    return f"{cls} (model={model})"


def switch_provider(spec: str) -> str:
    """Replace the active llm instance with a new provider.

    spec: bare alias ('openai', 'anthropic', 'ollama' ...) or alias/model
    ('openai/gpt-4o', 'ollama/llama3', 'anthropic/claude-opus-4-5').

    Returns a status string.  Raises ValueError for unknown aliases or
    missing credentials.
    """
    global llm

    if "/" in spec:
        alias, model_override = spec.split("/", 1)
        model_override = model_override.strip()
    else:
        alias, model_override = spec.strip(), None

    alias = alias.lower().strip()
    if alias not in _PROVIDER_ALIASES:
        known = ", ".join(sorted(_PROVIDER_ALIASES))
        raise ValueError(f"Unknown provider alias '{alias}'. Known: {known}")

    canonical = _PROVIDER_ALIASES[alias]

    if canonical == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in the environment.")
        model = model_override or os.environ.get("NTCODE_MODEL", DEFAULT_MODEL)
        new_llm: LLM = AnthropicLLM(api_key=api_key, model=model)
    else:
        from utils.openai_llm import OpenAILLM
        from utils.config import (
            OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL,
            OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE, OPENAI_TIMEOUT, OPENAI_MAX_RETRIES,
        )
        _DEFAULT_URLS: dict[str, str] = {
            "ollama": "http://localhost:11434/v1",
            "lmstudio": "http://localhost:1234/v1",
            "groq": "https://api.groq.com/openai/v1",
            "openai": "https://api.openai.com/v1",
        }
        base_url = OPENAI_BASE_URL or _DEFAULT_URLS.get(alias, "http://localhost:11434/v1")
        model = model_override or OPENAI_MODEL
        new_llm = OpenAILLM(
            base_url=base_url, api_key=OPENAI_API_KEY, model=model,
            max_tokens=OPENAI_MAX_TOKENS, temperature=OPENAI_TEMPERATURE,
            timeout=OPENAI_TIMEOUT, max_retries=OPENAI_MAX_RETRIES,
        )

    # Close the previous provider's connection pool if it supports it
    # (OpenAILLM wraps an httpx.Client; AnthropicLLM has no close method).
    if hasattr(llm, "close") and callable(llm.close):
        try:
            llm.close()
            logger.info("[LLM] Previous provider closed successfully.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LLM] Error closing previous provider: %s", exc)

    llm = new_llm
    desc = current_provider_name()
    logger.info("[LLM] Provider switched to: %s", desc)
    return f"\u2705 Switched to {desc}"


def execute_llm_call(
    conversation: List[Dict[str, Any]],
    system_override: Any = None,
    messages_override: List[Dict[str, Any]] = None,
) -> str:
    """Prepare the conversation and delegate to the active LLM provider.

    Two calling conventions are supported:

    Legacy (backward compatible):
        Pass conversation as a flat list including a
        {"role": "system", "content": str} entry.  The system message is
        extracted and passed as a plain string to llm.call().

    Cache-aware (used by ConversationManager):
        Pass system_override (list[dict] from ConversationManager.
        system_for_api()) and messages_override (list[dict] from
        ConversationManager.messages_for_api()).  The conversation argument
        is ignored when both overrides are provided.  This path sends
        cache_control markers to Claude, activating prompt caching for the
        session header.
    """
    if system_override is not None and messages_override is not None:
        system: Any = system_override
        messages: List[Dict[str, Any]] = messages_override
    else:
        system = ""
        messages = []
        for msg in conversation:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                messages.append(msg)

    try:
        return llm.call(system, messages)
    except anthropic.APITimeoutError as e:
        logger.error(f"API timeout error: {str(e)}")
        return (
            "\u23f1\ufe0f Request timed out. The conversation may be too long or the "
            "request too complex. Try:\n- Breaking your request into smaller parts\n"
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
    # --- OpenAI-compatible / httpx errors (raised by OpenAILLM) ----------
    except PermissionError as e:
        # Raised by OpenAILLM._raise_for_4xx for HTTP 401/403
        logger.error("OpenAI authentication/permission error: %s", e)
        return (
            "\U0001f511 Authentication failed. "
            "Please check your OPENAI_API_KEY / OPENAI_BASE_URL in your .env file.\n"
            f"Detail: {e}"
        )
    except ValueError as e:
        # Raised by OpenAILLM._raise_for_4xx for HTTP 404 (wrong model/URL)
        logger.error("OpenAI request error (likely wrong model or base URL): %s", e)
        return (
            "\u274c Bad request to the OpenAI-compatible endpoint. "
            "Check OPENAI_BASE_URL and OPENAI_MODEL in your .env file.\n"
            f"Detail: {e}"
        )
    except RuntimeError as e:
        # Raised by OpenAILLM for HTTP 429, 5xx, or exhausted retries
        msg = str(e)
        logger.error("OpenAI runtime error: %s", msg)
        if "429" in msg or "Rate limited" in msg:
            return "\U0001f6ab Rate limit exceeded by the remote server. Please wait a moment before trying again."
        if "attempt" in msg and "failed" in msg:
            return (
                "\U0001f310 Failed to reach the OpenAI-compatible endpoint after "
                "multiple retries. Please check the server is running and "
                "OPENAI_BASE_URL is correct.\n"
                f"Detail: {msg}"
            )
        return f"\u274c OpenAI-compatible endpoint error: {msg}"
    except Exception as e:
        # httpx.TimeoutException, httpx.ConnectError, and anything else
        exc_type = type(e).__name__
        logger.error("LLM call failed (%s): %s", exc_type, e)
        if "Timeout" in exc_type or "timeout" in str(e).lower():
            return (
                "\u23f1\ufe0f Request timed out connecting to the LLM endpoint. "
                "Try:\n- Checking the server is reachable\n"
                "- Increasing OPENAI_TIMEOUT in your .env file\n"
                "- Breaking your request into smaller parts"
            )
        if "Connect" in exc_type or "connect" in str(e).lower():
            return (
                "\U0001f310 Failed to connect to the LLM endpoint. "
                "Please check the server is running and your network connection."
            )
        return f"\U0001f4a5 Unexpected error calling LLM: {str(e)}"
