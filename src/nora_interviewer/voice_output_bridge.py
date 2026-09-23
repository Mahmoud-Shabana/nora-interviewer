from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator
from uuid import uuid4

from fastapi import HTTPException

from .models import Speaker
from .providers.streaming_tts import (
    StreamingTtsProvider,
    StreamingTtsSession,
    TtsAudioChunk,
    TtsAudioConfig,
)
from .storage import Store
from .voice import (
    RealtimeVoiceCoordinator,
    TtsLifecycleEvent,
)
from .voice_output import (
    TtsStreamConflictError,
    TtsStreamNotFoundError,
    TtsStreamOpenResult,
    TtsStreamState,
)


@dataclass
class _OutputStream:
    state: TtsStreamState
    provider_session: StreamingTtsSession


class VoiceOutputBridge:
    """Bridge Nora interviewer turns to a streaming TTS provider."""

    def __init__(
        self,
        *,
        store: Store,
        provider: StreamingTtsProvider,
        voice: RealtimeVoiceCoordinator,
    ) -> None:
        self.store = store
        self.provider = provider
        self.voice = voice
        self._streams: dict[str, _OutputStream] = {}
        self._active_by_session: dict[str, str] = {}
        self._opening_sessions: set[str] = set()
        self._lock = asyncio.Lock()

    async def open(
        self,
        *,
        session_id: str,
        turn_id: str,
        locale: str | None,
        config: TtsAudioConfig,
    ) -> TtsStreamOpenResult:
        session = await self.store.get_session(session_id)
        if session is None:
            raise HTTPException(404, "Session not found")

        turn = next(
            (
                item
                for item in session.turns
                if item.id == turn_id
            ),
            None,
        )
        if turn is None:
            raise HTTPException(404, "Interviewer turn not found")
        if turn.speaker is not Speaker.INTERVIEWER:
            raise HTTPException(
                400,
                "Streaming TTS requires an interviewer turn",
            )

        async with self._lock:
            if (
                session_id in self._active_by_session
                or session_id in self._opening_sessions
            ):
                raise TtsStreamConflictError(
                    "session already has an active TTS stream"
                )
            self._opening_sessions.add(session_id)

        provider_session = None
        try:
            generation = self.voice.state(
                session_id
            ).generation
            provider_session = await self.provider.synthesize(
                text=turn.text,
                locale=locale or session.locale,
                generation=generation,
                config=config,
            )

            await self.voice.tts_started(
                session_id,
                TtsLifecycleEvent(
                    turn_id=turn.id,
                ),
            )

            stream_id = str(uuid4())
            state = TtsStreamState(
                stream_id=stream_id,
                session_id=session_id,
                turn_id=turn.id,
                generation=generation,
                config=config,
            )
            record = _OutputStream(
                state=state,
                provider_session=provider_session,
            )

            async with self._lock:
                self._streams[stream_id] = record
                self._active_by_session[
                    session_id
                ] = stream_id

            return TtsStreamOpenResult(
                state=state.model_copy(deep=True)
            )
        except Exception:
            if provider_session is not None:
                await provider_session.cancel()
            raise
        finally:
            async with self._lock:
                self._opening_sessions.discard(
                    session_id
                )

    async def chunks(
        self,
        *,
        stream_id: str,
    ) -> AsyncIterator[TtsAudioChunk]:
        record = self._record(stream_id)
        normal_completion = False

        try:
            async for chunk in (
                record.provider_session.chunks()
            ):
                if (
                    chunk.generation
                    != record.state.generation
                ):
                    raise RuntimeError(
                        "TTS provider emitted a stale generation"
                    )

                current_voice = self.voice.state(
                    record.state.session_id
                )
                if (
                    current_voice.generation
                    != record.state.generation
                    or current_voice.active_tts_turn_id
                    != record.state.turn_id
                ):
                    record.state.cancelled = True
                    await record.provider_session.cancel()
                    return

                record.state.chunks_sent += 1
                record.state.bytes_sent += len(
                    chunk.audio
                )
                yield chunk

            normal_completion = True
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._mark_cancelled(
                record,
                reason="tts_provider_failure",
            )
            raise
        finally:
            if normal_completion:
                current_voice = self.voice.state(
                    record.state.session_id
                )
                if (
                    current_voice.active_tts_turn_id
                    == record.state.turn_id
                    and current_voice.generation
                    == record.state.generation
                ):
                    await self.voice.tts_completed(
                        record.state.session_id,
                        TtsLifecycleEvent(
                            turn_id=record.state.turn_id,
                        ),
                    )
                else:
                    record.state.cancelled = True

            record.state.closed = True
            await self._release(record)

    async def cancel_active(
        self,
        *,
        session_id: str,
        reason: str = "barge_in",
    ) -> bool:
        async with self._lock:
            stream_id = self._active_by_session.get(
                session_id
            )
            record = (
                self._streams.get(stream_id)
                if stream_id
                else None
            )

        if record is None:
            return False

        await self._mark_cancelled(
            record,
            reason=reason,
        )
        record.state.closed = True
        await self._release(record)
        return True

    async def close(
        self,
        *,
        stream_id: str,
        reason: str = "client_disconnect",
    ) -> None:
        record = self._record(stream_id)
        await self._mark_cancelled(
            record,
            reason=reason,
        )
        record.state.closed = True
        await self._release(record)

    async def close_all(self) -> None:
        async with self._lock:
            stream_ids = list(self._streams)
        for stream_id in stream_ids:
            try:
                await self.close(
                    stream_id=stream_id,
                    reason="server_shutdown",
                )
            except TtsStreamNotFoundError:
                continue

    def state(
        self,
        stream_id: str,
    ) -> TtsStreamState:
        return self._record(
            stream_id
        ).state.model_copy(deep=True)

    async def _mark_cancelled(
        self,
        record: _OutputStream,
        *,
        reason: str,
    ) -> None:
        if record.state.cancelled:
            return

        record.state.cancelled = True
        try:
            await record.provider_session.cancel()
        finally:
            current = self.voice.state(
                record.state.session_id
            )
            if (
                current.active_tts_turn_id
                == record.state.turn_id
            ):
                await self.voice.tts_cancelled(
                    record.state.session_id,
                    TtsLifecycleEvent(
                        turn_id=record.state.turn_id,
                    ),
                    reason=reason,
                )

    async def _release(
        self,
        record: _OutputStream,
    ) -> None:
        async with self._lock:
            self._streams.pop(
                record.state.stream_id,
                None,
            )
            if (
                self._active_by_session.get(
                    record.state.session_id
                )
                == record.state.stream_id
            ):
                self._active_by_session.pop(
                    record.state.session_id,
                    None,
                )

    def _record(
        self,
        stream_id: str,
    ) -> _OutputStream:
        try:
            return self._streams[stream_id]
        except KeyError as exc:
            raise TtsStreamNotFoundError(
                f"unknown TTS stream {stream_id}"
            ) from exc
