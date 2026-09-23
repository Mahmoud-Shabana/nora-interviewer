from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from pydantic import Field

from .models import StrictModel


DEFAULT_LATENCY_BUCKETS_SECONDS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)


@dataclass
class _RouteMetrics:
    method: str
    route: str
    status_class: str
    requests: int
    duration_seconds_sum: float
    duration_buckets: list[int]


class HttpMetricSeries(StrictModel):
    method: str
    route: str
    status_class: str
    requests: int = Field(ge=0)
    duration_seconds_sum: float = Field(ge=0)
    duration_buckets: dict[str, int] = Field(default_factory=dict)


class HttpMetricsSnapshot(StrictModel):
    requests_total: int = Field(default=0, ge=0)
    in_flight: int = Field(default=0, ge=0)
    series: list[HttpMetricSeries] = Field(default_factory=list)
    latency_buckets_seconds: list[float] = Field(default_factory=list)


class HttpRequestMetrics:
    """Bounded-label in-process HTTP RED metrics.

    The caller must pass route templates rather than concrete URLs. This keeps
    session ids, candidate references, and arbitrary user text out of metric
    labels.
    """

    def __init__(
        self,
        *,
        latency_buckets_seconds=DEFAULT_LATENCY_BUCKETS_SECONDS,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        buckets = tuple(
            float(value)
            for value in latency_buckets_seconds
        )
        if not buckets:
            raise ValueError(
                "latency_buckets_seconds cannot be empty"
            )
        if any(value <= 0 for value in buckets):
            raise ValueError(
                "latency buckets must be positive"
            )
        if tuple(sorted(set(buckets))) != buckets:
            raise ValueError(
                "latency buckets must be unique and increasing"
            )

        self.latency_buckets_seconds = buckets
        self.clock = clock
        self._series: dict[
            tuple[str, str, str],
            _RouteMetrics,
        ] = {}
        self._requests_total = 0
        self._in_flight = 0
        self._lock = asyncio.Lock()

    def start_timer(self) -> float:
        return self.clock()

    async def request_started(self) -> None:
        async with self._lock:
            self._in_flight += 1

    async def request_finished(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        started_at: float,
    ) -> None:
        duration = max(
            0.0,
            self.clock() - started_at,
        )
        method_label = (
            method.upper().strip() or "UNKNOWN"
        )
        route_label = (
            route.strip() or "<unmatched>"
        )
        status_class = (
            f"{status_code // 100}xx"
            if 100 <= status_code <= 599
            else "other"
        )
        key = (
            method_label,
            route_label,
            status_class,
        )

        async with self._lock:
            self._in_flight = max(
                0,
                self._in_flight - 1,
            )
            self._requests_total += 1
            current = self._series.get(key)
            if current is None:
                current = _RouteMetrics(
                    method=method_label,
                    route=route_label,
                    status_class=status_class,
                    requests=0,
                    duration_seconds_sum=0.0,
                    duration_buckets=[
                        0
                        for _ in self.latency_buckets_seconds
                    ],
                )
                self._series[key] = current

            current.requests += 1
            current.duration_seconds_sum += duration
            for index, upper_bound in enumerate(
                self.latency_buckets_seconds
            ):
                if duration <= upper_bound:
                    current.duration_buckets[index] += 1

    async def request_aborted(
        self,
        *,
        method: str,
        route: str,
        started_at: float,
    ) -> None:
        await self.request_finished(
            method=method,
            route=route,
            status_code=500,
            started_at=started_at,
        )

    async def snapshot(
        self,
    ) -> HttpMetricsSnapshot:
        async with self._lock:
            series = []
            for key in sorted(self._series):
                current = self._series[key]
                cumulative = {
                    f"{bound:g}": count
                    for bound, count in zip(
                        self.latency_buckets_seconds,
                        current.duration_buckets,
                        strict=True,
                    )
                }
                cumulative["+Inf"] = current.requests
                series.append(
                    HttpMetricSeries(
                        method=current.method,
                        route=current.route,
                        status_class=current.status_class,
                        requests=current.requests,
                        duration_seconds_sum=round(
                            current.duration_seconds_sum,
                            9,
                        ),
                        duration_buckets=cumulative,
                    )
                )

            return HttpMetricsSnapshot(
                requests_total=self._requests_total,
                in_flight=self._in_flight,
                series=series,
                latency_buckets_seconds=list(
                    self.latency_buckets_seconds
                ),
            )
