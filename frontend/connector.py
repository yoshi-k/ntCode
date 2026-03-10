"""Backward-compatibility shim.

The canonical ``Connector`` implementation lives in ``utils.connector``.
This module re-exports it so that any code importing from
``frontend.connector`` continues to work without changes.

A ``DeprecationWarning`` is emitted on import so that usages show up in
tests and ``-W error`` CI runs, making it easy to track when this shim
can safely be removed.
"""

import warnings

warnings.warn(
    "Importing from 'frontend.connector' is deprecated; "
    "use 'from utils.connector import Connector' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from utils.connector import Connector, Message  # noqa: F401

__all__ = ["Connector", "Message"]
