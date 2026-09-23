from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from .audio_stream_manager import AudioStreamManager
from .voice import (
    RealtimeVoiceCoordinator,
    TranscriptEvent,
    VoiceSessionState,
    VoiceTransportSelectionEvent,
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


@dataclass(frozen=True)
class StreamingProviderFailure(StreamingVoiceEvent):
    error_type: str
    message: str


_END = object()


@dataclass
class _ProviderStream:
    session: StreamingSpeechSession
    locale: str
    queue: asyncio.Queue
    pump_task: asyncio.Task | None = None


class VoiceStreamBridge:
    """Connect ordered audio transport to STT and Nora voice semantics.

    Provider events are pumped into a server-side queue independently of any
    particular client WebSocket. A temporary client disconnect therefore does
    not make reconnect semantics depend on an already-dead socket consumer.
    """

    def __init__(
        self,
        *,
        manager: AudioStreamManager,
        provider: StreamingSpeechProvider,
        voice: RealtimeVoiceCoordinator,
        event_queue_size: int = 64,
    ) -> None:
        if event_queue_size < 1:
            raise ValueError(
                "event_queue_size must be >= 1"
            )
        self.manager = manager
        self.provider = provider
        self.voice = voice
        self.event_queue_size = event_queue_size
        self._provider_streams: dict[
            str,
            _ProviderStream,
        ] = {}

    async def open(
        self,
        *,
        session_id: str,
        locale: str,
        config: AudioStreamConfig,
    ) -> AudioStreamOpenResult:
        provider_session = await self.provider.open(
            locale=locale,
            config=config,
        )
        try:
            voice_state = await self.voice.speech_started(
                session_id
            )
        except Exception:
            await provider_session.cancel()
            raise

        opened = self.manager.open(
            session_id=session_id,
            generation=voice_state.generation,
            config=config,
        )
        await self.voice.transport_selected(
            session_id,
            VoiceTransportSelectionEvent(
                direction="stt",
                transport="server",
                provider_id=str(
                    getattr(
                        self.provider,
                        "provider_id",
                        type(self.provider).__name__,
                    )
                ),
            ),
        )

        record = _ProviderStream(
            session=provider_session,
            locale=locale,
            queue=asyncio.Queue(
                maxsize=self.event_queue_size
            ),
        )
        self._provider_streams[
            opened.state.stream_id
        ] = record
        record.pump_task = asyncio.create_task(
            self._pump_provider(
                opened.state.stream_id,
                record,
                opened.state.generation,
            )
        )
        return opened

    async def _pump_provider(
        self,
        stream_id: str,
        record: _ProviderStream,
        generation: int,
    ) -> None:
        try:
            async for event in record.session.events():
                current = self.manager.state(
                    stream_id
                )
                if (
                    current.closed
                    or current.generation != generation
                ):
                    break

                transcript = TranscriptEvent(
                    text=event.text,
                    confidence=event.confidence,
                )
                if event.is_final:
                    result = (
                        await self.voice.transcript_final(
                            current.session_id,
                            transcript,
                        )
                    )
                    await record.queue.put(
                        StreamingFinalTranscript(
                            event=event,
                            result=result,
                        )
                    )
                    break

                voice_state = (
                    await self.voice.transcript_partial(
                        current.session_id,
                        transcript,
                    )
                )
                await record.queue.put(
                    StreamingPartialTranscript(
                        event=event,
                        state=voice_state,
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                state = self.manager.state(stream_id)
                await self.voice.provider_failed(
                    state.session_id,
                    direction="stt",
                    provider_id=str(
                        getattr(
                            self.provider,
                            "provider_id",
                            type(self.provider).__name__,
                        )
                    ),
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            except Exception:
                pass
            await record.queue.put(
                StreamingProviderFailure(
                    error_type=type(exc).__name__,
                    message=str(exc)[:1000],
                )
            )
        finally:
            await record.queue.put(_END)

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

        provider_stream = self._provider(
            stream_id
        )
        try:
            await provider_stream.session.push_audio(
                audio
            )
        except Exception as exc:
            state = self.manager.state(stream_id)
            try:
                await self.voice.provider_failed(
                    state.session_id,
                    direction="stt",
                    provider_id=str(
                        getattr(
                            self.provider,
                            "provider_id",
                            type(self.provider).__name__,
                        )
                    ),
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            except Exception:
                pass
            raise
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

    async def commit(
        self,
        *,
        stream_id: str,
    ) -> None:
        record = self._provider(stream_id)
        try:
            await record.session.commit()
        except Exception as exc:
            state = self.manager.state(stream_id)
            try:
                await self.voice.provider_failed(
                    state.session_id,
                    direction="stt",
                    provider_id=str(
                        getattr(
                            self.provider,
                            "provider_id",
                            type(self.provider).__name__,
                        )
                    ),
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            finally:
                raise

    async def next_event(
        self,
        *,
        stream_id: str,
    ) -> StreamingVoiceEvent | None:
        record = self._provider(stream_id)
        item = await record.queue.get()
        if item is _END:
            return None
        return item

    async def events(
        self,
        *,
        stream_id: str,
    ) -> AsyncIterator[StreamingVoiceEvent]:
        while True:
            event = await self.next_event(
                stream_id=stream_id
            )
            if event is None:
                return
            yield event

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
        self._provider(stream_id)
        return self.voice.state(
            state.session_id
        )

    async def close(
        self,
        *,
        stream_id: str,
        cancel_provider: bool = False,
    ) -> None:
        self.manager.close(stream_id)
        record = self._provider_streams.pop(
            stream_id,
            None,
        )
        if record is None:
            return

        if cancel_provider:
            await record.session.cancel()
        else:
            await record.session.close()

        task = record.pump_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def close_all(self) -> None:
        for stream_id in list(
            self._provider_streams
        ):
            await self.close(
                stream_id=stream_id,
                cancel_provider=True,
            )

    def _provider(
        self,
        stream_id: str,
    ) -> _ProviderStream:
        try:
            return self._provider_streams[
                stream_id
            ]
        except KeyError as exc:
            raise RuntimeError(
                f"no STT provider session for audio stream {stream_id}"
            ) from exc
