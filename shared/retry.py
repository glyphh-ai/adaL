"""
Retry and Circuit Breaker utilities for Ada Runtime.

Provides decorators and classes for handling transient failures
with exponential backoff and circuit breaker patterns.
"""

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 5
    base_delay_ms: int = 100
    max_delay_ms: int = 1600
    exponential_base: float = 2.0
    retryable_exceptions: List[Type[Exception]] = field(
        default_factory=lambda: [Exception]
    )
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for attempt (in seconds)."""
        delay_ms = min(
            self.base_delay_ms * (self.exponential_base ** attempt),
            self.max_delay_ms
        )
        return delay_ms / 1000.0


def retry_with_backoff(
    max_retries: int = 5,
    base_delay_ms: int = 100,
    max_delay_ms: int = 1600,
    retryable_exceptions: Optional[List[Type[Exception]]] = None,
):
    """
    Decorator for retrying async functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay_ms: Initial delay in milliseconds
        max_delay_ms: Maximum delay in milliseconds
        retryable_exceptions: List of exception types to retry on
        
    Example:
        @retry_with_backoff(max_retries=3, base_delay_ms=100)
        async def fetch_data():
            ...
    """
    if retryable_exceptions is None:
        retryable_exceptions = [Exception]
    
    config = RetryConfig(
        max_retries=max_retries,
        base_delay_ms=base_delay_ms,
        max_delay_ms=max_delay_ms,
        retryable_exceptions=retryable_exceptions,
    )
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except tuple(config.retryable_exceptions) as e:
                    last_exception = e
                    
                    if attempt < config.max_retries:
                        delay = config.get_delay(attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{config.max_retries} for {func.__name__} "
                            f"after {delay:.3f}s: {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_retries} retries exhausted for {func.__name__}: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker for protecting against cascading failures.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests rejected immediately
    - HALF_OPEN: Testing if service recovered
    
    Transitions:
    - CLOSED -> OPEN: After failure_threshold consecutive failures
    - OPEN -> HALF_OPEN: After recovery_timeout seconds
    - HALF_OPEN -> CLOSED: After success_threshold consecutive successes
    - HALF_OPEN -> OPEN: On any failure
    
    Example:
        breaker = CircuitBreaker(name="platform_api")
        
        async def call_api():
            if not breaker.allow_request():
                raise ServiceUnavailableError("Circuit open")
            
            try:
                result = await api.call()
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure()
                raise
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Name for logging
            failure_threshold: Failures before opening circuit
            success_threshold: Successes before closing circuit
            recovery_timeout: Seconds before trying half-open
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.recovery_timeout = recovery_timeout
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        # Check if we should transition from OPEN to HALF_OPEN
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info(f"Circuit {self.name} transitioning to HALF_OPEN")
        
        return self._state
    
    def allow_request(self) -> bool:
        """Check if a request should be allowed."""
        state = self.state  # This may trigger state transition
        
        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.HALF_OPEN:
            return True  # Allow test requests
        else:  # OPEN
            return False
    
    def record_success(self) -> None:
        """Record a successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info(f"Circuit {self.name} CLOSED after recovery")
        else:
            self._failure_count = 0
    
    def record_failure(self) -> None:
        """Record a failed request."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open reopens the circuit
            self._state = CircuitState.OPEN
            logger.warning(f"Circuit {self.name} OPEN (failed in half-open)")
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"Circuit {self.name} OPEN after {self._failure_count} failures"
                )
    
    def reset(self) -> None:
        """Reset circuit to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        logger.info(f"Circuit {self.name} manually reset")
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
        }


def circuit_breaker(breaker: CircuitBreaker):
    """
    Decorator for applying circuit breaker to async functions.
    
    Args:
        breaker: CircuitBreaker instance to use
        
    Example:
        api_breaker = CircuitBreaker(name="external_api")
        
        @circuit_breaker(api_breaker)
        async def call_external_api():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            if not breaker.allow_request():
                raise Exception(f"Circuit {breaker.name} is open")
            
            try:
                result = await func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception:
                breaker.record_failure()
                raise
        
        return wrapper
    return decorator
