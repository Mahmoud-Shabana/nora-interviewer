from __future__ import annotations

from enum import Enum
from time import monotonic
from collections.abc import Mapping
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
    component: str | None = None
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


def collect_provider_resilience(
    components: Mapping[str, object],
) -> list[ProviderResilienceSnapshot]:
    snapshots: list[
        ProviderResilienceSnapshot
    ] = []
    seen: set[int] = set()

    def visit(
        value: object,
        path: str,
    ) -> None:
        if value is None:
            return
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)

        snapshot_fn = getattr(
            value,
            "resilience_snapshot",
            None,
        )
        if callable(snapshot_fn):
            snapshot = snapshot_fn()
            if isinstance(
                snapshot,
                ProviderResilienceSnapshot,
            ):
                snapshots.append(
                    snapshot.model_copy(
                        update={
                            "component": path
                        }
                    )
                )

        provider = getattr(
            value,
            "provider",
            None,
        )
        if provider is not None:
            visit(
                provider,
                path + ".provider",
            )

        primary = getattr(
            value,
            "primary",
            None,
        )
        if primary is not None:
            visit(
                primary,
                path + ".primary",
            )

        runner = getattr(
            value,
            "runner",
            None,
        )
        if runner is not None:
            visit(
                runner,
                path + ".runner",
            )

        judges = getattr(
            value,
            "judges",
            None,
        )
        if isinstance(
            judges,
            (list, tuple),
        ):
            for index, judge in enumerate(
                judges
            ):
                visit(
                    judge,
                    f"{path}.judges[{index}]",
                )

    for name, component in components.items():
        visit(
            component,
            name,
        )

    return snapshots
