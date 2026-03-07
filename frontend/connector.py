import threading
from collections import deque
from typing import Dict, List, Optional

# A Message is a plain serialisable dict so the Connector stays network-transparent.
Message = Dict[str, str]  # {"role": str, "content": str}


class Connector:
    """Thread-safe communication channel between frontend and agent.

    Wraps a ``deque[Message]`` and exposes a minimal API so that any
    frontend (TUI, web, network socket ...) can be swapped in without
    touching the agent logic.

    Design for future network transparency: only plain, JSON-serialisable
    dicts are stored - no live objects.
    """

    def __init__(self) -> None:
        self._queue: deque = deque()
        self._history: List[Message] = []
        self._lock = threading.Lock()

    def send(self, role: str, content: str) -> None:
        """Enqueue a message from *role* with *content*."""
        msg: Message = {"role": role, "content": content}
        with self._lock:
            self._queue.append(msg)
            self._history.append(msg)

    def receive(self) -> Optional[Message]:
        """Dequeue and return the next pending message, or None if empty."""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def drain(self) -> List[Message]:
        """Return all pending messages as a list and clear the queue."""
        with self._lock:
            messages = list(self._queue)
            self._queue.clear()
            return messages

    def snapshot(self) -> List[Message]:
        """Return a read-only copy of the full message history."""
        with self._lock:
            return list(self._history)
