from __future__ import annotations

import base64
import binascii
import secrets
from enum import Enum
from typing import AsyncIterator, Protocol

from pydantic import Field, model_validator

from .models import StrictModel
from .vad import VadObservation


class AudioEncoding(str, Enum):
    PCM16 = "pcm16"
    OPUS = "opus"


class AudioStreamConfig(StrictModel):
    encoding: AudioEncoding = AudioEncoding.PCM16
    sample_rate_hz: int = Field(default=16_000, ge=8_000, le=96_000)
    channels: int = Field(default=1, ge=1, le=2)
    max_chunk_bytes: int = Field(default=32_768, ge=1_024, le=262_144)
    max_buffered_bytes: int = Field(
        default=524_288,
        ge=32_768,
        le=8_388_608,
    )

    @model_validator(mode="after")
    def validate_buffer(self) -> "AudioStreamConfig":
        if self.max_buffered_bytes < self.max_chunk_bytes:
            raise ValueError(
                "max_buffered_bytes must be >= max_chunk_bytes"
            )
        return self


class AudioChunkMessage(StrictModel):
    sequence: int = Field(ge=0)
    generation: int = Field(ge=0)
    audio_base64: str = Field(min_length=4)

    def decode(self) -> bytes:
        try:
            return base64.b64decode(
                self.audio_base64,
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "audio_base64 is not valid base64"
            ) from exc

    @classmethod
    def from_bytes(
        cls,
        *,
        sequence: int,
        generation: int,
        audio: bytes,
    ) -> "AudioChunkMessage":
        return cls(
            sequence=sequence,
            generation=generation,
            audio_base64=base64.b64encode(audio).decode("ascii"),
        )


class SpeechRecognitionEvent(StrictModel):
    text: str = Field(min_length=1, max_length=20_000)
    is_final: bool = False
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


class AudioStreamState(StrictModel):
    stream_id: str
    session_id: str
    config: AudioStreamConfig
    generation: int = Field(default=0, ge=0)
    next_sequence: int = Field(default=0, ge=0)
    buffered_bytes: int = Field(default=0, ge=0)
    accepted_chunks: int = Field(default=0, ge=0)
    accepted_bytes: int = Field(default=0, ge=0)
    duplicate_chunks: int = Field(default=0, ge=0)
    reconnect_count: int = Field(default=0, ge=0)
    closed: bool = False


class AudioChunkResult(StrictModel):
    accepted: bool
    duplicate: bool = False
    sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    generation: int = Field(ge=0)
    buffered_bytes: int = Field(ge=0)
    vad: VadObservation | None = None


class AudioStreamOpenResult(StrictModel):
    state: AudioStreamState
    reconnect_token: str = Field(min_length=20)


class AudioStreamError(RuntimeError):
    code = "audio_stream_error"


class AudioStreamClosedError(AudioStreamError):
    code = "stream_closed"


class AudioChunkTooLargeError(AudioStreamError):
    code = "chunk_too_large"


class AudioSequenceError(AudioStreamError):
    code = "invalid_sequence"


class AudioGenerationError(AudioStreamError):
    code = "stale_generation"


class AudioBackpressureError(AudioStreamError):
    code = "backpressure"


class AudioReconnectError(AudioStreamError):
    code = "invalid_reconnect"


class StreamingSpeechSession(Protocol):
    async def push_audio(
        self,
        audio: bytes,
    ) -> None: ...

    async def events(
        self,
    ) -> AsyncIterator[SpeechRecognitionEvent]: ...

    async def commit(self) -> None: ...

    async def close(self) -> None: ...

    async def cancel(self) -> None: ...


class StreamingSpeechProvider(Protocol):
    async def open(
        self,
        *,
        locale: str,
        config: AudioStreamConfig,
    ) -> StreamingSpeechSession: ...


def new_reconnect_token() -> str:
    return secrets.token_urlsafe(32)



class AudioStreamOpenRequest(StrictModel):
    locale: str = Field(default="en", min_length=2, max_length=32)
    config: AudioStreamConfig = Field(default_factory=AudioStreamConfig)


class AudioStreamReconnectRequest(StrictModel):
    stream_id: str = Field(min_length=1)
    reconnect_token: str = Field(min_length=20)
    generation: int = Field(ge=0)
    next_sequence: int = Field(ge=0)


class AudioStreamCloseRequest(StrictModel):
    stream_id: str = Field(min_length=1)
    cancel_provider: bool = False
