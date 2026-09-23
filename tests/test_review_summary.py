import asyncio

from nora_interviewer.models import (
    CandidateAppeal,
    Competency,
    CompetencyEvidence,
    EvidenceState,
    IntegritySignal,
    InterviewSession,
    JobSpec,
    SessionStatus,
)
from nora_interviewer.review_service import ReviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_review_summary_aggregates_active_human_review_work():
    async def scenario():
        store = InMemoryStore()
        job = JobSpec(
            id="job",
            title="Engineer",
            description="Build reliable systems",
            competencies=[Competency(id="x", description="systems")],
        )
        await store.put_job(job)

        clean = InterviewSession(
            id="clean",
            job_id="job",
            candidate_ref="clean-candidate",
            locale="en",
            status=SessionStatus.COMPLETED,
            evidence_graph={
                "x": CompetencyEvidence(
                    competency_id="x",
                    state=EvidenceState.DEMONSTRATED,
                    confidence=0.9,
                )
            },
        )
        flagged = InterviewSession(
            id="flagged",
            job_id="job",
            candidate_ref="flagged-candidate",
            locale="en",
            evidence_graph={
                "x": CompetencyEvidence(
                    competency_id="x",
                    state=EvidenceState.INSUFFICIENT,
                )
            },
            appeals=[
                CandidateAppeal(
                    message="Please review this interview.",
                )
            ],
            integrity_signals=[
                IntegritySignal(
                    kind="possible_external_assistance",
                    confidence=0.4,
                    note="Human review only.",
                )
            ],
        )
        await store.put_session(clean)
        await store.put_session(flagged)

        summary = await ReviewService(store).summary()

        assert summary.total_sessions == 2
        assert summary.completed_sessions == 1
        assert summary.review_required == 1
        assert summary.pending_appeals == 1
        assert summary.pending_integrity_signals == 1
        assert summary.assigned_reviews == 0
        assert summary.unassigned_review_required == 1

    run(scenario())
