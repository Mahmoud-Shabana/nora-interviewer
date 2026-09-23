import asyncio

from nora_interviewer.audio_stream_manager import AudioStreamManager
from nora_interviewer.models import (
    Competency,
    CreateSession,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore
from nora_interviewer.voice import (
    RealtimeVoiceCoordinator,
    VoicePhase,
)
from nora_interviewer.voice_stream import (
    AudioChunkMessage,
    AudioStreamConfig,
    SpeechRecognitionEvent,
)
from nora_interviewer.voice_stream_bridge import (
    StreamingFinalTranscript,
    StreamingPartialTranscript,
    VoiceStreamBridge,
)


class FakeSpeechSession:
    def __init__(self, events):
        self._events = list(events)
        self.audio = []
        self.closed = False
        self.cancelled = False

    async def push_audio(self, audio: bytes) -> None:
        self.audio.append(audio)

    async def events(self):
        for event in self._events:
            yield event

    async def close(self) -> None:
        self.closed = True

    async def cancel(self) -> None:
        self.cancelled = True


class FakeSpeechProvider:
    def __init__(self, events):
        self.events_to_emit = events
        self.sessions = []

    async def open(self, *, locale, config):
        session = FakeSpeechSession(
            self.events_to_emit
        )
        self.sessions.append(
            (locale, config, session)
        )
        return session


def run(coro):
    return asyncio.run(coro)


def test_bridge_pushes_ordered_audio_and_applies_partial_and_final_transcripts():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(
            store,
            RuleBasedBrain(),
        )
        voice = RealtimeVoiceCoordinator(
            service=service,
            store=store,
        )
        provider = FakeSpeechProvider([
            SpeechRecognitionEvent(
                text="I reproduced the incident",
                is_final=False,
                confidence=0.71,
            ),
            SpeechRecognitionEvent(
                text=(
                    "I reproduced the incident under the same load, "
                    "compared traces and metrics, and changed one variable."
                ),
                is_final=True,
                confidence=0.94,
            ),
        ])
        bridge = VoiceStreamBridge(
            manager=AudioStreamManager(),
            provider=provider,
            voice=voice,
        )

        job = await service.create_job(JobSpec(
            id="voice-stream-job",
            title="Engineer",
            description="Build reliable systems",
            competencies=[
                Competency(
                    id="debugging",
                    description="production debugging",
                    anchor_question="Describe a production incident.",
                )
            ],
        ))
        session = await service.create_session(
            CreateSession(
                job_id=job.id,
                candidate_ref="candidate",
                consent_to_ai_interview=True,
                consent_to_transcript=True,
            )
        )
        await service.start(session.id)

        opened = await bridge.open(
            session_id=session.id,
            locale="en",
            config=AudioStreamConfig(),
        )
        assert opened.state.generation == 0
        assert voice.state(session.id).phase is VoicePhase.LISTENING

        result = await bridge.push_chunk(
            stream_id=opened.state.stream_id,
            chunk=AudioChunkMessage.from_bytes(
                sequence=0,
                generation=0,
                audio=b"audio-frame",
            ),
        )
        assert result.next_sequence == 1
        assert result.buffered_bytes == 0
        assert provider.sessions[0][2].audio == [
            b"audio-frame"
        ]

        events = [
            item
            async for item in bridge.events(
                stream_id=opened.state.stream_id
            )
        ]
        assert len(events) == 2
        assert isinstance(
            events[0],
            StreamingPartialTranscript,
        )
        assert isinstance(
            events[1],
            StreamingFinalTranscript,
        )
        assert events[1].result.interviewer_turn is not None
        assert (
            events[1].result.interviewer_turn.text
        )

        current = await store.get_session(
            session.id
        )
        types = [
            event.type.value
            for event in current.events
        ]
        assert "voice_transcript_partial" in types
        assert "voice_transcript_final" in types
        assert "voice_response_ready" in types

        await bridge.close(
            stream_id=opened.state.stream_id
        )
        assert provider.sessions[0][2].closed is True

    run(scenario())


def test_duplicate_chunk_is_not_pushed_twice_to_provider():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(
            store,
            RuleBasedBrain(),
        )
        voice = RealtimeVoiceCoordinator(
            service=service,
            store=store,
        )
        provider = FakeSpeechProvider([])
        bridge = VoiceStreamBridge(
            manager=AudioStreamManager(),
            provider=provider,
            voice=voice,
        )

        job = await service.create_job(JobSpec(
            id="duplicate-job",
            title="Engineer",
            description="Build reliable systems",
            competencies=[
                Competency(id="x", description="systems")
            ],
        ))
        session = await service.create_session(
            CreateSession(
                job_id=job.id,
                candidate_ref="candidate",
                consent_to_ai_interview=True,
                consent_to_transcript=True,
            )
        )
        await service.start(session.id)
        opened = await bridge.open(
            session_id=session.id,
            locale="en",
            config=AudioStreamConfig(),
        )

        chunk = AudioChunkMessage.from_bytes(
            sequence=0,
            generation=opened.state.generation,
            audio=b"one",
        )
        first = await bridge.push_chunk(
            stream_id=opened.state.stream_id,
            chunk=chunk,
        )
        duplicate = await bridge.push_chunk(
            stream_id=opened.state.stream_id,
            chunk=chunk,
        )

        assert first.duplicate is False
        assert duplicate.duplicate is True
        assert provider.sessions[0][2].audio == [b"one"]

    run(scenario())
