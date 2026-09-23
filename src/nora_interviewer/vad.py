from __future__ import annotations

import math
import struct
from enum import Enum

from pydantic import Field, model_validator

from .models import StrictModel


class VadState(str, Enum):
    SILENCE = "silence"
    SPEECH_CANDIDATE = "speech_candidate"
    SPEAKING = "speaking"
    SPEECH_ENDED = "speech_ended"
    MAX_DURATION = "max_duration"


class VadConfig(StrictModel):
    speech_threshold: float = Field(
        default=0.02,
        gt=0.0,
        lt=1.0,
    )
    release_threshold: float = Field(
        default=0.012,
        gt=0.0,
        lt=1.0,
    )
    speech_start_ms: int = Field(
        default=120,
        ge=20,
        le=2000,
    )
    speech_end_silence_ms: int = Field(
        default=700,
        ge=100,
        le=5000,
    )
    max_utterance_ms: int = Field(
        default=120_000,
        ge=1000,
        le=600_000,
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "VadConfig":
        if self.release_threshold >= self.speech_threshold:
            raise ValueError(
                "release_threshold must be lower than speech_threshold"
            )
        return self


class VadObservation(StrictModel):
    state: VadState
    rms: float = Field(ge=0.0, le=1.0)
    peak: float = Field(ge=0.0, le=1.0)
    frame_ms: float = Field(gt=0.0)
    utterance_ms: float = Field(ge=0.0)
    silence_ms: float = Field(ge=0.0)
    speech_started: bool = False
    speech_ended: bool = False
    auto_commit_recommended: bool = False


class Pcm16EnergyVad:
    """Small dependency-free PCM16 energy VAD with hysteresis.

    This detector is intentionally transport-oriented rather than a semantic
    speech model. It provides deterministic speech/silence boundaries and can
    be replaced by a neural VAD behind the same observation contract later.
    """

    def __init__(
        self,
        config: VadConfig | None = None,
    ) -> None:
        self.config = config or VadConfig()
        self.speaking = False
        self.ended = False
        self.candidate_speech_ms = 0.0
        self.utterance_ms = 0.0
        self.silence_ms = 0.0

    def reset(self) -> None:
        self.speaking = False
        self.ended = False
        self.candidate_speech_ms = 0.0
        self.utterance_ms = 0.0
        self.silence_ms = 0.0

    def observe(
        self,
        audio: bytes,
        *,
        sample_rate_hz: int,
        channels: int = 1,
    ) -> VadObservation:
        if sample_rate_hz <= 0:
            raise ValueError(
                "sample_rate_hz must be > 0"
            )
        if channels not in {1, 2}:
            raise ValueError(
                "channels must be 1 or 2"
            )
        if not audio:
            raise ValueError(
                "VAD audio frame cannot be empty"
            )
        if len(audio) % (2 * channels) != 0:
            raise ValueError(
                "PCM16 audio length must align to complete frames"
            )

        sample_count = len(audio) // 2
        frame_count = sample_count // channels
        if frame_count <= 0:
            raise ValueError(
                "PCM16 audio frame contains no samples"
            )

        square_sum = 0.0
        peak = 0
        for (sample,) in struct.iter_unpack(
            "<h",
            audio,
        ):
            absolute = abs(sample)
            peak = max(peak, absolute)
            normalized = sample / 32768.0
            square_sum += normalized * normalized

        rms = math.sqrt(
            square_sum / sample_count
        )
        normalized_peak = min(
            1.0,
            peak / 32768.0,
        )
        frame_ms = (
            frame_count
            / sample_rate_hz
            * 1000.0
        )

        if self.ended:
            return VadObservation(
                state=VadState.SPEECH_ENDED,
                rms=round(rms, 6),
                peak=round(normalized_peak, 6),
                frame_ms=round(frame_ms, 3),
                utterance_ms=round(
                    self.utterance_ms,
                    3,
                ),
                silence_ms=round(
                    self.silence_ms,
                    3,
                ),
                speech_ended=True,
                auto_commit_recommended=True,
            )

        speech_started = False
        speech_ended = False

        if not self.speaking:
            if rms >= self.config.speech_threshold:
                self.candidate_speech_ms += frame_ms
                state = VadState.SPEECH_CANDIDATE
                if (
                    self.candidate_speech_ms
                    >= self.config.speech_start_ms
                ):
                    self.speaking = True
                    speech_started = True
                    self.utterance_ms = (
                        self.candidate_speech_ms
                    )
                    self.silence_ms = 0.0
                    state = VadState.SPEAKING
            else:
                self.candidate_speech_ms = 0.0
                state = VadState.SILENCE
        else:
            self.utterance_ms += frame_ms

            if rms <= self.config.release_threshold:
                self.silence_ms += frame_ms
            else:
                self.silence_ms = 0.0

            if (
                self.utterance_ms
                >= self.config.max_utterance_ms
            ):
                self.ended = True
                speech_ended = True
                state = VadState.MAX_DURATION
            elif (
                self.silence_ms
                >= self.config.speech_end_silence_ms
            ):
                self.ended = True
                speech_ended = True
                state = VadState.SPEECH_ENDED
            else:
                state = VadState.SPEAKING

        return VadObservation(
            state=state,
            rms=round(rms, 6),
            peak=round(normalized_peak, 6),
            frame_ms=round(frame_ms, 3),
            utterance_ms=round(
                self.utterance_ms,
                3,
            ),
            silence_ms=round(
                self.silence_ms,
                3,
            ),
            speech_started=speech_started,
            speech_ended=speech_ended,
            auto_commit_recommended=speech_ended,
        )
