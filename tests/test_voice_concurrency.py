import asyncio

from fastapi import HTTPException

from nora_interviewer.models import Competency, CreateSession, JobSpec
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore, StoreConflictError
from nora_interviewer.voice import RealtimeVoiceCoordinator


class ConflictStore(InMemoryStore):
    def __init__(self):
        super().__init__()
        self.fail_next = False

    async def put_session(self, session):
        if self.fail_next:
            self.fail_next = False
            raise StoreConflictError("simulated stale voice writer")
        await super().put_session(session)


def run(coro):
    return asyncio.run(coro)


def test_voice_conflict_is_exposed_as_http_409():
    async def scenario():
        store = ConflictStore()
        service = InterviewService(store, RuleBasedBrain())
        coordinator = RealtimeVoiceCoordinator(
            service=service,
            store=store,
        )

        job = await service.create_job(JobSpec(
            id="job",
            title="Engineer",
            description="Build reliable systems",
            competencies=[Competency(id="x", description="systems")],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))

        store.fail_next = True
        try:
            await coordinator.speech_started(session.id)
            assert False, "expected HTTP 409"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "Voice state changed concurrently" in str(exc.detail)

    run(scenario())
