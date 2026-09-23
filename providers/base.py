"""The provider interface.

A provider sends a provider-neutral conversation (:mod:`core.types`) to one
model API and returns the reply in the same types.  Wire formats never leave
the adapter::

    turn = provider.complete(system, messages, tools)
    turn.message.text        # reply text
    turn.message.tool_calls  # native tool calls, with the ids to answer

Failures raise :class:`providers.errors.ProviderError` subclasses; a
provider never returns an error as if it were the model's reply.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from core.types import AssistantTurn, Message, ToolSpec


class Provider(ABC):
    """One model endpoint."""

    #: Short provider name, e.g. "anthropic"; used in logs and errors.
    name: str = ""
    #: Model identifier sent to the API.
    model: str = ""

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AssistantTurn:
        """Send the conversation and return the model's reply.

        Args:
            system:   System prompt.
            messages: The conversation, starting with a user message.  Tool
                      results must answer the tool calls of the preceding
                      assistant message.
            tools:    Tools the model may call; empty for none.
        """

    def close(self) -> None:
        """Release network resources.  Safe to call more than once."""
