from __future__ import annotations

import hmac
from dataclasses import dataclass
from uuid import uuid4

from .voice_stream import (
    AudioBackpressureError,
    AudioChunkMessage,
    AudioChunkResult,
    AudioChunkTooLargeError,
    AudioGenerationError,
    AudioReconnectError,
    AudioSequenceError,
    AudioStreamClosedError,
    AudioStreamConfig,
    AudioStreamOpenResult,
    AudioStreamState,
    new_reconnect_token,
)


@dataclass
class _StreamRecord:
    state: AudioStreamState
    reconnect_token: str


class AudioStreamManager:
    """Own audio transport sequencing, buffering, and reconnect state.

    The manager intentionally does not transcribe audio. It enforces transport
    invariants before bytes reach a configured streaming STT provider.
    """

    def __init__(self) -> None:
        self._streams: dict[str, _StreamRecord] = {}

    def open(
        self,
        *,
        session_id: str,
        generation: int,
        config: AudioStreamConfig,
    ) -> AudioStreamOpenResult:
        stream_id = str(uuid4())
        token = new_reconnect_token()
        state = AudioStreamState(
            stream_id=stream_id,
            session_id=session_id,
            generation=generation,
            config=config,
        )
        self._streams[stream_id] = _StreamRecord(
            state=state,
            reconnect_token=token,
        )
        return AudioStreamOpenResult(
            state=state.model_copy(deep=True),
            reconnect_token=token,
        )

    def active_stream_count(self) -> int:
        return sum(
            not record.state.closed
            for record in self._streams.values()
        )

    def tracked_stream_count(self) -> int:
        return len(self._streams)

    def state(
        self,
        stream_id: str,
    ) -> AudioStreamState:
        record = self._record(stream_id)
        return record.state.model_copy(deep=True)

    def accept_chunk(
        self,
        stream_id: str,
        chunk: AudioChunkMessage,
    ) -> tuple[AudioChunkResult, bytes | None]:
        record = self._record(stream_id)
        state = record.state

        if state.closed:
            raise AudioStreamClosedError(
                f"audio stream {stream_id} is closed"
            )

        if chunk.generation != state.generation:
            raise AudioGenerationError(
                f"expected generation {state.generation}, "
                f"got {chunk.generation}"
            )

        if chunk.sequence < state.next_sequence:
            state.duplicate_chunks += 1
            return (
                AudioChunkResult(
                    accepted=True,
                    duplicate=True,
                    sequence=chunk.sequence,
                    next_sequence=state.next_sequence,
                    generation=state.generation,
                    buffered_bytes=state.buffered_bytes,
                ),
                None,
            )

        if chunk.sequence > state.next_sequence:
            raise AudioSequenceError(
                f"expected sequence {state.next_sequence}, "
                f"got {chunk.sequence}"
            )

        audio = chunk.decode()
        size = len(audio)
        if size == 0:
            raise AudioChunkTooLargeError(
                "empty audio chunks are not accepted"
            )
        if size > state.config.max_chunk_bytes:
            raise AudioChunkTooLargeError(
                f"audio chunk is {size} bytes; limit is "
                f"{state.config.max_chunk_bytes}"
            )

        projected = state.buffered_bytes + size
        if projected > state.config.max_buffered_bytes:
            raise AudioBackpressureError(
                f"audio buffer would reach {projected} bytes; limit is "
                f"{state.config.max_buffered_bytes}"
            )

        state.buffered_bytes = projected
        state.accepted_chunks += 1
        state.accepted_bytes += size
        state.next_sequence += 1

        return (
            AudioChunkResult(
                accepted=True,
                duplicate=False,
                sequence=chunk.sequence,
                next_sequence=state.next_sequence,
                generation=state.generation,
                buffered_bytes=state.buffered_bytes,
            ),
            audio,
        )

    def acknowledge_processed(
        self,
        stream_id: str,
        byte_count: int,
    ) -> AudioStreamState:
        record = self._record(stream_id)
        state = record.state
        if byte_count < 0:
            raise ValueError("byte_count must be >= 0")
        if byte_count > state.buffered_bytes:
            raise ValueError(
                "cannot acknowledge more bytes than are buffered"
            )

        state.buffered_bytes -= byte_count
        return state.model_copy(deep=True)

    def rotate_generation(
        self,
        stream_id: str,
        generation: int,
    ) -> AudioStreamState:
        record = self._record(stream_id)
        state = record.state

        if state.closed:
            raise AudioStreamClosedError(
                f"audio stream {stream_id} is closed"
            )
        if generation <= state.generation:
            raise AudioGenerationError(
                f"new generation must be greater than {state.generation}"
            )

        state.generation = generation
        state.next_sequence = 0
        state.buffered_bytes = 0
        return state.model_copy(deep=True)

    def reconnect(
        self,
        *,
        stream_id: str,
        session_id: str,
        reconnect_token: str,
        generation: int,
        next_sequence: int,
    ) -> AudioStreamState:
        record = self._record(stream_id)
        state = record.state

        if state.closed:
            raise AudioStreamClosedError(
                f"audio stream {stream_id} is closed"
            )
        if session_id != state.session_id:
            raise AudioReconnectError(
                "audio stream does not belong to this session"
            )
        if not hmac.compare_digest(
            reconnect_token,
            record.reconnect_token,
        ):
            raise AudioReconnectError(
                "audio reconnect token is invalid"
            )
        if generation != state.generation:
            raise AudioGenerationError(
                f"expected generation {state.generation}, "
                f"got {generation}"
            )
        if next_sequence != state.next_sequence:
            raise AudioSequenceError(
                f"expected next_sequence {state.next_sequence}, "
                f"got {next_sequence}"
            )

        state.reconnect_count += 1
        return state.model_copy(deep=True)

    def close(
        self,
        stream_id: str,
    ) -> AudioStreamState:
        record = self._record(stream_id)
        state = record.state
        state.closed = True
        state.buffered_bytes = 0
        return state.model_copy(deep=True)

    def _record(
        self,
        stream_id: str,
    ) -> _StreamRecord:
        try:
            return self._streams[stream_id]
        except KeyError as exc:
            raise AudioReconnectError(
                f"unknown audio stream: {stream_id}"
            ) from exc
