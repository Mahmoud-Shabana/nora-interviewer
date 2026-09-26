from __future__ import annotations

from enum import Enum
from time import monotonic
from typing import Callable

from .models import StrictModel


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderCircuitOpenError(RuntimeError):
    pass


class ProviderResilienceSnapshot(StrictModel):
    provider_id: str
    state: CircuitState
    consecutive_failures: int
    total_failures: int
    total_successes: int
    open_seconds_remaining: float


class CircuitBreaker:
    def __init__(
        self,
        *,
        provider_id: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 20.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(
                "failure_threshold must be positive"
            )
        if cooldown_seconds <= 0:
            raise ValueError(
                "cooldown_seconds must be positive"
            )
        self.provider_id = provider_id
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_successes = 0
        self.opened_at: float | None = None

    def before_call(self) -> None:
        if self.state is not CircuitState.OPEN:
            return
        assert self.opened_at is not None
        elapsed = self.clock() - self.opened_at
        if elapsed >= self.cooldown_seconds:
            self.state = CircuitState.HALF_OPEN
            return
        raise ProviderCircuitOpenError(
            f"Provider circuit is open: {self.provider_id}"
        )

    def record_success(self) -> None:
        self.total_successes += 1
        self.consecutive_failures = 0
        self.state = CircuitState.CLOSED
        self.opened_at = None

    def record_failure(self) -> None:
        self.total_failures += 1
        self.consecutive_failures += 1
        if (
            self.state is CircuitState.HALF_OPEN
            or self.consecutive_failures
            >= self.failure_threshold
        ):
            self.state = CircuitState.OPEN
            self.opened_at = self.clock()

    def snapshot(self) -> ProviderResilienceSnapshot:
        remaining = 0.0
        if (
            self.state is CircuitState.OPEN
            and self.opened_at is not None
        ):
            remaining = max(
                0.0,
                self.cooldown_seconds
                - (
                    self.clock()
                    - self.opened_at
                ),
            )
        return ProviderResilienceSnapshot(
            provider_id=self.provider_id,
            state=self.state,
            consecutive_failures=self.consecutive_failures,
            total_failures=self.total_failures,
            total_successes=self.total_successes,
            open_seconds_remaining=round(
                remaining,
                3,
            ),
        )


def retryable_http_status(
    status_code: int,
) -> bool:
    return (
        status_code in {
            408,
            409,
            425,
            429,
        }
        or status_code >= 500
    )
