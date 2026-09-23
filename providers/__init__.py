"""Provider adapters: one class per model API, speaking core.types.

See providers/base.py for the interface and providers/errors.py for the
errors they raise.
"""

from providers.base import Provider
from providers.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderServerError,
    ProviderTimeoutError,
)

__all__ = [
    "Provider",
    "ProviderError",
    "ProviderAuthError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderConnectionError",
    "ProviderRequestError",
    "ProviderServerError",
]
