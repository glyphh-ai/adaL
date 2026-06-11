"""
Shared components for Ada Runtime.

Includes exceptions, middleware, retry utilities, and circuit breakers.
"""

from shared.exceptions import (
    AuthenticationException,
    AuthorizationException,
    EncodingException,
    GlyphNotFoundException,
    AdaRuntimeException,
    ModelIncompatibleException,
    ModelLoadException,
    ModelNotFoundException,
    NamespaceNotFoundException,
    NamespaceQuotaExceededException,
    NLQueryDisabledException,
    ValidationException,
)
from shared.retry import (
    CircuitBreaker,
    CircuitState,
    RetryConfig,
    circuit_breaker,
    retry_with_backoff,
)

__all__ = [
    # Exceptions
    "AdaRuntimeException",
    "ModelNotFoundException",
    "ModelIncompatibleException",
    "ModelLoadException",
    "NamespaceNotFoundException",
    "NamespaceQuotaExceededException",
    "AuthenticationException",
    "AuthorizationException",
    "ValidationException",
    "GlyphNotFoundException",
    "EncodingException",
    "NLQueryDisabledException",
    # Retry utilities
    "RetryConfig",
    "retry_with_backoff",
    "CircuitBreaker",
    "CircuitState",
    "circuit_breaker",
]
