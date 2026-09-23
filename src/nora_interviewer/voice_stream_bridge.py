from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from .audio_stream_manager import AudioStreamManager
from .voice import (
    RealtimeVoiceCoordinator,
    TranscriptEvent,
    VoiceSessionState,
    VoiceTurnResult,
)
from .voice_stream import (
    AudioChunkMessage,
    AudioChunkResult,
    AudioStreamConfig,
    AudioStreamOpenResult,
    SpeechRecognitionEvent,
    StreamingSpeechProvider,
    StreamingSpeechSession,
)


@dataclass
class _ProviderStream:
    session: StreamingSpeechSession
    locale: str


class StreamingVoiceEvent:
    """Marker base class for bridge events."""


@dataclass(frozen=True)
class StreamingPartialTranscript(StreamingVoiceEvent):
    event: SpeechRecognitionEvent
    state: VoiceSessionState


@dataclass(frozen=True)
class StreamingFinalTranscript(StreamingVoiceEvent):
    event: SpeechRecognitionEvent
    result: VoiceTurnResult


class VoiceStreamBridge:
    """Connect ordered audio transport to STT and Nora voice semantics."""

    def __init__(
        self,
        *,
        manager: AudioStreamManager,
        provider: StreamingSpeechProvider,
        voice: RealtimeVoiceCoordinator,
    ) -> None:
        self.manager = manager
        self.provider = provider
        self.voice = voice
        self._provider_streams: dict[str, _ProviderStream] = {}

    async def open(
        self,
        *,
        session_id: str,
        locale: str,
        config: AudioStreamConfig,
    ) -> AudioStreamOpenResult:
        voice_state = await self.voice.speech_started(
            session_id
        )
        opened = self.manager.open(
            session_id=session_id,
            generation=voice_state.generation,
            config=config,
        )
        try:
            provider_session = await self.provider.open(
                locale=locale,
                config=config,
            )
        except Exception:
            self.manager.close(opened.state.stream_id)
            raise

        self._provider_streams[
            opened.state.stream_id
        ] = _ProviderStream(
            session=provider_session,
            locale=locale,
        )
        return opened

    async def push_chunk(
        self,
        *,
        stream_id: str,
        chunk: AudioChunkMessage,
    ) -> AudioChunkResult:
        result, audio = self.manager.accept_chunk(
            stream_id,
            chunk,
        )
        if audio is None:
            return result

        provider_stream = self._provider(stream_id)
        try:
            await provider_stream.session.push_audio(
                audio
            )
        finally:
            self.manager.acknowledge_processed(
                stream_id,
                len(audio),
            )

        state = self.manager.state(stream_id)
        return AudioChunkResult(
            accepted=result.accepted,
            duplicate=result.duplicate,
            sequence=result.sequence,
            next_sequence=result.next_sequence,
            generation=result.generation,
            buffered_bytes=state.buffered_bytes,
        )

    async def events(
        self,
        *,
        stream_id: str,
    ) -> AsyncIterator[StreamingVoiceEvent]:
        provider_stream = self._provider(stream_id)
        state = self.manager.state(stream_id)

        async for event in provider_stream.session.events():
            current = self.manager.state(stream_id)
            if current.closed:
                break
            if current.generation != state.generation:
                # The caller should restart provider streaming for a new
                # generation instead of applying stale transcript events.
                break

            transcript = TranscriptEvent(
                text=event.text,
                confidence=event.confidence,
            )
            if event.is_final:
                result = await self.voice.transcript_final(
                    current.session_id,
                    transcript,
                )
                yield StreamingFinalTranscript(
                    event=event,
                    result=result,
                )
            else:
                voice_state = await self.voice.transcript_partial(
                    current.session_id,
                    transcript,
                )
                yield StreamingPartialTranscript(
                    event=event,
                    state=voice_state,
                )

    def reconnect(
        self,
        *,
        stream_id: str,
        session_id: str,
        reconnect_token: str,
        generation: int,
        next_sequence: int,
    ) -> VoiceSessionState:
        state = self.manager.reconnect(
            stream_id=stream_id,
            session_id=session_id,
            reconnect_token=reconnect_token,
            generation=generation,
            next_sequence=next_sequence,
        )
        return self.voice.state(state.session_id)

    async def rotate_generation(
        self,
        *,
        stream_id: str,
        generation: int,
    ) -> None:
        self.manager.rotate_generation(
            stream_id,
            generation,
        )
        provider_stream = self._provider(stream_id)
        await provider_stream.session.cancel()
        del self._provider_streams[stream_id]

    async def close(
        self,
        *,
        stream_id: str,
        cancel_provider: bool = False,
    ) -> None:
        self.manager.close(stream_id)
        provider_stream = self._provider_streams.pop(
            stream_id,
            None,
        )
        if provider_stream is None:
            return
        if cancel_provider:
            await provider_stream.session.cancel()
        else:
            await provider_stream.session.close()

    def _provider(
        self,
        stream_id: str,
    ) -> _ProviderStream:
        try:
            return self._provider_streams[stream_id]
        except KeyError as exc:
            raise RuntimeError(
                f"no STT provider session for audio stream {stream_id}"
            ) from exc
