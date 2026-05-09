"""Connector – thread-safe message channel between frontend and agent.

This module contains **no** UI code.  It communicates exclusively through a
:class:`~utils.connector.Connector` instance:

* Reads user messages via :meth:`~utils.connector.receive_user_blocking`.
* Writes assistant responses via :meth:`~utils.connector.send_assistant`.

The TUI (or any other frontend) owns the ``Connector`` and starts
:func:`run_agent` in a background thread::

    from utils.connector import Connector
    from utils.agent import run_agent

    connector = Connector()
    thread = threading.Thread(target=run_agent, args=(connector,), daemon=True)
    thread.start()
"""

import threading
from collections import deque
from typing import Dict, List, Optional

# A Message is a plain, JSON-serialisable dict.
Message = Dict[str, str]  # {"role": str, "content": str}

# An ApprovalRequest is sent by the agent to the TUI when VERBOSE_MODE is on.
# {"tool_name": str, "args": dict}
ApprovalRequest = Dict[str, object]

# An ApprovalResponse is sent by the TUI back to the agent.
# {"approved": bool}
ApprovalResponse = Dict[str, bool]


class Connector:
    """Thread-safe two-directional message channel.

    Two separate queues are maintained:

    * ``_user_queue``  – messages sent by the frontend for the agent.
    * ``_agent_queue`` – messages sent by the agent for the frontend.

    A full history of every message (both directions) is kept in
    ``_history`` for logging / replay purposes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        self._user_queue: deque = deque()     # frontend -> agent  (user messages)
        self._agent_queue: deque = deque()    # agent    -> frontend (assistant messages)
        self._approval_req_queue: deque = deque()  # agent -> frontend (tool approval requests)
        self._approval_resp_queue: deque = deque() # frontend -> agent (tool approval responses)

        self._user_event = threading.Event()
        self._agent_event = threading.Event()
        self._approval_req_event = threading.Event()
        self._approval_resp_event = threading.Event()

        self._history: List[Message] = []
        self._current_role_name: str = "default"

        # Set to True by shutdown() to unblock all blocking receivers
        self._shutdown = False

    # ------------------------------------------------------------------
    # Low-level send (routes by role)
    # ------------------------------------------------------------------

    def send(self, role: str, content: str) -> None:
        """Enqueue a message; routes to the correct queue based on *role*.

        ``"user"`` roles go to the agent queue (frontend -> agent).
        All other roles go to the frontend queue (agent -> frontend).
        """
        msg: Message = {"role": role, "content": content}
        with self._lock:
            self._history.append(msg)
            if role == "user":
                self._user_queue.append(msg)
                self._user_event.set()
            else:
                self._agent_queue.append(msg)
                self._agent_event.set()

    # ------------------------------------------------------------------
    # Role Tracking
    # ------------------------------------------------------------------

    def set_role_name(self, name: str) -> None:
        """Update the current active role name (used by TUI for prompt display)."""
        with self._lock:
            self._current_role_name = name

    def get_role_name(self) -> str:
        """Return the current active role name."""
        with self._lock:
            return self._current_role_name

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def send_user(self, content: str) -> None:
        """Frontend -> agent: submit a user turn."""
        self.send("user", content)

    def send_assistant(self, content: str) -> None:
        """Agent -> frontend: publish the assistant reply."""
        self.send("assistant", content)

    # ------------------------------------------------------------------
    # Non-blocking receive
    # ------------------------------------------------------------------

    def receive(self) -> Optional[Message]:
        """Dequeue the next agent-queue message without blocking, or ``None``."""
        with self._lock:
            if self._agent_queue:
                msg = self._agent_queue.popleft()
                if not self._agent_queue:
                    self._agent_event.clear()
                return msg
            return None

    def receive_user(self) -> Optional[Message]:
        """Dequeue the next user-queue message without blocking, or ``None``."""
        with self._lock:
            if self._user_queue:
                msg = self._user_queue.popleft()
                if not self._user_queue:
                    self._user_event.clear()
                return msg
            return None

    # ------------------------------------------------------------------
    # Blocking receive (preferred)
    # ------------------------------------------------------------------

    def receive_assistant_blocking(self, timeout: Optional[float] = None) -> Optional[Message]:
        """Block until an assistant message is available, then return it.

        Returns ``None`` if *timeout* expires or :meth:`shutdown` is called.
        """
        while not self._shutdown:
            self._agent_event.wait(timeout=timeout)
            with self._lock:
                if self._agent_queue:
                    msg = self._agent_queue.popleft()
                    if not self._agent_queue:
                        self._agent_event.clear()
                    return msg
            if timeout is not None:
                return None
        return None

    def receive_user_blocking(self, timeout: Optional[float] = None) -> Optional[Message]:
        """Block until a user message is available, then return it.

        Returns ``None`` if *timeout* expires or :meth:`shutdown` is called.
        """
        while not self._shutdown:
            self._user_event.wait(timeout=timeout)
            with self._lock:
                if self._user_queue:
                    msg = self._user_queue.popleft()
                    if not self._user_queue:
                        self._user_event.clear()
                    return msg
            if timeout is not None:
                return None
        return None

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def drain(self) -> List[Message]:
        """Return all pending agent-queue messages and clear the queue."""
        with self._lock:
            messages = list(self._agent_queue)
            self._agent_queue.clear()
            self._agent_event.clear()
            return messages

    def snapshot(self) -> List[Message]:
        """Return a read-only copy of the full message history (both directions)."""
        with self._lock:
            return list(self._history)

    # ------------------------------------------------------------------
    # Tool approval channel (used only when VERBOSE_MODE is on)
    # ------------------------------------------------------------------

    def request_approval(self, tool_name: str, args: dict) -> None:
        """Agent -> frontend: ask the user to approve a tool execution."""
        req: ApprovalRequest = {"tool_name": tool_name, "args": args}
        with self._lock:
            self._approval_req_queue.append(req)
            self._approval_req_event.set()

    def receive_approval_request_blocking(
        self, timeout: Optional[float] = None
    ) -> Optional[ApprovalRequest]:
        """Frontend: block until an approval request arrives, then return it."""
        while not self._shutdown:
            self._approval_req_event.wait(timeout=timeout)
            with self._lock:
                if self._approval_req_queue:
                    req = self._approval_req_queue.popleft()
                    if not self._approval_req_queue:
                        self._approval_req_event.clear()
                    return req
            if timeout is not None:
                return None
        return None

    def send_approval_response(self, approved: bool) -> None:
        """Frontend -> agent: convey the user's yes/no decision."""
        resp: ApprovalResponse = {"approved": approved}
        with self._lock:
            self._approval_resp_queue.append(resp)
            self._approval_resp_event.set()

    def receive_approval_response_blocking(
        self, timeout: Optional[float] = None
    ) -> Optional[ApprovalResponse]:
        """Agent: block until the frontend sends the approval decision."""
        while not self._shutdown:
            self._approval_resp_event.wait(timeout=timeout)
            with self._lock:
                if self._approval_resp_queue:
                    resp = self._approval_resp_queue.popleft()
                    if not self._approval_resp_queue:
                        self._approval_resp_event.clear()
                    return resp
            if timeout is not None:
                return None
        return None

    # ------------------------------------------------------------------
    # Control messages (save / load / reset conversation)
    # ------------------------------------------------------------------

    def send_control(self, command: str, payload: object = None) -> None:
        """Frontend -> agent: send a control command.

        Supported commands: ``"save"``, ``"load"``, ``"reset"``.
        *payload* carries command-specific data (e.g. a file path for save/load).
        The command is delivered via the user queue with role ``"control"``.
        """
        msg: Message = {"role": "control", "command": command, "payload": payload or ""}
        with self._lock:
            self._history.append(msg)
            self._user_queue.append(msg)
            self._user_event.set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Signal all blocking receivers to wake up and return ``None``."""
        self._shutdown = True
        self._user_event.set()
        self._agent_event.set()
        self._approval_req_event.set()
        self._approval_resp_event.set()
