from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import Field

from .models import StrictModel
from .storage import Store


class RetentionRequest(StrictModel):
    max_age_days: int = Field(
        default=90,
        ge=1,
        le=3650,
    )
    completed_only: bool = True
    dry_run: bool = True
    candidate_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )


class RetentionMatch(StrictModel):
    session_id: str
    candidate_ref: str
    age_basis: str
    age_timestamp: datetime


class RetentionReport(StrictModel):
    cutoff: datetime
    dry_run: bool
    completed_only: bool
    scanned_sessions: int
    matched: list[RetentionMatch]
    deleted_session_ids: list[str]
    skipped_active_session_ids: list[str]


class RetentionManager:
    """Apply explicit data-retention rules over the Store contract."""

    def __init__(
        self,
        store: Store,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.now = now or (
            lambda: datetime.now(timezone.utc)
        )

    async def run(
        self,
        request: RetentionRequest,
    ) -> RetentionReport:
        now = self.now()
        if now.tzinfo is None:
            raise ValueError(
                "RetentionManager clock must return timezone-aware datetime"
            )

        cutoff = now - timedelta(
            days=request.max_age_days
        )
        sessions = await self.store.list_sessions()

        matched: list[RetentionMatch] = []
        deleted: list[str] = []
        skipped_active: list[str] = []

        for session in sessions:
            if (
                request.candidate_ref is not None
                and session.candidate_ref
                != request.candidate_ref
            ):
                continue

            if (
                request.completed_only
                and session.completed_at is None
            ):
                skipped_active.append(session.id)
                continue

            if session.completed_at is not None:
                age_timestamp = session.completed_at
                age_basis = "completed_at"
            else:
                age_timestamp = session.created_at
                age_basis = "created_at"

            if age_timestamp > cutoff:
                continue

            matched.append(
                RetentionMatch(
                    session_id=session.id,
                    candidate_ref=session.candidate_ref,
                    age_basis=age_basis,
                    age_timestamp=age_timestamp,
                )
            )

            if not request.dry_run:
                removed = await self.store.delete_session(
                    session.id
                )
                if removed:
                    deleted.append(session.id)

        return RetentionReport(
            cutoff=cutoff,
            dry_run=request.dry_run,
            completed_only=request.completed_only,
            scanned_sessions=len(sessions),
            matched=matched,
            deleted_session_ids=deleted,
            skipped_active_session_ids=skipped_active,
        )
