import struct

import pytest

from nora_interviewer.vad import (
    Pcm16EnergyVad,
    VadConfig,
    VadState,
)


def pcm16(
    amplitude: int,
    *,
    samples: int = 320,
) -> bytes:
    return b"".join(
        struct.pack("<h", amplitude)
        for _ in range(samples)
    )


def test_vad_keeps_quiet_frames_as_silence():
    vad = Pcm16EnergyVad(
        VadConfig(
            speech_start_ms=60,
            speech_end_silence_ms=100,
        )
    )

    observation = vad.observe(
        pcm16(100),
        sample_rate_hz=16_000,
    )

    assert observation.state is VadState.SILENCE
    assert observation.speech_started is False
    assert observation.speech_ended is False
    assert observation.auto_commit_recommended is False


def test_vad_requires_sustained_energy_before_speech_start():
    vad = Pcm16EnergyVad(
        VadConfig(
            speech_start_ms=60,
            speech_end_silence_ms=100,
        )
    )

    states = [
        vad.observe(
            pcm16(3000),
            sample_rate_hz=16_000,
        )
        for _ in range(3)
    ]

    assert states[0].state is VadState.SPEECH_CANDIDATE
    assert states[1].state is VadState.SPEECH_CANDIDATE
    assert states[2].state is VadState.SPEAKING
    assert states[2].speech_started is True


def test_vad_hysteresis_does_not_end_on_single_quiet_frame():
    vad = Pcm16EnergyVad(
        VadConfig(
            speech_start_ms=40,
            speech_end_silence_ms=100,
        )
    )

    vad.observe(
        pcm16(3000),
        sample_rate_hz=16_000,
    )
    started = vad.observe(
        pcm16(3000),
        sample_rate_hz=16_000,
    )
    assert started.speech_started is True

    quiet = vad.observe(
        pcm16(100),
        sample_rate_hz=16_000,
    )
    resumed = vad.observe(
        pcm16(2500),
        sample_rate_hz=16_000,
    )

    assert quiet.state is VadState.SPEAKING
    assert quiet.speech_ended is False
    assert resumed.state is VadState.SPEAKING
    assert resumed.silence_ms == 0


def test_vad_recommends_commit_after_end_of_utterance_silence():
    vad = Pcm16EnergyVad(
        VadConfig(
            speech_start_ms=40,
            speech_end_silence_ms=100,
        )
    )

    vad.observe(
        pcm16(3000),
        sample_rate_hz=16_000,
    )
    vad.observe(
        pcm16(3000),
        sample_rate_hz=16_000,
    )

    result = None
    for _ in range(5):
        result = vad.observe(
            pcm16(100),
            sample_rate_hz=16_000,
        )

    assert result is not None
    assert result.state is VadState.SPEECH_ENDED
    assert result.speech_ended is True
    assert result.auto_commit_recommended is True


def test_vad_forces_end_at_max_utterance_duration():
    vad = Pcm16EnergyVad(
        VadConfig(
            speech_start_ms=20,
            speech_end_silence_ms=1000,
            max_utterance_ms=1000,
        )
    )

    result = None
    for _ in range(50):
        result = vad.observe(
            pcm16(3000),
            sample_rate_hz=16_000,
        )
        if result.speech_ended:
            break

    assert result is not None
    assert result.state is VadState.MAX_DURATION
    assert result.auto_commit_recommended is True


def test_vad_rejects_invalid_threshold_order():
    with pytest.raises(
        ValueError,
        match="release_threshold",
    ):
        VadConfig(
            speech_threshold=0.01,
            release_threshold=0.02,
        )


def test_vad_requires_complete_pcm16_frames():
    vad = Pcm16EnergyVad()

    with pytest.raises(
        ValueError,
        match="complete frames",
    ):
        vad.observe(
            b"\x00\x01\x02",
            sample_rate_hz=16_000,
        )
