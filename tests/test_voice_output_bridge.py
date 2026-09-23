import asyncio

import pytest

from nora_interviewer.models import (
    Competency,
    CreateSession,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.providers.streaming_tts import (
    TtsAudioChunk,
    TtsAudioConfig,
)
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore
from nora_interviewer.voice import (
    RealtimeVoiceCoordinator,
    VoicePhase,
)
from nora_interviewer.voice_output import (
    TtsStreamConflictError,
)
from nora_interviewer.voice_output_bridge import (
    VoiceOutputBridge,
)


def run(coro):
    return asyncio.run(coro)


class FakeTtsSession:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.cancelled = False
        self.closed = False

    async def chunks(self):
        for chunk in self._chunks:
            yield chunk

    async def cancel(self):
        self.cancelled = True

    async def close(self):
        self.closed = True


class FakeTtsProvider:
    provider_id = "fake"

    def __init__(self, chunks):
        self.chunks_to_emit = chunks
        self.calls = []
        self.sessions = []

    async def synthesize(
        self,
        *,
        text,
        locale,
        generation,
        config,
    ):
        session = FakeTtsSession(
            self.chunks_to_emit
        )
        self.calls.append({
            "text": text,
            "locale": locale,
            "generation": generation,
            "config": config,
        })
        self.sessions.append(session)
        return session


async def setup_bridge(chunks):
    store = InMemoryStore()
    service = InterviewService(
        store,
        RuleBasedBrain(),
    )
    voice = RealtimeVoiceCoordinator(
        service=service,
        store=store,
    )
    provider = FakeTtsProvider(chunks)
    bridge = VoiceOutputBridge(
        store=store,
        provider=provider,
        voice=voice,
    )

    job = await service.create_job(
        JobSpec(
            id="tts-job",
            title="Engineer",
            description="Build systems",
            competencies=[
                Competency(
                    id="debugging",
                    description="production debugging",
                    anchor_question=(
                        "Describe a production incident."
                    ),
                )
            ],
        )
    )
    session = await service.create_session(
        CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        )
    )
    step = await service.start(session.id)
    return (
        store,
        service,
        voice,
        provider,
        bridge,
        session.id,
        step.interviewer_turn,
    )


def test_output_bridge_streams_interviewer_audio_and_completes_voice_state():
    async def scenario():
        chunks = [
            TtsAudioChunk(
                sequence=0,
                generation=0,
                audio=b"one",
            ),
            TtsAudioChunk(
                sequence=1,
                generation=0,
                audio=b"two",
            ),
        ]
        (
            store,
            service,
            voice,
            provider,
            bridge,
            session_id,
            turn,
        ) = await setup_bridge(chunks)

        opened = await bridge.open(
            session_id=session_id,
            turn_id=turn.id,
            locale=None,
            config=TtsAudioConfig(),
        )

        assert voice.state(
            session_id
        ).phase is VoicePhase.SPEAKING
        assert provider.calls[0]["text"] == turn.text
        assert provider.calls[0]["locale"] == "en"

        received = [
            chunk
            async for chunk in bridge.chunks(
                stream_id=opened.state.stream_id
            )
        ]
        assert [chunk.audio for chunk in received] == [
            b"one",
            b"two",
        ]

        state = voice.state(session_id)
        assert state.phase is VoicePhase.IDLE
        assert state.active_tts_turn_id is None

        current = await store.get_session(session_id)
        event_types = [
            event.type.value
            for event in current.events
        ]
        assert "voice_tts_started" in event_types
        assert "voice_tts_completed" in event_types

    run(scenario())


def test_output_bridge_barge_in_cancels_provider_without_duplicate_voice_event():
    async def scenario():
        (
            store,
            service,
            voice,
            provider,
            bridge,
            session_id,
            turn,
        ) = await setup_bridge([])

        opened = await bridge.open(
            session_id=session_id,
            turn_id=turn.id,
            locale="en",
            config=TtsAudioConfig(),
        )

        await voice.speech_started(session_id)
        cancelled = await bridge.cancel_active(
            session_id=session_id,
            reason="barge_in",
        )

        assert cancelled is True
        assert provider.sessions[0].cancelled is True
        assert voice.state(
            session_id
        ).phase is VoicePhase.LISTENING
        assert voice.state(
            session_id
        ).generation == 1

        current = await store.get_session(session_id)
        barge_events = [
            event
            for event in current.events
            if event.type.value == "voice_barge_in"
        ]
        cancel_events = [
            event
            for event in current.events
            if event.type.value == "voice_tts_cancelled"
        ]
        assert len(barge_events) == 1
        assert len(cancel_events) == 1

        with pytest.raises(Exception):
            bridge.state(opened.state.stream_id)

    run(scenario())


def test_output_bridge_prevents_two_active_tts_streams_for_session():
    async def scenario():
        (
            _store,
            _service,
            _voice,
            _provider,
            bridge,
            session_id,
            turn,
        ) = await setup_bridge([])

        await bridge.open(
            session_id=session_id,
            turn_id=turn.id,
            locale="en",
            config=TtsAudioConfig(),
        )

        with pytest.raises(
            TtsStreamConflictError,
            match="active TTS stream",
        ):
            await bridge.open(
                session_id=session_id,
                turn_id=turn.id,
                locale="en",
                config=TtsAudioConfig(),
            )

    run(scenario())
