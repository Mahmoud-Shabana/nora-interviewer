from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from typing import Callable

from pydantic import Field

from .models import StrictModel


class ProviderHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OPEN = "open"
    DISABLED = "disabled"


class ProviderCircuitOpenError(RuntimeError):
    pass


class ProviderHealthSnapshot(StrictModel):
    key: str
    provider_id: str
    state: ProviderHealthState
    consecutive_failures: int = Field(ge=0)
    total_failures: int = Field(ge=0)
    total_successes: int = Field(ge=0)
    circuit_open_seconds_remaining: float = Field(default=0.0, ge=0.0)
    last_error_type: str | None = None
    last_error: str | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None


class _ProviderHealthRecord:
    def __init__(
        self,
        *,
        key: str,
        provider_id: str,
        disabled: bool,
    ) -> None:
        self.key = key
        self.provider_id = provider_id
        self.disabled = disabled
        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_successes = 0
        self.open_until = 0.0
        self.last_error_type: str | None = None
        self.last_error: str | None = None
        self.last_failure_at: datetime | None = None
        self.last_success_at: datetime | None = None


class ProviderHealthRegistry:
    """Runtime health and circuit-breaker state for external providers."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 20.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")

        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self._records: dict[str, _ProviderHealthRecord] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        key: str,
        provider_id: str,
        disabled: bool = False,
    ) -> None:
        async with self._lock:
            self._records.setdefault(
                key,
                _ProviderHealthRecord(
                    key=key,
                    provider_id=provider_id,
                    disabled=disabled,
                ),
            )

    async def before_call(self, key: str) -> None:
        async with self._lock:
            record = self._record(key)
            if record.disabled:
                return

            now = self.clock()
            if record.open_until <= now:
                record.open_until = 0.0
                return

            remaining = max(0.0, record.open_until - now)
            raise ProviderCircuitOpenError(
                f"provider circuit {key!r} is open for "
                f"{remaining:.2f} more seconds"
            )

    async def record_success(self, key: str) -> None:
        async with self._lock:
            record = self._record(key)
            record.total_successes += 1
            record.consecutive_failures = 0
            record.open_until = 0.0
            record.last_error_type = None
            record.last_error = None
            record.last_success_at = datetime.now(timezone.utc)

    async def record_failure(
        self,
        key: str,
        exc: BaseException,
    ) -> None:
        async with self._lock:
            record = self._record(key)
            if record.disabled:
                return

            record.total_failures += 1
            record.consecutive_failures += 1
            record.last_error_type = type(exc).__name__
            record.last_error = str(exc)[:1000]
            record.last_failure_at = datetime.now(timezone.utc)

            if (
                record.consecutive_failures
                >= self.failure_threshold
            ):
                record.open_until = (
                    self.clock() + self.cooldown_seconds
                )

    async def snapshot(
        self,
        key: str,
    ) -> ProviderHealthSnapshot:
        async with self._lock:
            return self._snapshot(self._record(key))

    async def snapshots(
        self,
    ) -> list[ProviderHealthSnapshot]:
        async with self._lock:
            return [
                self._snapshot(record)
                for _, record in sorted(
                    self._records.items()
                )
            ]

    def _snapshot(
        self,
        record: _ProviderHealthRecord,
    ) -> ProviderHealthSnapshot:
        now = self.clock()
        remaining = max(
            0.0,
            record.open_until - now,
        )

        if record.disabled:
            state = ProviderHealthState.DISABLED
        elif remaining > 0:
            state = ProviderHealthState.OPEN
        elif record.consecutive_failures > 0:
            state = ProviderHealthState.DEGRADED
        else:
            state = ProviderHealthState.HEALTHY

        return ProviderHealthSnapshot(
            key=record.key,
            provider_id=record.provider_id,
            state=state,
            consecutive_failures=record.consecutive_failures,
            total_failures=record.total_failures,
            total_successes=record.total_successes,
            circuit_open_seconds_remaining=round(
                remaining,
                3,
            ),
            last_error_type=record.last_error_type,
            last_error=record.last_error,
            last_failure_at=record.last_failure_at,
            last_success_at=record.last_success_at,
        )

    def _record(
        self,
        key: str,
    ) -> _ProviderHealthRecord:
        try:
            return self._records[key]
        except KeyError as exc:
            raise KeyError(
                f"provider health key {key!r} is not registered"
            ) from exc
