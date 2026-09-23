import asyncio

from fastapi import HTTPException

from nora_interviewer.models import (
    Competency,
    CreateSession,
    IntegrityReviewRequest,
    IntegritySignalRequest,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_integrity_signal_review_is_audited_and_one_time():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="job",
            title="Engineer",
            description="Build systems",
            competencies=[Competency(id="x", description="systems")],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        signal = await service.submit_integrity_signal(
            session.id,
            IntegritySignalRequest(
                kind="possible_external_assistance",
                confidence=0.41,
                note="Timing pattern requires review only.",
                evidence={"gap_ms": 140},
            ),
        )

        reviewed = await service.review_integrity_signal(
            session.id,
            signal.id,
            IntegrityReviewRequest(
                reviewer_id="reviewer-1",
                note="Reviewed alongside transcript; no automatic conclusion.",
            ),
        )

        assert reviewed.review_status.value == "reviewed"
        assert reviewed.reviewed_by == "reviewer-1"
        assert reviewed.requires_human_review is True

        current = await store.get_session(session.id)
        events = [
            event for event in current.events
            if event.type.value == "integrity_reviewed"
        ]
        assert len(events) == 1
        assert events[0].payload["signal_id"] == signal.id

        try:
            await service.review_integrity_signal(
                session.id,
                signal.id,
                IntegrityReviewRequest(
                    reviewer_id="reviewer-2",
                    note="Second review attempt.",
                ),
            )
            assert False, "expected conflict"
        except HTTPException as exc:
            assert exc.status_code == 409

    run(scenario())
