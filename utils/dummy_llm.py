"""Dummy provider for testing and offline development.

Replays responses from a plain-text file instead of calling a real API.
Each non-empty, non-comment line in the replay file is one complete model
reply.  When the file is exhausted the reader wraps back to the first line
so callers never run out of answers.

Lines are read in the ``ntcode`` text syntax, so a line such as
``tool: read_file({"filename": "a.py"})`` comes back as a native
:class:`core.types.ToolCall`, and the agent loop runs the tool exactly as it
would for a real provider.

Quick usage
-----------
    from utils.dummy_llm import DummyProvider

    provider = DummyProvider("tests/dummy_responses.txt")
    turn = provider.complete("system", [], [])
    print(turn.message.text)   # first non-empty line from the file

Replay-file format
------------------
* One response per line.
* Lines that are blank or start with ``#`` are skipped.
* The file is read once at construction time; call ``reload()`` to re-read.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from core.types import AssistantTurn, Message, ToolSpec
from providers.base import Provider
from providers.text_tools import get_dialect


class DummyProvider(Provider):
    """File-replay provider for tests and offline development.

    Parameters
    ----------
    replay_file:
        Path to a plain-text file whose non-empty, non-comment lines are
        returned as successive replies.  Cycles from the beginning once all
        lines have been consumed.
    """

    name = "dummy"
    model = "dummy"

    def __init__(self, replay_file: str | Path) -> None:
        self._path = Path(replay_file)
        self._responses: List[str] = self._load()
        self._index: int = 0
        self._dialect = get_dialect("ntcode")

    def _load(self) -> List[str]:
        """Read the replay file and return all usable lines."""
        if not self._path.exists():
            raise FileNotFoundError(f"DummyProvider: replay file not found: {self._path}")
        lines = [
            line.strip()
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not lines:
            raise ValueError(f"DummyProvider: replay file has no usable lines: {self._path}")
        return lines

    def _next_response(self) -> str:
        """Return the next pre-recorded response, cycling as needed."""
        text = self._responses[self._index % len(self._responses)]
        self._index += 1
        return text

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AssistantTurn:
        """Return the next recorded reply; the arguments are ignored."""
        prose, calls = self._dialect.parse(self._next_response())
        return AssistantTurn(
            Message.assistant(prose, calls),
            stop_reason="tool_use" if calls else "end_turn",
        )

    # ------------------------------------------------------------------
    # Extras: helpers useful in tests
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Restart the replay from the first line."""
        self._index = 0

    def reload(self, replay_file: Optional[str | Path] = None) -> None:
        """Re-read the replay file from disk, optionally from a new path."""
        if replay_file is not None:
            self._path = Path(replay_file)
        self._responses = self._load()
        self._index = 0

    @property
    def response_count(self) -> int:
        """Number of unique responses available in the replay file."""
        return len(self._responses)

    @property
    def current_index(self) -> int:
        """Zero-based index of the *next* response that will be returned."""
        return self._index % len(self._responses)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DummyProvider(file={self._path!r}, "
            f"index={self._index % len(self._responses)}/{len(self._responses)})"
        )
