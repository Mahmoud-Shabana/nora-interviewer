from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from .models import InterviewSession, JobSpec
from .storage import StoreConflictError


class SqliteStore:
    """Durable local Nora store backed by SQLite.

    Sessions are stored as canonical Pydantic JSON documents and protected by
    an optimistic version column. Stale writers fail instead of silently
    overwriting newer interview state.
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
                    version INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(sessions)"
                ).fetchall()
            }
            if "version" not in columns:
                connection.execute(
                    """
                    ALTER TABLE sessions
                    ADD COLUMN version INTEGER NOT NULL DEFAULT 0
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
        expected_version = session.version
        next_version = expected_version + 1
        stored = session.model_copy(deep=True)
        stored.version = next_version
        payload = stored.model_dump_json()

        async with self._lock:
            await asyncio.to_thread(
                self._put_session_sync,
                session.id,
                session.job_id,
                session.candidate_ref,
                expected_version,
                next_version,
                payload,
            )

        session.version = next_version

    def _put_session_sync(
        self,
        session_id: str,
        job_id: str,
        candidate_ref: str,
        expected_version: int,
        next_version: int,
        payload: str,
    ) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT version FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()

            if existing is None:
                if expected_version != 0:
                    raise StoreConflictError(
                        f"new session {session_id} must start at version 0"
                    )
                try:
                    connection.execute(
                        """
                        INSERT INTO sessions(
                            id,
                            job_id,
                            candidate_ref,
                            version,
                            payload,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            session_id,
                            job_id,
                            candidate_ref,
                            next_version,
                            payload,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise StoreConflictError(
                        f"session {session_id} was created concurrently"
                    ) from exc
                return

            cursor = connection.execute(
                """
                UPDATE sessions
                SET
                    job_id = ?,
                    candidate_ref = ?,
                    version = ?,
                    payload = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND version = ?
                """,
                (
                    job_id,
                    candidate_ref,
                    next_version,
                    payload,
                    session_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                current = connection.execute(
                    "SELECT version FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                current_version = (
                    int(current[0])
                    if current is not None
                    else None
                )
                raise StoreConflictError(
                    f"stale session {session_id}: expected version "
                    f"{current_version}, got {expected_version}"
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

    async def list_sessions(
        self,
    ) -> list[InterviewSession]:
        payloads = await asyncio.to_thread(
            self._list_session_payloads_sync,
        )
        return [
            InterviewSession.model_validate_json(payload)
            for payload in payloads
        ]

    def _list_session_payloads_sync(
        self,
    ) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM sessions
                ORDER BY updated_at ASC, id ASC
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

    async def delete_session(
        self,
        session_id: str,
    ) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self._delete_session_sync,
                session_id,
            )

    def _delete_session_sync(
        self,
        session_id: str,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
        return cursor.rowcount > 0

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
