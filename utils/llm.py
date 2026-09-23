"""LLM providers, prompt-caching helpers, and ConversationManager for ntCode.

This module contains:

* LLM                   - legacy text-in/text-out provider interface (OpenAILLM,
                          DummyLLM).  Native providers live in providers/.
* apply_cache_control   - stamps a content block with a cache_control marker.
* mark_last_content_block - marks the tail block of a list for caching.
* SessionHeader         - builds the stable, cached session-header prefix.
* ConversationManager   - task-scoped history with cache-point resets.
* execute_llm_call      - dispatch to a legacy LLM provider.

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

from utils.config import (
    DEFAULT_MODEL,
    API_MAX_TOKENS,
    API_TIMEOUT,
    LOG_CONVERSATIONS,
    DEBUG_MODE,
    logger,
)
from utils.rate_limiter import _rate_limiter
from core.types import Message, TextBlock, message_from_dict, message_to_dict
from providers.base import Provider


# ===========================================================================
# Prompt-caching helpers
# ===========================================================================

_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}


def apply_cache_control(block: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *block* with a cache_control marker attached.

    The original dict is never mutated.  The marker instructs Claude to store
    everything up to and including this block in its server-side KV-cache.

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

    def system_with_docs(self) -> str:
        """Return the system prompt with the documentation files appended.

        Used by native-tool-use providers, which cache the system prompt
        directly and need no user/assistant header pair.  A file whose text
        the system prompt already contains (inlined via ``{{FILE:...}}``) is
        not appended a second time.
        """
        parts = [self.system_prompt]
        for block in self._doc_blocks:
            body = block["text"].split("\n", 1)[1] if "\n" in block["text"] else ""
            if body.strip() and body.strip() not in self.system_prompt:
                parts.append(block["text"])
        return "\n\n".join(parts)

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

    * Task context - everything that follows the header for the current task,
      stored as provider-neutral :class:`core.types.Message` objects.
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
        self._task_messages: list[Message] = []
        self._save_points: dict[str, list[Message]] = {}

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
        self._task_messages.append(Message("user", (TextBlock(text),)))

    def add_assistant(self, text: str) -> None:
        """Append a plain assistant-role text message to the current task context."""
        self._task_messages.append(Message("assistant", (TextBlock(text),)))

    def add_message(self, message: Message) -> None:
        """Append a message, which may carry tool calls or tool results."""
        if not isinstance(message, Message):
            raise TypeError(f"expected core.types.Message, got {type(message).__name__}")
        self._task_messages.append(message)

    def messages(self) -> list[Message]:
        """Return the task-context messages (without the session header)."""
        return list(self._task_messages)

    def system_for_api(self) -> list[dict[str, Any]]:
        """Return the system= parameter value for the Anthropic API."""
        return self.session_header.system_block()

    def messages_for_api(self) -> list[dict[str, Any]]:
        """Return [header_user, header_ack, *task_messages] as text-block dicts.

        This is the format the current text-protocol providers consume.
        Messages holding tool-call or tool-result blocks cannot be expressed
        in it; those go through a provider adapter that takes
        :meth:`messages` directly.

        Raises:
            TypeError: If a task message contains a non-text block.
        """
        out = self.session_header.as_message_pair()
        for msg in self._task_messages:
            if not all(isinstance(b, TextBlock) for b in msg.content):
                raise TypeError(
                    "messages_for_api() only supports text messages; "
                    "tool calls, tool results and provider blocks need a "
                    "provider adapter"
                )
            out.append({
                "role": msg.role,
                "content": [{"type": "text", "text": b.text} for b in msg.content],
            })
        return out

    @staticmethod
    def _is_clean_start(msg: Message) -> bool:
        """True if the task context may begin at *msg*.

        It must be a user message, and must not be a tool-result message,
        whose calls would have been cut off (native APIs reject a result
        with no matching call).
        """
        return msg.role == "user" and not msg.results

    def prune_task_messages(self, max_messages: int) -> None:
        """Trim the task context to roughly the last *max_messages* messages.

        The kept part always starts at a user message that is not a tool
        result, so a tool call is never separated from its result.  The
        start moves forward from the plain cut point to the next such
        message; if there is none, it moves back to the previous one, which
        keeps a few more messages than asked for.  The session header is
        never pruned.
        """
        msgs = self._task_messages
        if len(msgs) <= max_messages:
            return
        cut = len(msgs) - max_messages
        start = next(
            (i for i in range(cut, len(msgs)) if self._is_clean_start(msgs[i])),
            None,
        )
        if start is None:
            start = next(
                (i for i in range(cut - 1, -1, -1) if self._is_clean_start(msgs[i])),
                0,
            )
        if start == 0:
            return
        before = len(msgs)
        self._task_messages = msgs[start:]
        logger.info(
            "ConversationManager: pruned %d -> %d task messages",
            before, len(self._task_messages),
        )

    def as_flat_conversation(self) -> list[dict[str, Any]]:
        """Return the task context as JSON-serialisable dicts (save/load).

        Uses :func:`core.types.message_to_dict`, so tool calls and results
        survive a save/restore round trip.  No cache markers are included.
        """
        return [message_to_dict(m) for m in self._task_messages]

    def restore_from_flat(self, flat: list[dict[str, Any]]) -> None:
        """Replace the task context with a previously serialised list.

        Accepts both the current format and the older one where ``content``
        is a plain string.
        """
        self._task_messages = [message_from_dict(m) for m in flat]

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


def _build_anthropic(model: str) -> "Provider":
    """Build the native-tool-use Claude adapter."""
    from providers.anthropic import AnthropicProvider

    return AnthropicProvider(
        model,
        api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        max_tokens=API_MAX_TOKENS,
        timeout=API_TIMEOUT,
        rate_limiter=_rate_limiter,
    )


def _build_openai(model: str, base_url: str) -> "LLM | Provider":
    """Build a client for an OpenAI-compatible endpoint.

    Native tool calling (providers.openai_chat.OpenAIChatProvider) unless
    CALLING_CONVENTION names a text format, which uses the legacy OpenAILLM.
    """
    from utils import config as cfg
    from utils.tool_format import openai_tool_mode

    mode = openai_tool_mode()
    logger.info(f"[LLM] Provider: openai-compatible ({mode} tools)  url={base_url}  model={model}")
    if mode == "native":
        from providers.openai_chat import OpenAIChatProvider

        return OpenAIChatProvider(
            model,
            base_url=base_url,
            api_key=cfg.OPENAI_API_KEY,
            max_tokens=cfg.OPENAI_MAX_TOKENS,
            temperature=cfg.OPENAI_TEMPERATURE,
            timeout=cfg.OPENAI_TIMEOUT,
            # OPENAI_MAX_RETRIES counts attempts; the SDK counts retries.
            max_retries=max(0, cfg.OPENAI_MAX_RETRIES - 1),
            rate_limiter=_rate_limiter,
        )

    from utils.openai_llm import OpenAILLM

    return OpenAILLM(
        base_url=base_url, api_key=cfg.OPENAI_API_KEY, model=model,
        max_tokens=cfg.OPENAI_MAX_TOKENS, temperature=cfg.OPENAI_TEMPERATURE,
        timeout=cfg.OPENAI_TIMEOUT, max_retries=cfg.OPENAI_MAX_RETRIES,
    )


def _build_llm() -> "LLM | Provider":
    """Instantiate the provider selected by the LLM_PROVIDER env var.

    'anthropic' (default): providers.anthropic.AnthropicProvider (native
              tool use).  Credentials come from ANTHROPIC_API_KEY or the
              SDK's other credential sources.
    'openai': any OpenAI-compatible endpoint (llama.cpp, Ollama, ...), see
              _build_openai.  Uses OPENAI_BASE_URL, OPENAI_API_KEY,
              OPENAI_MODEL from .env.
    """
    from utils.config import LLM_PROVIDER

    if LLM_PROVIDER == "openai":
        from utils import config as cfg

        return _build_openai(cfg.OPENAI_MODEL, cfg.OPENAI_BASE_URL)

    model = os.environ.get("NTCODE_MODEL", DEFAULT_MODEL)
    logger.info(f"[LLM] Provider: anthropic  model={model}")
    return _build_anthropic(model)


# Active LLM instance. Swap via LLM_PROVIDER env var or switch_provider().
llm: "LLM | Provider" = _build_llm()


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
        model = model_override or os.environ.get("NTCODE_MODEL", DEFAULT_MODEL)
        new_llm: "LLM | Provider" = _build_anthropic(model)
    else:
        from utils.config import OPENAI_BASE_URL, OPENAI_MODEL

        _DEFAULT_URLS: dict[str, str] = {
            "ollama": "http://localhost:11434/v1",
            "lmstudio": "http://localhost:1234/v1",
            "groq": "https://api.groq.com/openai/v1",
            "openai": "https://api.openai.com/v1",
        }
        base_url = OPENAI_BASE_URL or _DEFAULT_URLS.get(alias, "http://localhost:11434/v1")
        model = model_override or OPENAI_MODEL
        new_llm = _build_openai(model, base_url)

    # Close the previous provider's connection pool if it supports it.
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
    """Prepare the conversation and delegate to the active legacy LLM provider.

    Only for text-protocol providers (OpenAILLM, DummyLLM).  A
    providers.base.Provider (native tool calling) is driven by the agent loop directly.

    Two calling conventions are supported:

    Legacy (backward compatible):
        Pass conversation as a flat list including a
        {"role": "system", "content": str} entry.  The system message is
        extracted and passed as a plain string to llm.call().

    Cache-aware (used by ConversationManager):
        Pass system_override (list[dict] from ConversationManager.
        system_for_api()) and messages_override (list[dict] from
        ConversationManager.messages_for_api()).  The conversation argument
        is ignored when both overrides are provided.
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
