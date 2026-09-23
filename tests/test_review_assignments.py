import asyncio

from fastapi import HTTPException

from nora_interviewer.models import (
    Competency,
    InterviewSession,
    JobSpec,
    ReviewAssignmentStatus,
)
from nora_interviewer.review import (
    ReviewAssignmentActionRequest,
    ReviewAssignmentCreateRequest,
    build_recruiter_report,
)
from nora_interviewer.review_service import ReviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


async def setup():
    store = InMemoryStore()
    job = JobSpec(
        id="job",
        title="Backend Engineer",
        description="Build reliable services",
        competencies=[
            Competency(
                id="debugging",
                description="production debugging",
            )
        ],
    )
    session = InterviewSession(
        id="session",
        job_id=job.id,
        candidate_ref="candidate",
        locale="en",
    )
    await store.put_job(job)
    await store.put_session(session)
    return store, ReviewService(store), job, session


def test_review_assignment_lifecycle_is_audited_and_owned():
    async def scenario():
        store, service, job, session = await setup()

        assignment = await service.assign(
            session.id,
            ReviewAssignmentCreateRequest(
                reviewer_id="reviewer-a",
                note="Please validate conflicting evidence.",
            ),
            assigned_by="recruiter-1",
        )
        assert assignment.status is ReviewAssignmentStatus.OPEN
        assert assignment.reviewer_id == "reviewer-a"
        assert assignment.assigned_by == "recruiter-1"

        try:
            await service.assign(
                session.id,
                ReviewAssignmentCreateRequest(
                    reviewer_id="reviewer-b",
                ),
                assigned_by="recruiter-1",
            )
            assert False, "expected active assignment conflict"
        except HTTPException as exc:
            assert exc.status_code == 409

        try:
            await service.start_assignment(
                session.id,
                assignment.id,
                reviewer_id="reviewer-b",
            )
            assert False, "expected reviewer ownership rejection"
        except HTTPException as exc:
            assert exc.status_code == 403

        started = await service.start_assignment(
            session.id,
            assignment.id,
            reviewer_id="reviewer-a",
        )
        assert started.status is ReviewAssignmentStatus.IN_REVIEW
        assert started.started_at is not None

        try:
            await service.complete_assignment(
                session.id,
                assignment.id,
                ReviewAssignmentActionRequest(
                    note="Wrong reviewer.",
                ),
                reviewer_id="reviewer-b",
            )
            assert False, "expected reviewer ownership rejection"
        except HTTPException as exc:
            assert exc.status_code == 403

        completed = await service.complete_assignment(
            session.id,
            assignment.id,
            ReviewAssignmentActionRequest(
                note="Reviewed evidence and audit history.",
            ),
            reviewer_id="reviewer-a",
        )
        assert completed.status is ReviewAssignmentStatus.COMPLETED
        assert completed.completed_at is not None
        assert "audit history" in completed.completion_note

        current = await store.get_session(session.id)
        event_types = [
            event.type.value
            for event in current.events
        ]
        assert event_types[-3:] == [
            "review_assigned",
            "review_started",
            "review_completed",
        ]

        report = build_recruiter_report(
            current,
            job,
        )
        assert len(report.review_assignments) == 1
        assert (
            report.review_assignments[0].status
            is ReviewAssignmentStatus.COMPLETED
        )

        # Completed history does not block a later independent review.
        second = await service.assign(
            session.id,
            ReviewAssignmentCreateRequest(
                reviewer_id="reviewer-b",
            ),
            assigned_by="recruiter-2",
        )
        assert second.status is ReviewAssignmentStatus.OPEN

    run(scenario())


def test_review_assignment_requires_start_before_completion():
    async def scenario():
        _, service, _, session = await setup()
        assignment = await service.assign(
            session.id,
            ReviewAssignmentCreateRequest(
                reviewer_id="reviewer-a",
            ),
            assigned_by="recruiter",
        )

        try:
            await service.complete_assignment(
                session.id,
                assignment.id,
                ReviewAssignmentActionRequest(
                    note="Premature completion.",
                ),
                reviewer_id="reviewer-a",
            )
            assert False, "expected lifecycle conflict"
        except HTTPException as exc:
            assert exc.status_code == 409

    run(scenario())


def test_recruiter_can_cancel_active_assignment_but_not_completed_one():
    async def scenario():
        _, service, _, session = await setup()
        assignment = await service.assign(
            session.id,
            ReviewAssignmentCreateRequest(
                reviewer_id="reviewer-a",
            ),
            assigned_by="recruiter",
        )

        cancelled = await service.cancel_assignment(
            session.id,
            assignment.id,
            ReviewAssignmentActionRequest(
                note="Reviewer unavailable.",
            ),
            cancelled_by="recruiter",
        )
        assert cancelled.status is ReviewAssignmentStatus.CANCELLED
        assert cancelled.cancelled_at is not None
        assert cancelled.cancellation_reason == "Reviewer unavailable."

        try:
            await service.start_assignment(
                session.id,
                assignment.id,
                reviewer_id="reviewer-a",
            )
            assert False, "cancelled assignment must stay terminal"
        except HTTPException as exc:
            assert exc.status_code == 409

    run(scenario())
