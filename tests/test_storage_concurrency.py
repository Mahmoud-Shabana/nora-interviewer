import asyncio

import pytest

from nora_interviewer.models import InterviewSession
from nora_interviewer.sqlite_store import SqliteStore
from nora_interviewer.storage import InMemoryStore, StoreConflictError


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_stale_session_writer_is_rejected(store_kind, tmp_path):
    async def scenario():
        store = (
            InMemoryStore()
            if store_kind == "memory"
            else SqliteStore(tmp_path / "nora.db")
        )

        original = InterviewSession(
            id="session",
            job_id="job",
            candidate_ref="candidate",
            locale="en",
        )
        await store.put_session(original)
        assert original.version == 1

        writer_a = await store.get_session("session")
        writer_b = await store.get_session("session")
        assert writer_a is not None
        assert writer_b is not None
        assert writer_a.version == writer_b.version == 1

        writer_a.paused = True
        await store.put_session(writer_a)
        assert writer_a.version == 2

        writer_b.paused = False
        with pytest.raises(StoreConflictError):
            await store.put_session(writer_b)

        current = await store.get_session("session")
        assert current is not None
        assert current.version == 2
        assert current.paused is True

    run(scenario())


def test_memory_store_returns_isolated_session_copies():
    async def scenario():
        store = InMemoryStore()
        session = InterviewSession(
            id="session",
            job_id="job",
            candidate_ref="candidate",
            locale="en",
        )
        await store.put_session(session)

        loaded = await store.get_session("session")
        loaded.paused = True

        untouched = await store.get_session("session")
        assert untouched.paused is False
        assert untouched.version == 1

    run(scenario())
