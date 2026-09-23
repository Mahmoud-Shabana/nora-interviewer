import asyncio

from fastapi import HTTPException

from nora_interviewer.models import (
    AppealReviewRequest,
    CandidateAppealRequest,
    Competency,
    CreateSession,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_reviewer_can_resolve_appeal_once_and_audit_it():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
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
        appeal = await service.submit_appeal(
            session.id,
            CandidateAppealRequest(
                message="Please review the transcript.",
            ),
        )

        reviewed = await service.review_appeal(
            session.id,
            appeal.id,
            AppealReviewRequest(
                reviewer_id="reviewer-1",
                note="Transcript and audit history were reviewed.",
            ),
        )

        assert reviewed.status.value == "reviewed"
        assert reviewed.reviewed_by == "reviewer-1"
        assert "audit history" in reviewed.review_note

        current = await store.get_session(session.id)
        events = [
            event
            for event in current.events
            if event.type.value == "appeal_reviewed"
        ]
        assert len(events) == 1
        assert events[0].payload["appeal_id"] == appeal.id
        assert events[0].payload["reviewer_id"] == "reviewer-1"

        try:
            await service.review_appeal(
                session.id,
                appeal.id,
                AppealReviewRequest(
                    reviewer_id="reviewer-2",
                    note="Trying to review twice.",
                ),
            )
            assert False, "expected already-reviewed conflict"
        except HTTPException as exc:
            assert exc.status_code == 409

    run(scenario())
