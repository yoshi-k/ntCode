"""Typed errors raised by provider adapters.

Adapters translate their SDK's or HTTP library's exceptions into these, so
callers can tell a bad key from a rate limit from a server outage without
knowing which provider is active, and never have to recognise an error by
the text of a reply.  ``user_message()`` gives the text to show the user.
"""

from __future__ import annotations

from typing import Optional


class ProviderError(Exception):
    """Base class: the provider call failed."""

    hint = "The request to the model provider failed."

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retry_after = retry_after

    def user_message(self) -> str:
        where = f" ({self.provider})" if self.provider else ""
        return f"{self.hint}{where}\nDetail: {self}"


class ProviderAuthError(ProviderError):
    """401 / 403: the credentials are missing, wrong, or lack permission."""

    hint = "Authentication with the model provider failed. Check the API key."


class ProviderRateLimitError(ProviderError):
    """429: too many requests or tokens; retrying later may succeed."""

    hint = "The model provider is rate limiting requests. Wait a moment and try again."


class ProviderTimeoutError(ProviderError):
    """The request timed out."""

    hint = "The request to the model provider timed out."


class ProviderConnectionError(ProviderError):
    """The provider could not be reached."""

    hint = "Could not connect to the model provider. Check the network and the server URL."


class ProviderRequestError(ProviderError):
    """400 / 404 / 413 / 422: the request itself was rejected; retrying will not help."""

    hint = "The model provider rejected the request."


class ProviderServerError(ProviderError):
    """5xx or overloaded: a problem on the provider's side."""

    hint = "The model provider had a server error. Try again later."
