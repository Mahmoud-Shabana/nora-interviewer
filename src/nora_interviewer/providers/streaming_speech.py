from __future__ import annotations

from ..voice_stream import (
    AudioStreamConfig,
    StreamingSpeechProvider,
    StreamingSpeechSession,
)


class StreamingSpeechUnavailableError(RuntimeError):
    pass


class DisabledStreamingSpeechProvider:
    """Explicit no-provider mode for deployments without streaming STT."""

    provider_id = "disabled"

    async def open(
        self,
        *,
        locale: str,
        config: AudioStreamConfig,
    ) -> StreamingSpeechSession:
        raise StreamingSpeechUnavailableError(
            "Streaming STT is disabled. Configure a streaming speech provider "
            "before opening the audio WebSocket transport."
        )


def provider_id(
    provider: StreamingSpeechProvider,
) -> str:
    return str(
        getattr(
            provider,
            "provider_id",
            type(provider).__name__,
        )
    )
