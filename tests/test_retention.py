import asyncio
from datetime import datetime, timedelta, timezone

from nora_interviewer.models import InterviewSession
from nora_interviewer.retention import (
    RetentionManager,
    RetentionRequest,
)
from nora_interviewer.storage import InMemoryStore


NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def session(
    session_id: str,
    *,
    candidate_ref: str,
    created_days_ago: int,
    completed_days_ago: int | None,
):
    created_at = NOW - timedelta(
        days=created_days_ago
    )
    completed_at = (
        NOW - timedelta(days=completed_days_ago)
        if completed_days_ago is not None
        else None
    )
    return InterviewSession(
        id=session_id,
        job_id="job",
        candidate_ref=candidate_ref,
        locale="en",
        created_at=created_at,
        completed_at=completed_at,
    )


def test_retention_defaults_to_dry_run_and_completed_sessions_only():
    async def scenario():
        store = InMemoryStore()
        await store.put_session(
            session(
                "old-complete",
                candidate_ref="a",
                created_days_ago=120,
                completed_days_ago=100,
            )
        )
        await store.put_session(
            session(
                "old-active",
                candidate_ref="b",
                created_days_ago=120,
                completed_days_ago=None,
            )
        )

        report = await RetentionManager(
            store,
            now=lambda: NOW,
        ).run(
            RetentionRequest(
                max_age_days=90,
            )
        )

        assert report.dry_run is True
        assert [item.session_id for item in report.matched] == [
            "old-complete"
        ]
        assert report.deleted_session_ids == []
        assert report.skipped_active_session_ids == [
            "old-active"
        ]
        assert await store.get_session("old-complete") is not None

    run(scenario())


def test_retention_deletes_only_matches_when_explicitly_enabled():
    async def scenario():
        store = InMemoryStore()
        await store.put_session(
            session(
                "expired",
                candidate_ref="a",
                created_days_ago=120,
                completed_days_ago=100,
            )
        )
        await store.put_session(
            session(
                "recent",
                candidate_ref="a",
                created_days_ago=30,
                completed_days_ago=20,
            )
        )

        report = await RetentionManager(
            store,
            now=lambda: NOW,
        ).run(
            RetentionRequest(
                max_age_days=90,
                dry_run=False,
            )
        )

        assert report.deleted_session_ids == ["expired"]
        assert await store.get_session("expired") is None
        assert await store.get_session("recent") is not None

    run(scenario())


def test_retention_can_scope_to_candidate_reference():
    async def scenario():
        store = InMemoryStore()
        for session_id, candidate_ref in [
            ("a-old", "a"),
            ("b-old", "b"),
        ]:
            await store.put_session(
                session(
                    session_id,
                    candidate_ref=candidate_ref,
                    created_days_ago=120,
                    completed_days_ago=100,
                )
            )

        report = await RetentionManager(
            store,
            now=lambda: NOW,
        ).run(
            RetentionRequest(
                max_age_days=90,
                candidate_ref="a",
            )
        )

        assert [item.session_id for item in report.matched] == [
            "a-old"
        ]

    run(scenario())
