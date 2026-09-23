import os
from uuid import uuid4

import pytest

from nora_interviewer.models import (
    Competency,
    InterviewSession,
    JobSpec,
)
from nora_interviewer.postgres_store import PostgresStore
from nora_interviewer.storage import StoreConflictError


DSN = os.getenv("NORA_TEST_POSTGRES_DSN")


@pytest.mark.skipif(
    not DSN,
    reason="NORA_TEST_POSTGRES_DSN is not configured",
)
@pytest.mark.asyncio
async def test_postgres_store_roundtrip_and_stale_writer_detection():
    store = PostgresStore(
        DSN,
        min_size=0,
        max_size=2,
    )

    suffix = str(uuid4())
    job = JobSpec(
        id=f"pg-job-{suffix}",
        title="Engineer",
        description="PostgreSQL integration fixture.",
        competencies=[
            Competency(
                id="systems",
                description="systems",
            )
        ],
    )
    session = InterviewSession(
        id=f"pg-session-{suffix}",
        job_id=job.id,
        candidate_ref=f"candidate-{suffix}",
        locale="en",
    )

    try:
        await store.put_job(job)
        loaded_job = await store.get_job(job.id)
        assert loaded_job is not None
        assert loaded_job.id == job.id

        await store.put_session(session)
        assert session.version == 1

        writer_a = await store.get_session(session.id)
        writer_b = await store.get_session(session.id)
        assert writer_a is not None
        assert writer_b is not None

        writer_a.paused = True
        await store.put_session(writer_a)
        assert writer_a.version == 2

        writer_b.paused = False
        with pytest.raises(StoreConflictError):
            await store.put_session(writer_b)

        current = await store.get_session(session.id)
        assert current is not None
        assert current.version == 2
        assert current.paused is True

        listed = await store.list_sessions()
        assert session.id in {
            item.id for item in listed
        }

        assert await store.delete_session(session.id) is True
        assert await store.get_session(session.id) is None
    finally:
        await store.delete_session(session.id)
        await store.close()
