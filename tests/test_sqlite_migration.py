import asyncio
import sqlite3

from nora_interviewer.models import InterviewSession
from nora_interviewer.sqlite_store import SqliteStore


def run(coro):
    return asyncio.run(coro)


def test_sqlite_store_migrates_legacy_sessions_table(tmp_path):
    path = tmp_path / "legacy.db"

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                candidate_ref TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    store = SqliteStore(path)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(sessions)"
            ).fetchall()
        }
    assert "version" in columns

    async def scenario():
        session = InterviewSession(
            id="session",
            job_id="job",
            candidate_ref="candidate",
            locale="en",
        )
        await store.put_session(session)
        assert session.version == 1

        loaded = await store.get_session("session")
        assert loaded is not None
        assert loaded.version == 1

    run(scenario())
