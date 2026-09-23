import asyncio

from nora_interviewer.models import (
    CancelSessionRequest,
    Competency,
    CreateSession,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore
from nora_interviewer.voice import (
    RealtimeVoiceCoordinator,
    TtsLifecycleEvent,
    VoicePhase,
)


def run(coro):
    return asyncio.run(coro)


def test_session_cancellation_closes_active_voice_generation():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        voice = RealtimeVoiceCoordinator(
            service=service,
            store=store,
        )

        job = await service.create_job(JobSpec(
            id="voice-cancel-job",
            title="Engineer",
            description="Build systems",
            competencies=[
                Competency(
                    id="x",
                    description="systems",
                    anchor_question="Describe a system you built.",
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
        turn = step.interviewer_turn
        assert turn is not None

        speaking = await voice.tts_started(
            session.id,
            TtsLifecycleEvent(turn_id=turn.id),
        )
        assert speaking.phase is VoicePhase.SPEAKING

        await service.cancel_session(
            session.id,
            CancelSessionRequest(reason="Candidate ended the interview."),
        )
        closed = await voice.close_session(
            session.id,
            reason="session_cancelled",
        )

        assert closed.phase is VoicePhase.CLOSED
        assert closed.active_tts_turn_id is None
        assert closed.generation == speaking.generation + 1

        current = await store.get_session(session.id)
        voice_cancel = [
            event
            for event in current.events
            if event.type.value == "voice_tts_cancelled"
        ]
        assert len(voice_cancel) == 1
        assert voice_cancel[0].turn_id == turn.id
        assert voice_cancel[0].payload["reason"] == "session_cancelled"

        try:
            await voice.speech_started(session.id)
            assert False, "expected cancelled voice session conflict"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409

    run(scenario())
