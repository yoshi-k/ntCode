"""Dummy LLM provider for testing and offline development.

Replays responses from a plain-text file instead of calling a real API.
Each non-empty, non-comment line in the replay file is returned as one
complete LLM response.  When the file is exhausted the reader wraps back
to the first line so callers never run out of answers.

The class inherits from ``LLM`` and matches its exact ``call()`` signature
(``system``, ``messages`` → ``str``), so it can be passed wherever an
``LLM`` instance is expected — including ``execute_llm_call()``.

Quick usage
-----------
    from utils.dummy_llm import DummyLLM

    llm = DummyLLM("tests/fixtures/dummy_responses.txt")
    reply = llm.call(system="s", messages=[])
    print(reply)   # first non-empty line from the file

Replay-file format
------------------
* One response per line.
* Lines that are blank or start with ``#`` are skipped.
* The file is read once at construction time; call ``reload()`` to re-read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from utils.llm import LLM


class DummyLLM(LLM):
    """File-replay LLM provider for tests and offline development.

    Parameters
    ----------
    replay_file:
        Path to a plain-text file whose non-empty, non-comment lines are
        returned as successive LLM responses.  Cycles from the beginning
        once all lines have been consumed.
    """

    def __init__(self, replay_file: str | Path) -> None:
        self._path = Path(replay_file)
        self._responses: List[str] = self._load()
        self._index: int = 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> List[str]:
        """Read the replay file and return all usable lines."""
        if not self._path.exists():
            raise FileNotFoundError(
                f"DummyLLM: replay file not found: {self._path}"
            )
        lines = [
            line.strip()
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not lines:
            raise ValueError(
                f"DummyLLM: replay file has no usable lines: {self._path}"
            )
        return lines

    def _next_response(self) -> str:
        """Return the next pre-recorded response, cycling as needed."""
        text = self._responses[self._index % len(self._responses)]
        self._index += 1
        return text

    # ------------------------------------------------------------------
    # LLM interface  (matches LLM.call exactly)
    # ------------------------------------------------------------------

    def call(self, system: str, messages: List[Dict[str, str]]) -> str:
        """Return the next pre-recorded response.

        The *system* and *messages* arguments are accepted for interface
        compatibility but are not used — the reply always comes from the
        replay file.

        :param system: System prompt (ignored).
        :param messages: Conversation history (ignored).
        :return: Next response line from the replay file.
        """
        return self._next_response()

    # ------------------------------------------------------------------
    # Extras: helpers useful in tests
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Restart the replay from the first line."""
        self._index = 0

    def reload(self, replay_file: Optional[str | Path] = None) -> None:
        """Re-read the replay file from disk.

        Parameters
        ----------
        replay_file:
            New path to use.  If *None*, the original path is re-read.
        """
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
            f"DummyLLM(file={self._path!r}, "
            f"index={self._index % len(self._responses)}/{len(self._responses)})"
        )
