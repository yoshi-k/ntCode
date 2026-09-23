"""Active provider, session header and conversation state for ntCode.

This module contains:

* SessionHeader         - the system prompt plus the documentation files.
* ConversationManager   - task-scoped history of core.types messages, with
                          pair-safe pruning, save/load and save points.
* llm                   - the active providers.base.Provider, always built
                          from the configuration (rebuild_provider,
                          switch_provider).

::

    from utils.llm import SessionHeader, ConversationManager
"""

import copy
from pathlib import Path
from typing import Any

from utils import config as cfg
from utils.config import API_MAX_TOKENS, logger
from utils.rate_limiter import _rate_limiter
from core.types import Message, TextBlock, message_from_dict, message_to_dict
from providers.base import Provider


# ===========================================================================
# SessionHeader
# ===========================================================================

class SessionHeader:
    """The system prompt plus the core documentation files.

    :meth:`system_with_docs` is what the agent sends as the system prompt.
    Providers cache it (Anthropic puts a cache breakpoint on it), so it
    should stay byte-identical from one request to the next.

    Attributes:
        system_prompt: Raw system-prompt string.
        doc_paths:     Ordered list of documentation file paths to append.
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
            doc_paths:     Documentation files to append.  Defaults to the
                           three canonical ntCode docs when None.
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

    def system_with_docs(self) -> str:
        """Return the system prompt with the documentation files appended.

        A file whose text the system prompt already contains (inlined via
        ``{{FILE:...}}``) is not appended a second time.
        """
        parts = [self.system_prompt]
        for block in self._doc_blocks:
            body = block["text"].split("\n", 1)[1] if "\n" in block["text"] else ""
            if body.strip() and body.strip() not in self.system_prompt:
                parts.append(block["text"])
        return "\n\n".join(parts)


# ===========================================================================
# ConversationManager
# ===========================================================================


class ConversationManager:
    """The conversation for the current task, as core.types messages.

    The session header (system prompt and docs) is kept separately and never
    discarded; the task context is reset by start_task().

    Typical usage::

        from tools.registry import get_full_system_prompt
        from utils.llm import SessionHeader, ConversationManager

        mgr = ConversationManager(SessionHeader(get_full_system_prompt()))
        mgr.start_task("Refactor the login module")
        turn = provider.complete(
            mgr.session_header.system_with_docs(), mgr.messages(), tools
        )
        mgr.add_message(turn.message)

    Attributes:
        session_header: The SessionHeader with the system prompt and docs.
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
# Active provider
# ===========================================================================


def _build_anthropic(model: str) -> "Provider":
    """Build the native-tool-use Claude adapter."""
    from providers.anthropic import AnthropicProvider
    from utils.config_manager import config

    return AnthropicProvider(
        model,
        api_key=config.get("ANTHROPIC_API_KEY") or None,
        max_tokens=API_MAX_TOKENS,
        timeout=cfg.API_TIMEOUT,
        rate_limiter=_rate_limiter,
    )


def _build_openai(model: str, base_url: str) -> "Provider":
    """Build a client for an OpenAI-compatible endpoint.

    Native tool calling (providers.openai_chat.OpenAIChatProvider) unless
    CALLING_CONVENTION names a text format; then the same client is wrapped
    in providers.text_tools.TextToolsProvider with that dialect.
    """
    from providers.openai_chat import OpenAIChatProvider

    convention = (cfg.CALLING_CONVENTION or "").lower().strip()
    provider: Provider = OpenAIChatProvider(
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
    mode = "native"
    if convention not in ("", "auto", "native"):
        from providers.text_tools import TextToolsProvider, get_dialect

        provider = TextToolsProvider(provider, get_dialect(convention))
        mode = f"text/{convention}"
    logger.info(f"[LLM] Provider: openai-compatible ({mode} tools)  url={base_url}  model={model}")
    return provider


def _build_llm() -> "Provider":
    """Build the provider described by the current configuration.

    The configuration (utils.config, edited through utils.config_manager) is
    the single source of truth: /provider, /config set and roles change it
    and then call rebuild_provider().

    'anthropic' (default): providers.anthropic.AnthropicProvider with
              DEFAULT_MODEL (NTCODE_MODEL).
    'openai': an OpenAI-compatible endpoint (llama.cpp, Ollama, ...) with
              OPENAI_MODEL at OPENAI_BASE_URL, see _build_openai.
    """
    if cfg.LLM_PROVIDER == "openai":
        return _build_openai(cfg.OPENAI_MODEL, cfg.OPENAI_BASE_URL)
    logger.info(f"[LLM] Provider: anthropic  model={cfg.DEFAULT_MODEL}")
    return _build_anthropic(cfg.DEFAULT_MODEL)


# Active provider, built from the configuration.  Change it through
# switch_provider() or a configuration change plus rebuild_provider().
llm: Provider = _build_llm()

#: Configuration keys that shape the provider; changing one needs rebuild_provider().
PROVIDER_KEYS = frozenset({
    "LLM_PROVIDER", "DEFAULT_MODEL", "ANTHROPIC_API_KEY", "API_TIMEOUT",
    "CALLING_CONVENTION", "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_API_KEY",
    "OPENAI_MAX_TOKENS", "OPENAI_TEMPERATURE", "OPENAI_TIMEOUT", "OPENAI_MAX_RETRIES",
})


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


_DEFAULT_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
}


def rebuild_provider() -> str:
    """Replace the active provider with one built from the current configuration.

    Returns a description of the new provider.  Raises if it cannot be built
    (the previous provider then stays active).
    """
    global llm

    new_llm = _build_llm()
    old, llm = llm, new_llm
    # Close the previous provider's connection pool if it supports it.
    if old is not new_llm and callable(getattr(old, "close", None)):
        try:
            old.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LLM] Error closing previous provider: %s", exc)
    desc = current_provider_name()
    logger.info("[LLM] Provider is now: %s", desc)
    return desc


def switch_provider(spec: str) -> str:
    """Switch provider (and optionally model) by updating the configuration.

    spec: bare alias ('openai', 'anthropic', 'ollama' ...) or alias/model
    ('openai/gpt-4o', 'ollama/llama3', 'anthropic/claude-opus-4-5').

    'anthropic' sets LLM_PROVIDER and, with a model, DEFAULT_MODEL.  The
    OpenAI-compatible aliases set LLM_PROVIDER=openai, OPENAI_MODEL when a
    model is given, and OPENAI_BASE_URL: 'ollama', 'lmstudio' and 'groq'
    use their standard URL; 'openai' keeps the configured OPENAI_BASE_URL
    (e.g. a llama.cpp server) or falls back to api.openai.com.

    Returns a status string.  Raises ValueError for unknown aliases.
    """
    from utils.config_manager import config

    if "/" in spec:
        alias, model_override = spec.split("/", 1)
        model_override = model_override.strip() or None
    else:
        alias, model_override = spec.strip(), None

    alias = alias.lower().strip()
    if alias not in _PROVIDER_ALIASES:
        known = ", ".join(sorted(_PROVIDER_ALIASES))
        raise ValueError(f"Unknown provider alias '{alias}'. Known: {known}")
    canonical = _PROVIDER_ALIASES[alias]

    changes: dict[str, str] = {"LLM_PROVIDER": canonical}
    if canonical == "anthropic":
        if model_override:
            changes["DEFAULT_MODEL"] = model_override
    else:
        if alias == "openai":
            changes["OPENAI_BASE_URL"] = cfg.OPENAI_BASE_URL or _DEFAULT_URLS["openai"]
        else:
            changes["OPENAI_BASE_URL"] = _DEFAULT_URLS[alias]
        if model_override:
            changes["OPENAI_MODEL"] = model_override

    previous = {key: config.get(key) for key in changes}
    for key, value in changes.items():
        config.set(key, value)
    try:
        desc = rebuild_provider()
    except Exception:
        for key, value in previous.items():
            config.set(key, value)
        raise
    return f"\u2705 Switched to {desc}"


def system_prompt_for_display() -> str:
    """The system prompt as the active provider sends it (for /prompt).

    The prompt plus the documentation files, and for a text-dialect provider
    also the tool descriptions it appends.  Native providers send the tool
    definitions in the request instead, so they do not appear here.
    """
    from core.tool_schema import tool_specs
    from providers.text_tools import TextToolsProvider
    from tools.registry import TOOL_REGISTRY, get_full_system_prompt
    from utils.roles import get_active_role

    system = SessionHeader(get_full_system_prompt()).system_with_docs()
    if isinstance(llm, TextToolsProvider):
        role = get_active_role()
        specs = tool_specs(TOOL_REGISTRY, role.tools if role and role.tools else None)
        system += "\n\n" + llm.dialect.render_tools(specs)
    return system
