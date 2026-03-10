"""Backward-compatibility shim.

The canonical ``Connector`` implementation lives in ``utils.connector``.
This module re-exports it so that any code importing from
``frontend.connector`` continues to work without changes.
"""

from utils.connector import Connector, Message  # noqa: F401

__all__ = ["Connector", "Message"]
