import asyncio

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
    TranscriptEvent,
    TtsLifecycleEvent,
    VoicePhase,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, milliseconds: int) -> None:
        self.value += milliseconds / 1000


def run(coro):
    return asyncio.run(coro)


def test_barge_in_cancels_active_tts_and_records_voice_latency():
    async def scenario():
        clock = FakeClock()
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        coordinator = RealtimeVoiceCoordinator(
            service=service,
            store=store,
            clock=clock,
        )

        job = await service.create_job(JobSpec(
            id="voice-job",
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
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        step = await service.start(session.id)
        question = step.interviewer_turn
        assert question is not None

        clock.advance_ms(40)
        state = await coordinator.tts_started(
            session.id,
            TtsLifecycleEvent(turn_id=question.id),
        )
        assert state.phase is VoicePhase.SPEAKING

        clock.advance_ms(120)
        state = await coordinator.speech_started(session.id)
        assert state.phase is VoicePhase.LISTENING
        assert state.interruption_count == 1
        assert state.generation == 1

        clock.advance_ms(350)
        partial = await coordinator.transcript_partial(
            session.id,
            TranscriptEvent(text="I started by reproducing"),
        )
        assert partial.phase is VoicePhase.LISTENING

        clock.advance_ms(150)
        result = await coordinator.transcript_final(
            session.id,
            TranscriptEvent(
                text=(
                    "I started by reproducing the issue under the same load, "
                    "then compared traces and metrics before changing one variable."
                ),
                confidence=0.92,
            ),
        )
        assert result.interviewer_turn is not None
        assert result.state.last_speech_to_final_ms == 500
        assert result.state.last_final_to_response_ms >= 0

        current = await store.get_session(session.id)
        event_types = [event.type.value for event in current.events]
        assert "voice_barge_in" in event_types
        assert "voice_tts_cancelled" in event_types
        assert "voice_transcript_partial" in event_types
        assert "voice_transcript_final" in event_types

    run(scenario())


def test_tts_lifecycle_closes_completed_voice_session():
    async def scenario():
        clock = FakeClock()
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        coordinator = RealtimeVoiceCoordinator(
            service=service,
            store=store,
            clock=clock,
        )

        job = await service.create_job(JobSpec(
            id="close-job",
            title="Engineer",
            description="Build systems",
            max_questions=1,
            competencies=[Competency(id="x", description="systems")],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        first = await service.start(session.id)

        await coordinator.tts_started(
            session.id,
            TtsLifecycleEvent(turn_id=first.interviewer_turn.id),
        )
        await coordinator.tts_completed(
            session.id,
            TtsLifecycleEvent(turn_id=first.interviewer_turn.id),
        )

        await coordinator.speech_started(session.id)
        final = await coordinator.transcript_final(
            session.id,
            TranscriptEvent(
                text="I would reproduce the system behavior and measure it before changing anything."
            ),
        )
        assert final.completed is True
        assert final.interviewer_turn is not None

        await coordinator.tts_started(
            session.id,
            TtsLifecycleEvent(turn_id=final.interviewer_turn.id),
        )
        closed = await coordinator.tts_completed(
            session.id,
            TtsLifecycleEvent(turn_id=final.interviewer_turn.id),
        )
        assert closed.phase is VoicePhase.CLOSED

    run(scenario())
