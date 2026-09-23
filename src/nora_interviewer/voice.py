from __future__ import annotations

from enum import Enum
from time import perf_counter
from typing import Callable, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from .audit import append_event
from .models import EventType, SessionStatus, StrictModel, ToolInvocation, Turn
from .service import InterviewService
from .storage import Store, StoreConflictError
from .vad import VadObservation


class VoicePhase(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CLOSED = "closed"


class TranscriptEvent(StrictModel):
    text: str = Field(min_length=1, max_length=20_000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TtsLifecycleEvent(StrictModel):
    turn_id: str = Field(min_length=1)


class VoiceTransportSelectionEvent(StrictModel):
    direction: Literal["stt", "tts"]
    transport: Literal["server", "browser"]
    provider_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class VoiceTransportFallbackEvent(StrictModel):
    direction: Literal["stt", "tts"]
    from_transport: Literal["server", "browser"]
    to_transport: Literal["server", "browser"]
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_transition(self) -> "VoiceTransportFallbackEvent":
        if self.from_transport == self.to_transport:
            raise ValueError(
                "voice transport fallback must change transport"
            )
        return self


class VoiceSessionState(StrictModel):
    session_id: str
    phase: VoicePhase = VoicePhase.IDLE
    generation: int = Field(default=0, ge=0)
    interruption_count: int = Field(default=0, ge=0)
    active_tts_turn_id: str | None = None
    speech_started_at_ms: int | None = None
    response_ready_at_ms: int | None = None
    last_speech_to_final_ms: int | None = Field(default=None, ge=0)
    last_final_to_response_ms: int | None = Field(default=None, ge=0)
    last_response_to_tts_ms: int | None = Field(default=None, ge=0)


class VoiceTurnResult(StrictModel):
    state: VoiceSessionState
    interviewer_turn: Turn | None = None
    tool_invocation: ToolInvocation | None = None
    completed: bool = False


class RealtimeVoiceCoordinator:
    """Provider-neutral realtime speech lifecycle and barge-in state machine.

    STT/TTS providers can feed this coordinator partial/final transcripts and TTS
    lifecycle events. Nora keeps the interview semantics in InterviewService while
    this layer owns voice timing and interruption state.
    """

    def __init__(
        self,
        service: InterviewService,
        store: Store,
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.service = service
        self.store = store
        self.clock = clock
        self._states: dict[str, VoiceSessionState] = {}

    def state(self, session_id: str) -> VoiceSessionState:
        state = self._states.setdefault(
            session_id,
            VoiceSessionState(session_id=session_id),
        )
        return state.model_copy(deep=True)

    def _state_ref(self, session_id: str) -> VoiceSessionState:
        return self._states.setdefault(
            session_id,
            VoiceSessionState(session_id=session_id),
        )

    def _now_ms(self) -> int:
        return max(0, round(self.clock() * 1000))

    async def _session(self, session_id: str):
        session = await self.store.get_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        return session

    @staticmethod
    def _ensure_input_allowed(
        session,
        state: VoiceSessionState,
    ) -> None:
        if session.status is SessionStatus.COMPLETED:
            state.phase = VoicePhase.CLOSED
            raise HTTPException(409, "Interview is already complete")
        if session.status is SessionStatus.CANCELLED:
            state.phase = VoicePhase.CLOSED
            raise HTTPException(409, "Interview is cancelled")

    async def _persist(self, session) -> None:
        try:
            await self.store.put_session(session)
        except StoreConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Voice state changed concurrently. "
                    "Reload the session and retry the voice event."
                ),
            ) from exc

    async def speech_started(self, session_id: str) -> VoiceSessionState:
        session = await self._session(session_id)
        state = self._state_ref(session_id)
        self._ensure_input_allowed(session, state)
        now = self._now_ms()

        if state.phase is VoicePhase.SPEAKING:
            previous_turn = state.active_tts_turn_id
            state.interruption_count += 1
            state.generation += 1
            append_event(
                session,
                EventType.VOICE_BARGE_IN,
                payload={
                    "generation": state.generation,
                    "interrupted_turn_id": previous_turn,
                    "interruption_count": state.interruption_count,
                },
            )
            append_event(
                session,
                EventType.VOICE_TTS_CANCELLED,
                payload={
                    "turn_id": previous_turn,
                    "reason": "barge_in",
                    "generation": state.generation,
                },
            )
            state.active_tts_turn_id = None

        state.phase = VoicePhase.LISTENING
        state.speech_started_at_ms = now
        append_event(
            session,
            EventType.VOICE_SPEECH_STARTED,
            payload={
                "generation": state.generation,
                "started_at_ms": now,
            },
        )
        await self._persist(session)
        return state.model_copy(deep=True)

    async def transcript_partial(
        self,
        session_id: str,
        event: TranscriptEvent,
    ) -> VoiceSessionState:
        session = await self._session(session_id)
        state = self._state_ref(session_id)
        self._ensure_input_allowed(session, state)
        if state.phase is not VoicePhase.LISTENING:
            raise HTTPException(
                409,
                f"Partial transcript received while voice phase is {state.phase.value}",
            )

        append_event(
            session,
            EventType.VOICE_TRANSCRIPT_PARTIAL,
            payload={
                "text": event.text,
                "confidence": event.confidence,
                "generation": state.generation,
            },
        )
        await self._persist(session)
        return state.model_copy(deep=True)

    async def transcript_final(
        self,
        session_id: str,
        event: TranscriptEvent,
    ) -> VoiceTurnResult:
        session = await self._session(session_id)
        state = self._state_ref(session_id)
        self._ensure_input_allowed(session, state)
        if state.phase is not VoicePhase.LISTENING:
            raise HTTPException(
                409,
                f"Final transcript received while voice phase is {state.phase.value}",
            )

        now = self._now_ms()
        if state.speech_started_at_ms is not None:
            state.last_speech_to_final_ms = max(
                0,
                now - state.speech_started_at_ms,
            )

        append_event(
            session,
            EventType.VOICE_TRANSCRIPT_FINAL,
            payload={
                "text": event.text,
                "confidence": event.confidence,
                "generation": state.generation,
                "speech_to_final_ms": state.last_speech_to_final_ms,
            },
        )
        await self._persist(session)

        state.phase = VoicePhase.PROCESSING
        response_started = self._now_ms()
        step = await self.service.answer(session_id, event.text)
        response_ready = self._now_ms()
        state.last_final_to_response_ms = max(
            0,
            response_ready - response_started,
        )
        state.response_ready_at_ms = response_ready
        state.active_tts_turn_id = (
            step.interviewer_turn.id
            if step.interviewer_turn
            else None
        )

        current = await self._session(session_id)
        append_event(
            current,
            EventType.VOICE_RESPONSE_READY,
            turn=step.interviewer_turn,
            payload={
                "generation": state.generation,
                "final_to_response_ms": state.last_final_to_response_ms,
                "interviewer_turn_id": (
                    step.interviewer_turn.id
                    if step.interviewer_turn
                    else None
                ),
            },
        )
        await self._persist(current)

        if step.status is SessionStatus.COMPLETED and step.interviewer_turn is None:
            state.phase = VoicePhase.CLOSED

        return VoiceTurnResult(
            state=state.model_copy(deep=True),
            interviewer_turn=step.interviewer_turn,
            tool_invocation=step.tool_invocation,
            completed=step.status is SessionStatus.COMPLETED,
        )

    async def tts_started(
        self,
        session_id: str,
        event: TtsLifecycleEvent,
    ) -> VoiceSessionState:
        session = await self._session(session_id)
        state = self._state_ref(session_id)
        if session.status is SessionStatus.CANCELLED:
            state.phase = VoicePhase.CLOSED
            raise HTTPException(409, "Interview is cancelled")

        known_turn = next(
            (turn for turn in session.turns if turn.id == event.turn_id),
            None,
        )
        if known_turn is None:
            raise HTTPException(400, "TTS event references unknown turn")

        if (
            state.active_tts_turn_id is not None
            and state.active_tts_turn_id != event.turn_id
        ):
            raise HTTPException(
                409,
                "TTS started for a stale interviewer turn",
            )

        now = self._now_ms()
        if state.response_ready_at_ms is not None:
            state.last_response_to_tts_ms = max(
                0,
                now - state.response_ready_at_ms,
            )

        state.phase = VoicePhase.SPEAKING
        state.active_tts_turn_id = event.turn_id
        append_event(
            session,
            EventType.VOICE_TTS_STARTED,
            turn=known_turn,
            payload={
                "generation": state.generation,
                "response_to_tts_ms": state.last_response_to_tts_ms,
            },
        )
        await self._persist(session)
        return state.model_copy(deep=True)

    async def tts_completed(
        self,
        session_id: str,
        event: TtsLifecycleEvent,
    ) -> VoiceSessionState:
        session = await self._session(session_id)
        state = self._state_ref(session_id)

        if state.active_tts_turn_id != event.turn_id:
            raise HTTPException(
                409,
                "TTS completion does not match the active interviewer turn",
            )

        turn = next(
            (item for item in session.turns if item.id == event.turn_id),
            None,
        )
        append_event(
            session,
            EventType.VOICE_TTS_COMPLETED,
            turn=turn,
            payload={"generation": state.generation},
        )
        state.active_tts_turn_id = None
        state.response_ready_at_ms = None
        state.speech_started_at_ms = None
        state.phase = (
            VoicePhase.CLOSED
            if session.status is SessionStatus.COMPLETED
            else VoicePhase.IDLE
        )
        await self._persist(session)
        return state.model_copy(deep=True)

    async def tts_cancelled(
        self,
        session_id: str,
        event: TtsLifecycleEvent,
        *,
        reason: str = "provider_cancelled",
    ) -> VoiceSessionState:
        session = await self._session(session_id)
        state = self._state_ref(session_id)
        if state.active_tts_turn_id != event.turn_id:
            raise HTTPException(
                409,
                "TTS cancellation does not match the active interviewer turn",
            )

        turn = next(
            (item for item in session.turns if item.id == event.turn_id),
            None,
        )
        append_event(
            session,
            EventType.VOICE_TTS_CANCELLED,
            turn=turn,
            payload={
                "generation": state.generation,
                "reason": reason,
            },
        )
        state.active_tts_turn_id = None
        state.response_ready_at_ms = None
        state.phase = VoicePhase.IDLE
        await self._persist(session)
        return state.model_copy(deep=True)


    async def provider_failed(
        self,
        session_id: str,
        *,
        direction: Literal["stt", "tts"],
        provider_id: str,
        error_type: str,
        message: str,
    ) -> None:
        session = await self._session(session_id)
        append_event(
            session,
            EventType.VOICE_PROVIDER_FAILED,
            payload={
                "direction": direction,
                "provider_id": provider_id,
                "error_type": error_type,
                "message": message[:1000],
            },
        )
        await self._persist(session)

    async def transport_selected(
        self,
        session_id: str,
        event: VoiceTransportSelectionEvent,
    ) -> None:
        session = await self._session(session_id)
        append_event(
            session,
            EventType.VOICE_TRANSPORT_SELECTED,
            payload=event.model_dump(
                mode="json",
                exclude_none=True,
            ),
        )
        await self._persist(session)

    async def transport_fallback(
        self,
        session_id: str,
        event: VoiceTransportFallbackEvent,
    ) -> None:
        session = await self._session(session_id)
        append_event(
            session,
            EventType.VOICE_TRANSPORT_FALLBACK,
            payload=event.model_dump(mode="json"),
        )
        await self._persist(session)

    async def vad_endpoint(
        self,
        session_id: str,
        observation: VadObservation,
    ) -> None:
        session = await self._session(session_id)
        state = self._state_ref(session_id)
        append_event(
            session,
            EventType.VOICE_VAD_ENDPOINT,
            payload={
                "generation": state.generation,
                "state": observation.state.value,
                "utterance_ms": observation.utterance_ms,
                "silence_ms": observation.silence_ms,
                "frame_ms": observation.frame_ms,
                "auto_commit_recommended": (
                    observation.auto_commit_recommended
                ),
            },
        )
        await self._persist(session)

    async def close_session(
        self,
        session_id: str,
        *,
        reason: str = "session_cancelled",
    ) -> VoiceSessionState:
        session = await self._session(session_id)
        state = self._state_ref(session_id)

        state.generation += 1
        active_turn_id = state.active_tts_turn_id
        if active_turn_id is not None:
            turn = next(
                (
                    item
                    for item in session.turns
                    if item.id == active_turn_id
                ),
                None,
            )
            append_event(
                session,
                EventType.VOICE_TTS_CANCELLED,
                turn=turn,
                payload={
                    "generation": state.generation,
                    "reason": reason,
                },
            )
            await self._persist(session)

        state.active_tts_turn_id = None
        state.response_ready_at_ms = None
        state.speech_started_at_ms = None
        state.phase = VoicePhase.CLOSED
        return state.model_copy(deep=True)
