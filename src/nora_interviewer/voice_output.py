from __future__ import annotations

from pydantic import Field

from .models import StrictModel
from .providers.streaming_tts import TtsAudioConfig


class TtsStreamOpenRequest(StrictModel):
    turn_id: str = Field(min_length=1)
    locale: str | None = Field(
        default=None,
        min_length=2,
        max_length=32,
    )
    config: TtsAudioConfig = Field(
        default_factory=TtsAudioConfig
    )


class TtsStreamState(StrictModel):
    stream_id: str
    session_id: str
    turn_id: str
    generation: int = Field(ge=0)
    config: TtsAudioConfig
    closed: bool = False
    cancelled: bool = False
    chunks_sent: int = Field(default=0, ge=0)
    bytes_sent: int = Field(default=0, ge=0)


class TtsStreamOpenResult(StrictModel):
    state: TtsStreamState


class TtsStreamError(RuntimeError):
    code = "tts_stream_error"


class TtsStreamNotFoundError(TtsStreamError):
    code = "tts_stream_not_found"


class TtsStreamConflictError(TtsStreamError):
    code = "tts_stream_conflict"
