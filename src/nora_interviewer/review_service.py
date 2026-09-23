from __future__ import annotations

from fastapi import HTTPException

from .review import (
    RecruiterSessionReport,
    ReviewDashboardSummary,
    ReviewQueueItem,
    build_recruiter_report,
    to_queue_item,
)
from .storage import Store


class ReviewService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def session_report(
        self,
        session_id: str,
    ) -> RecruiterSessionReport:
        session = await self.store.get_session(session_id)
        if session is None:
            raise HTTPException(404, "Session not found")

        job = await self.store.get_job(session.job_id)
        if job is None:
            raise HTTPException(
                500,
                "Session references a missing job",
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

        return ReviewDashboardSummary(
            total_sessions=total_sessions,
            review_required=review_required,
            pending_appeals=pending_appeals,
            pending_integrity_signals=pending_integrity,
            unresolved_tools=unresolved_tools,
            completed_sessions=completed_sessions,
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
                -item.pending_appeals,
                -item.integrity_signals,
                -item.unresolved_tools,
                item.session_id,
            ),
        )
