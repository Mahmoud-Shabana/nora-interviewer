from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from .models import InterviewSession, JobSpec


class SqliteStore:
    """Durable local Nora store backed by SQLite.

    Sessions are stored as canonical Pydantic JSON documents so the complete
    event log, evidence graph, tools, appeals, and voice metadata persist
    together.

    This implementation is intended for local development, demos, and single-
    process deployments. Production multi-instance deployments should use a
    database backend with explicit concurrency/versioning semantics.
    """

    def __init__(
        self,
        path: str | Path,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._lock = asyncio.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30.0,
        )
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "PRAGMA journal_mode = WAL"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    candidate_ref TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_sessions_job_id
                ON sessions(job_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_sessions_candidate_ref
                ON sessions(candidate_ref)
                """
            )

    async def put_job(
        self,
        job: JobSpec,
    ) -> None:
        payload = job.model_dump_json()
        async with self._lock:
            await asyncio.to_thread(
                self._put_job_sync,
                job.id,
                payload,
            )

    def _put_job_sync(
        self,
        job_id: str,
        payload: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(id, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (job_id, payload),
            )

    async def get_job(
        self,
        job_id: str,
    ) -> JobSpec | None:
        payload = await asyncio.to_thread(
            self._get_payload_sync,
            "jobs",
            job_id,
        )
        if payload is None:
            return None
        return JobSpec.model_validate_json(payload)

    async def put_session(
        self,
        session: InterviewSession,
    ) -> None:
        payload = session.model_dump_json()
        async with self._lock:
            await asyncio.to_thread(
                self._put_session_sync,
                session.id,
                session.job_id,
                session.candidate_ref,
                payload,
            )

    def _put_session_sync(
        self,
        session_id: str,
        job_id: str,
        candidate_ref: str,
        payload: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    id,
                    job_id,
                    candidate_ref,
                    payload,
                    updated_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    job_id = excluded.job_id,
                    candidate_ref = excluded.candidate_ref,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    session_id,
                    job_id,
                    candidate_ref,
                    payload,
                ),
            )

    async def get_session(
        self,
        session_id: str,
    ) -> InterviewSession | None:
        payload = await asyncio.to_thread(
            self._get_payload_sync,
            "sessions",
            session_id,
        )
        if payload is None:
            return None
        return InterviewSession.model_validate_json(
            payload
        )

    def _get_payload_sync(
        self,
        table: str,
        object_id: str,
    ) -> str | None:
        if table not in {"jobs", "sessions"}:
            raise ValueError("unsupported SQLite table")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload FROM {table} WHERE id = ?",
                (object_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0])
