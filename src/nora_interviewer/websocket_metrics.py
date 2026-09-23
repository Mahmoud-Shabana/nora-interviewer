from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from pydantic import Field

from .models import StrictModel


_ALLOWED_CHANNELS = {
    "interview",
    "audio",
    "tts",
    "other",
}


def classify_websocket_channel(
    path: str,
) -> str:
    if path.startswith("/v1/ws/interviews/"):
        return "interview"
    if path.startswith("/v1/ws/audio/"):
        return "audio"
    if path.startswith("/v1/ws/tts/"):
        return "tts"
    return "other"


@dataclass
class _ChannelMetrics:
    active: int = 0
    opened_total: int = 0
    closed_total: int = 0
    errors_total: int = 0
    duration_seconds_sum: float = 0.0


class WebSocketChannelSnapshot(StrictModel):
    channel: str
    active: int = Field(ge=0)
    opened_total: int = Field(ge=0)
    closed_total: int = Field(ge=0)
    errors_total: int = Field(ge=0)
    duration_seconds_sum: float = Field(ge=0)


class WebSocketMetricsSnapshot(StrictModel):
    channels: list[WebSocketChannelSnapshot] = Field(
        default_factory=list
    )


class WebSocketMetrics:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.clock = clock
        self._channels = {
            channel: _ChannelMetrics()
            for channel in sorted(_ALLOWED_CHANNELS)
        }
        self._lock = asyncio.Lock()

    async def opened(
        self,
        channel: str,
    ) -> float:
        channel = self._normalize(channel)
        started_at = self.clock()
        async with self._lock:
            current = self._channels[channel]
            current.active += 1
            current.opened_total += 1
        return started_at

    async def closed(
        self,
        channel: str,
        *,
        started_at: float,
        error: bool = False,
    ) -> None:
        channel = self._normalize(channel)
        duration = max(
            0.0,
            self.clock() - started_at,
        )
        async with self._lock:
            current = self._channels[channel]
            current.active = max(
                0,
                current.active - 1,
            )
            current.closed_total += 1
            current.duration_seconds_sum += duration
            if error:
                current.errors_total += 1

    async def snapshot(
        self,
    ) -> WebSocketMetricsSnapshot:
        async with self._lock:
            return WebSocketMetricsSnapshot(
                channels=[
                    WebSocketChannelSnapshot(
                        channel=channel,
                        active=current.active,
                        opened_total=current.opened_total,
                        closed_total=current.closed_total,
                        errors_total=current.errors_total,
                        duration_seconds_sum=round(
                            current.duration_seconds_sum,
                            9,
                        ),
                    )
                    for channel, current in sorted(
                        self._channels.items()
                    )
                    if (
                        current.active
                        or current.opened_total
                        or current.closed_total
                        or current.errors_total
                    )
                ]
            )

    @staticmethod
    def _normalize(
        channel: str,
    ) -> str:
        return (
            channel
            if channel in _ALLOWED_CHANNELS
            else "other"
        )


class WebSocketMetricsMiddleware:
    """ASGI middleware with bounded channel labels only."""

    def __init__(
        self,
        app,
        *,
        registry: WebSocketMetrics,
    ) -> None:
        self.app = app
        self.registry = registry

    async def __call__(
        self,
        scope,
        receive,
        send,
    ) -> None:
        if scope.get("type") != "websocket":
            await self.app(
                scope,
                receive,
                send,
            )
            return

        channel = classify_websocket_channel(
            str(scope.get("path", ""))
        )
        accepted = False
        started_at = 0.0
        closed = False
        error = False

        async def wrapped_send(message):
            nonlocal accepted, started_at, closed

            message_type = message.get("type")
            if (
                message_type == "websocket.accept"
                and not accepted
            ):
                started_at = await self.registry.opened(
                    channel
                )
                accepted = True
            elif message_type == "websocket.close":
                closed = True

            await send(message)

        try:
            await self.app(
                scope,
                receive,
                wrapped_send,
            )
        except Exception:
            error = True
            raise
        finally:
            if accepted:
                await self.registry.closed(
                    channel,
                    started_at=started_at,
                    error=error,
                )
