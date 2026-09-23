from __future__ import annotations

from collections.abc import AsyncIterator
from enum import Enum
from typing import Protocol

from pydantic import Field

from ..models import StrictModel


class TtsAudioEncoding(str, Enum):
    PCM16 = "pcm16"
    MP3 = "mp3"
    OPUS = "opus"


class TtsAudioConfig(StrictModel):
    encoding: TtsAudioEncoding = TtsAudioEncoding.PCM16
    sample_rate_hz: int = Field(
        default=24_000,
        ge=8_000,
        le=96_000,
    )
    channels: int = Field(default=1, ge=1, le=2)


class TtsAudioChunk(StrictModel):
    sequence: int = Field(ge=0)
    generation: int = Field(ge=0)
    audio: bytes = Field(min_length=1)


class StreamingTtsSession(Protocol):
    async def chunks(
        self,
    ) -> AsyncIterator[TtsAudioChunk]: ...

    async def cancel(self) -> None: ...

    async def close(self) -> None: ...


class StreamingTtsProvider(Protocol):
    provider_id: str

    async def synthesize(
        self,
        *,
        text: str,
        locale: str,
        generation: int,
        config: TtsAudioConfig,
    ) -> StreamingTtsSession: ...


class StreamingTtsUnavailableError(RuntimeError):
    pass


class DisabledStreamingTtsProvider:
    provider_id = "disabled"

    async def synthesize(
        self,
        *,
        text: str,
        locale: str,
        generation: int,
        config: TtsAudioConfig,
    ) -> StreamingTtsSession:
        raise StreamingTtsUnavailableError(
            "Production streaming TTS is disabled. "
            "Configure NORA_STREAMING_TTS_MODE."
        )
