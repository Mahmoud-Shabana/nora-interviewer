import asyncio

from nora_interviewer.models import (
    Competency,
    EventType,
    InterviewEvent,
    InterviewSession,
    JobSpec,
    Speaker,
    Turn,
)
from nora_interviewer.sqlite_store import SqliteStore


def run(coro):
    return asyncio.run(coro)


def test_sqlite_store_persists_jobs_across_instances(tmp_path):
    async def scenario():
        path = tmp_path / "nora.db"
        first = SqliteStore(path)
        second = SqliteStore(path)

        job = JobSpec(
            id="job-1",
            title="Engineer",
            description="Build reliable systems",
            competencies=[
                Competency(
                    id="debugging",
                    description="production debugging",
                )
            ],
        )
        await first.put_job(job)

        loaded = await second.get_job("job-1")
        assert loaded is not None
        assert loaded.model_dump() == job.model_dump()

    run(scenario())


def test_sqlite_store_round_trips_full_session_state(tmp_path):
    async def scenario():
        path = tmp_path / "nora.db"
        writer = SqliteStore(path)

        session = InterviewSession(
            id="session-1",
            job_id="job-1",
            candidate_ref="candidate-1",
            locale="ar-SA",
            turns=[
                Turn(
                    id="q1",
                    speaker=Speaker.INTERVIEWER,
                    text="Describe the incident.",
                    competency_tags=["debugging"],
                ),
                Turn(
                    id="a1",
                    speaker=Speaker.CANDIDATE,
                    text="قارنت traces و metrics قبل أي تغيير.",
                    parent_turn_id="q1",
                ),
            ],
            events=[
                InterviewEvent(
                    seq=1,
                    type=EventType.SESSION_CREATED,
                    payload={"job_id": "job-1"},
                )
            ],
        )
        await writer.put_session(session)

        reader = SqliteStore(path)
        loaded = await reader.get_session("session-1")

        assert loaded is not None
        assert loaded.model_dump() == session.model_dump()

    run(scenario())


def test_sqlite_store_upserts_updated_session(tmp_path):
    async def scenario():
        path = tmp_path / "nora.db"
        store = SqliteStore(path)

        session = InterviewSession(
            id="session-1",
            job_id="job-1",
            candidate_ref="candidate-1",
            locale="en",
        )
        await store.put_session(session)

        session.paused = True
        session.asked_questions = 3
        await store.put_session(session)

        loaded = await store.get_session("session-1")
        assert loaded is not None
        assert loaded.paused is True
        assert loaded.asked_questions == 3

    run(scenario())


def test_sqlite_store_lists_and_deletes_sessions(tmp_path):
    async def scenario():
        path = tmp_path / "nora.db"
        store = SqliteStore(path)

        first = InterviewSession(
            id="session-a",
            job_id="job",
            candidate_ref="a",
            locale="en",
        )
        second = InterviewSession(
            id="session-b",
            job_id="job",
            candidate_ref="b",
            locale="en",
        )
        await store.put_session(first)
        await store.put_session(second)

        listed = await store.list_sessions()
        assert {item.id for item in listed} == {
            "session-a",
            "session-b",
        }

        assert await store.delete_session("session-a") is True
        assert await store.delete_session("session-a") is False
        assert await store.get_session("session-a") is None
        assert await store.get_session("session-b") is not None

    run(scenario())
