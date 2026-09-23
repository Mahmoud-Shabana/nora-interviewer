from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from .audit import append_event
from .models import (
    EventType,
    InterviewSession,
    JobSpec,
    ReviewAssignment,
    ReviewAssignmentStatus,
)

from .review import (
    EvidenceReevaluationQueueItem,
    RecruiterSessionReport,
    ReviewDashboardSummary,
    ReviewAssignmentActionRequest,
    ReviewAssignmentCreateRequest,
    ReviewQueueItem,
    build_recruiter_report,
    to_queue_item,
)
from .storage import Store, StoreConflictError


class ReviewService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def _get(
        self,
        session_id: str,
    ) -> tuple[InterviewSession, JobSpec]:
        session = await self.store.get_session(
            session_id
        )
        if session is None:
            raise HTTPException(
                404,
                "Session not found",
            )

        job = await self.store.get_job(
            session.job_id
        )
        if job is None:
            raise HTTPException(
                500,
                "Session references a missing job",
            )
        return session, job

    async def _persist(
        self,
        session: InterviewSession,
    ) -> None:
        try:
            await self.store.put_session(
                session
            )
        except StoreConflictError as exc:
            raise HTTPException(
                409,
                (
                    "Review state changed concurrently. "
                    "Reload and retry the operation."
                ),
            ) from exc

    @staticmethod
    def _assignment(
        session: InterviewSession,
        assignment_id: str,
    ) -> ReviewAssignment:
        assignment = next(
            (
                item
                for item in session.review_assignments
                if item.id == assignment_id
            ),
            None,
        )
        if assignment is None:
            raise HTTPException(
                404,
                "Review assignment not found",
            )
        return assignment

    async def assign(
        self,
        session_id: str,
        request: ReviewAssignmentCreateRequest,
        *,
        assigned_by: str,
    ) -> ReviewAssignment:
        session, _ = await self._get(
            session_id
        )
        active = next(
            (
                item
                for item in session.review_assignments
                if item.status in {
                    ReviewAssignmentStatus.OPEN,
                    ReviewAssignmentStatus.IN_REVIEW,
                }
            ),
            None,
        )
        if active is not None:
            raise HTTPException(
                409,
                (
                    "Session already has an active "
                    f"review assignment {active.id}"
                ),
            )

        assignment = ReviewAssignment(
            reviewer_id=request.reviewer_id,
            assigned_by=assigned_by,
            assignment_note=request.note,
        )
        session.review_assignments.append(
            assignment
        )
        append_event(
            session,
            EventType.REVIEW_ASSIGNED,
            payload={
                "assignment_id": assignment.id,
                "reviewer_id": assignment.reviewer_id,
                "assigned_by": assignment.assigned_by,
            },
        )
        await self._persist(session)
        return assignment

    async def start_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        reviewer_id: str,
    ) -> ReviewAssignment:
        session, _ = await self._get(
            session_id
        )
        assignment = self._assignment(
            session,
            assignment_id,
        )
        if assignment.reviewer_id != reviewer_id:
            raise HTTPException(
                403,
                "Review assignment belongs to another reviewer",
            )
        if assignment.status is not ReviewAssignmentStatus.OPEN:
            raise HTTPException(
                409,
                "Only open review assignments can be started",
            )

        assignment.status = ReviewAssignmentStatus.IN_REVIEW
        assignment.started_at = datetime.now(
            timezone.utc
        )
        append_event(
            session,
            EventType.REVIEW_STARTED,
            payload={
                "assignment_id": assignment.id,
                "reviewer_id": reviewer_id,
            },
        )
        await self._persist(session)
        return assignment

    async def complete_assignment(
        self,
        session_id: str,
        assignment_id: str,
        request: ReviewAssignmentActionRequest,
        *,
        reviewer_id: str,
    ) -> ReviewAssignment:
        session, _ = await self._get(
            session_id
        )
        assignment = self._assignment(
            session,
            assignment_id,
        )
        if assignment.reviewer_id != reviewer_id:
            raise HTTPException(
                403,
                "Review assignment belongs to another reviewer",
            )
        if assignment.status is not ReviewAssignmentStatus.IN_REVIEW:
            raise HTTPException(
                409,
                "Only in-review assignments can be completed",
            )

        assignment.status = ReviewAssignmentStatus.COMPLETED
        assignment.completed_at = datetime.now(
            timezone.utc
        )
        assignment.completion_note = request.note
        append_event(
            session,
            EventType.REVIEW_COMPLETED,
            payload={
                "assignment_id": assignment.id,
                "reviewer_id": reviewer_id,
                "note": request.note,
            },
        )
        await self._persist(session)
        return assignment

    async def cancel_assignment(
        self,
        session_id: str,
        assignment_id: str,
        request: ReviewAssignmentActionRequest,
        *,
        cancelled_by: str,
    ) -> ReviewAssignment:
        session, _ = await self._get(
            session_id
        )
        assignment = self._assignment(
            session,
            assignment_id,
        )
        if assignment.status not in {
            ReviewAssignmentStatus.OPEN,
            ReviewAssignmentStatus.IN_REVIEW,
        }:
            raise HTTPException(
                409,
                "Only active review assignments can be cancelled",
            )

        assignment.status = ReviewAssignmentStatus.CANCELLED
        assignment.cancelled_at = datetime.now(
            timezone.utc
        )
        assignment.cancellation_reason = (
            request.note
        )
        append_event(
            session,
            EventType.REVIEW_ASSIGNMENT_CANCELLED,
            payload={
                "assignment_id": assignment.id,
                "reviewer_id": assignment.reviewer_id,
                "cancelled_by": cancelled_by,
                "reason": request.note,
            },
        )
        await self._persist(session)
        return assignment

    async def session_report(
        self,
        session_id: str,
    ) -> RecruiterSessionReport:
        session, job = await self._get(
            session_id
        )
        return build_recruiter_report(
            session,
            job,
        )

    async def summary(self) -> ReviewDashboardSummary:
        sessions = await self.store.list_sessions()

        total_sessions = 0
        review_required = 0
        pending_appeals = 0
        pending_integrity = 0
        unresolved_tools = 0
        stale_evidence_runs = 0
        failed_evidence_runs = 0
        completed_sessions = 0

        for session in sessions:
            job = await self.store.get_job(session.job_id)
            if job is None:
                continue
            total_sessions += 1
            if session.status.value == "completed":
                completed_sessions += 1

            report = build_recruiter_report(
                session,
                job,
            )
            review_required += int(
                report.requires_human_review
            )
            pending_appeals += report.pending_appeals
            pending_integrity += report.integrity_signals
            unresolved_tools += report.unresolved_tools
            stale_evidence_runs += report.stale_evidence_runs
            failed_evidence_runs += report.failed_evidence_runs

        return ReviewDashboardSummary(
            total_sessions=total_sessions,
            review_required=review_required,
            pending_appeals=pending_appeals,
            pending_integrity_signals=pending_integrity,
            unresolved_tools=unresolved_tools,
            stale_evidence_runs=stale_evidence_runs,
            failed_evidence_runs=failed_evidence_runs,
            completed_sessions=completed_sessions,
        )

    async def evidence_reevaluation_queue(
        self,
        *,
        job_id: str | None = None,
    ) -> list[EvidenceReevaluationQueueItem]:
        sessions = await self.store.list_sessions()
        items: list[EvidenceReevaluationQueueItem] = []

        for session in sessions:
            if job_id is not None and session.job_id != job_id:
                continue

            job = await self.store.get_job(session.job_id)
            if job is None:
                continue

            report = build_recruiter_report(
                session,
                job,
            )
            for run in report.evidence_judge_runs:
                if not (run.stale or run.failed):
                    continue
                items.append(
                    EvidenceReevaluationQueueItem(
                        session_id=session.id,
                        job_id=session.job_id,
                        candidate_ref=session.candidate_ref,
                        role=job.title,
                        answer_turn_id=run.answer_turn_id,
                        latest_run_id=run.id,
                        judge_id=run.judge_id,
                        stale=run.stale,
                        failed=run.failed,
                        transcript_revision_count=(
                            run.transcript_revision_count
                        ),
                        current_transcript_revision_count=(
                            run.current_transcript_revision_count
                        ),
                    )
                )

        return sorted(
            items,
            key=lambda item: (
                not item.failed,
                not item.stale,
                item.session_id,
                item.answer_turn_id,
            ),
        )

    async def queue(
        self,
        *,
        requires_review_only: bool = True,
        job_id: str | None = None,
    ) -> list[ReviewQueueItem]:
        sessions = await self.store.list_sessions()
        items: list[ReviewQueueItem] = []

        for session in sessions:
            if job_id is not None and session.job_id != job_id:
                continue

            job = await self.store.get_job(session.job_id)
            if job is None:
                continue

            report = build_recruiter_report(
                session,
                job,
            )
            item = to_queue_item(report)

            if (
                requires_review_only
                and not item.requires_human_review
            ):
                continue

            items.append(item)

        return sorted(
            items,
            key=lambda item: (
                not item.requires_human_review,
                -item.failed_evidence_runs,
                -item.stale_evidence_runs,
                -item.pending_appeals,
                -item.integrity_signals,
                -item.unresolved_tools,
                item.session_id,
            ),
        )
