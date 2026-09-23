import pytest

from nora_interviewer.audio_stream_manager import AudioStreamManager
from nora_interviewer.voice_stream import (
    AudioBackpressureError,
    AudioChunkMessage,
    AudioChunkTooLargeError,
    AudioGenerationError,
    AudioReconnectError,
    AudioSequenceError,
    AudioStreamConfig,
)


def opened(
    *,
    max_chunk_bytes: int = 1024,
    max_buffered_bytes: int = 2048,
):
    manager = AudioStreamManager()
    result = manager.open(
        session_id="session",
        generation=3,
        config=AudioStreamConfig(
            max_chunk_bytes=max_chunk_bytes,
            max_buffered_bytes=max_buffered_bytes,
        ),
    )
    return manager, result


def test_audio_chunks_require_contiguous_sequence_and_are_idempotent():
    manager, result = opened()
    stream_id = result.state.stream_id

    first, audio = manager.accept_chunk(
        stream_id,
        AudioChunkMessage.from_bytes(
            sequence=0,
            generation=3,
            audio=b"a" * 100,
        ),
    )
    assert first.accepted is True
    assert first.duplicate is False
    assert first.next_sequence == 1
    assert audio == b"a" * 100

    duplicate, duplicate_audio = manager.accept_chunk(
        stream_id,
        AudioChunkMessage.from_bytes(
            sequence=0,
            generation=3,
            audio=b"different bytes are ignored",
        ),
    )
    assert duplicate.accepted is True
    assert duplicate.duplicate is True
    assert duplicate.next_sequence == 1
    assert duplicate_audio is None

    with pytest.raises(AudioSequenceError):
        manager.accept_chunk(
            stream_id,
            AudioChunkMessage.from_bytes(
                sequence=2,
                generation=3,
                audio=b"gap",
            ),
        )


def test_audio_chunk_and_buffer_limits_are_enforced():
    manager, result = opened(
        max_chunk_bytes=1024,
        max_buffered_bytes=1536,
    )
    stream_id = result.state.stream_id

    manager.accept_chunk(
        stream_id,
        AudioChunkMessage.from_bytes(
            sequence=0,
            generation=3,
            audio=b"a" * 800,
        ),
    )

    with pytest.raises(AudioBackpressureError):
        manager.accept_chunk(
            stream_id,
            AudioChunkMessage.from_bytes(
                sequence=1,
                generation=3,
                audio=b"b" * 800,
            ),
        )

    state = manager.acknowledge_processed(
        stream_id,
        800,
    )
    assert state.buffered_bytes == 0

    with pytest.raises(AudioChunkTooLargeError):
        manager.accept_chunk(
            stream_id,
            AudioChunkMessage.from_bytes(
                sequence=1,
                generation=3,
                audio=b"x" * 1025,
            ),
        )


def test_generation_rotation_invalidates_stale_audio():
    manager, result = opened()
    stream_id = result.state.stream_id

    manager.accept_chunk(
        stream_id,
        AudioChunkMessage.from_bytes(
            sequence=0,
            generation=3,
            audio=b"old",
        ),
    )
    rotated = manager.rotate_generation(
        stream_id,
        4,
    )
    assert rotated.generation == 4
    assert rotated.next_sequence == 0
    assert rotated.buffered_bytes == 0

    with pytest.raises(AudioGenerationError):
        manager.accept_chunk(
            stream_id,
            AudioChunkMessage.from_bytes(
                sequence=1,
                generation=3,
                audio=b"stale",
            ),
        )

    accepted, audio = manager.accept_chunk(
        stream_id,
        AudioChunkMessage.from_bytes(
            sequence=0,
            generation=4,
            audio=b"fresh",
        ),
    )
    assert accepted.next_sequence == 1
    assert audio == b"fresh"


def test_reconnect_requires_identity_and_never_accepts_cursor_ahead_of_server():
    manager, result = opened()
    stream_id = result.state.stream_id

    manager.accept_chunk(
        stream_id,
        AudioChunkMessage.from_bytes(
            sequence=0,
            generation=3,
            audio=b"hello",
        ),
    )

    with pytest.raises(AudioReconnectError):
        manager.reconnect(
            stream_id=stream_id,
            session_id="other-session",
            reconnect_token=result.reconnect_token,
            generation=3,
            next_sequence=1,
        )

    with pytest.raises(AudioReconnectError):
        manager.reconnect(
            stream_id=stream_id,
            session_id="session",
            reconnect_token="wrong-token",
            generation=3,
            next_sequence=1,
        )

    with pytest.raises(AudioSequenceError):
        manager.reconnect(
            stream_id=stream_id,
            session_id="session",
            reconnect_token=result.reconnect_token,
            generation=3,
            next_sequence=2,
        )

    # The client may reconnect from its last acknowledged cursor. The
    # authoritative server cursor is returned so unacknowledged frames can
    # be reconciled without replaying frames the server already accepted.
    behind = manager.reconnect(
        stream_id=stream_id,
        session_id="session",
        reconnect_token=result.reconnect_token,
        generation=3,
        next_sequence=0,
    )
    assert behind.next_sequence == 1
    assert behind.reconnect_count == 1

    exact = manager.reconnect(
        stream_id=stream_id,
        session_id="session",
        reconnect_token=result.reconnect_token,
        generation=3,
        next_sequence=1,
    )
    assert exact.next_sequence == 1
    assert exact.reconnect_count == 2
