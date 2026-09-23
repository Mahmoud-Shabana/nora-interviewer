from __future__ import annotations

import asyncio
from typing import Any

from .models import InterviewSession, JobSpec
from .rubric_drafting import RubricDraft
from .storage import StoreConflictError


class PostgresStore:
    """Async PostgreSQL store for multi-instance Nora deployments.

    The pool is created synchronously but opened lazily on first use, which
    keeps application import side-effect free and follows psycopg_pool guidance
    for async pools.
    """

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN cannot be empty")
        if min_size < 0:
            raise ValueError("PostgreSQL pool min_size must be >= 0")
        if max_size < 1:
            raise ValueError("PostgreSQL pool max_size must be >= 1")
        if min_size > max_size:
            raise ValueError("PostgreSQL pool min_size cannot exceed max_size")

        try:
            from psycopg.errors import UniqueViolation
            from psycopg.types.json import Jsonb
            from psycopg_pool import AsyncConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL storage requires the 'postgres' extra: "
                "pip install -e '.[postgres]'"
            ) from exc

        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.timeout_seconds = timeout_seconds
        self._Jsonb = Jsonb
        self._UniqueViolation = UniqueViolation
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_seconds,
            open=False,
        )
        self._open_lock = asyncio.Lock()
        self._opened = False
        self._schema_ready = False

    async def _ensure_open(self) -> None:
        if self._opened and self._schema_ready:
            return

        async with self._open_lock:
            if not self._opened:
                await self._pool.open()
                self._opened = True

            if not self._schema_ready:
                async with self._pool.connection() as connection:
                    await connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS nora_jobs (
                            id TEXT PRIMARY KEY,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL
                                DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    await connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS nora_rubric_drafts (
                            id TEXT PRIMARY KEY,
                            approved_job_id TEXT,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL
                                DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    await connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS nora_sessions (
                            id TEXT PRIMARY KEY,
                            job_id TEXT NOT NULL,
                            candidate_ref TEXT NOT NULL,
                            version BIGINT NOT NULL,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL
                                DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    await connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS
                            idx_nora_sessions_job_id
                        ON nora_sessions(job_id)
                        """
                    )
                    await connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS
                            idx_nora_sessions_candidate_ref
                        ON nora_sessions(candidate_ref)
                        """
                    )
                self._schema_ready = True

    @staticmethod
    def _decode_job(payload: Any) -> JobSpec:
        if isinstance(payload, str):
            return JobSpec.model_validate_json(payload)
        return JobSpec.model_validate(payload)

    @staticmethod
    def _decode_rubric_draft(payload: Any) -> RubricDraft:
        if isinstance(payload, str):
            return RubricDraft.model_validate_json(payload)
        return RubricDraft.model_validate(payload)

    @staticmethod
    def _decode_session(payload: Any) -> InterviewSession:
        if isinstance(payload, str):
            return InterviewSession.model_validate_json(payload)
        return InterviewSession.model_validate(payload)

    async def put_job(self, job: JobSpec) -> None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO nora_jobs(id, payload, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    job.id,
                    self._Jsonb(
                        job.model_dump(mode="json")
                    ),
                ),
            )

    async def get_job(
        self,
        job_id: str,
    ) -> JobSpec | None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT payload
                FROM nora_jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return self._decode_job(row[0])

    async def put_rubric_draft(
        self,
        draft: RubricDraft,
    ) -> None:
        await self._ensure_open()
        try:
            async with self._pool.connection() as connection:
                await connection.execute(
                    """
                    INSERT INTO nora_rubric_drafts(
                        id,
                        approved_job_id,
                        payload,
                        updated_at
                    )
                    VALUES (
                        %s,
                        NULL,
                        %s,
                        CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        draft.id,
                        self._Jsonb(
                            draft.model_dump(
                                mode="json"
                            )
                        ),
                    ),
                )
        except self._UniqueViolation as exc:
            raise StoreConflictError(
                f"rubric draft {draft.id} already exists"
            ) from exc

    async def get_rubric_draft(
        self,
        draft_id: str,
    ) -> RubricDraft | None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT payload
                FROM nora_rubric_drafts
                WHERE id = %s
                """,
                (draft_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return self._decode_rubric_draft(
            row[0]
        )

    async def approve_rubric_draft(
        self,
        draft_id: str,
        approved_draft: RubricDraft,
        job: JobSpec,
    ) -> None:
        await self._ensure_open()
        try:
            async with self._pool.connection() as connection:
                cursor = await connection.execute(
                    """
                    SELECT approved_job_id
                    FROM nora_rubric_drafts
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (draft_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise KeyError(
                        f"rubric draft {draft_id} not found"
                    )
                if row[0] is not None:
                    raise StoreConflictError(
                        f"rubric draft {draft_id} is already approved"
                    )

                await connection.execute(
                    """
                    INSERT INTO nora_jobs(
                        id,
                        payload,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        job.id,
                        self._Jsonb(
                            job.model_dump(
                                mode="json"
                            )
                        ),
                    ),
                )
                updated = await connection.execute(
                    """
                    UPDATE nora_rubric_drafts
                    SET
                        approved_job_id = %s,
                        payload = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND approved_job_id IS NULL
                    RETURNING id
                    """,
                    (
                        job.id,
                        self._Jsonb(
                            approved_draft.model_dump(
                                mode="json"
                            )
                        ),
                        draft_id,
                    ),
                )
                if await updated.fetchone() is None:
                    raise StoreConflictError(
                        f"rubric draft {draft_id} was approved concurrently"
                    )
        except self._UniqueViolation as exc:
            raise StoreConflictError(
                f"job {job.id} already exists"
            ) from exc

    async def put_session(
        self,
        session: InterviewSession,
    ) -> None:
        await self._ensure_open()

        expected_version = session.version
        next_version = expected_version + 1
        stored = session.model_copy(deep=True)
        stored.version = next_version
        payload = self._Jsonb(
            stored.model_dump(mode="json")
        )

        async with self._pool.connection() as connection:
            if expected_version == 0:
                try:
                    await connection.execute(
                        """
                        INSERT INTO nora_sessions(
                            id,
                            job_id,
                            candidate_ref,
                            version,
                            payload,
                            updated_at
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            session.id,
                            session.job_id,
                            session.candidate_ref,
                            next_version,
                            payload,
                        ),
                    )
                except self._UniqueViolation as exc:
                    raise StoreConflictError(
                        f"session {session.id} was created concurrently"
                    ) from exc
            else:
                cursor = await connection.execute(
                    """
                    UPDATE nora_sessions
                    SET
                        job_id = %s,
                        candidate_ref = %s,
                        version = %s,
                        payload = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND version = %s
                    RETURNING version
                    """,
                    (
                        session.job_id,
                        session.candidate_ref,
                        next_version,
                        payload,
                        session.id,
                        expected_version,
                    ),
                )
                updated = await cursor.fetchone()
                if updated is None:
                    current_cursor = await connection.execute(
                        """
                        SELECT version
                        FROM nora_sessions
                        WHERE id = %s
                        """,
                        (session.id,),
                    )
                    current = await current_cursor.fetchone()
                    current_version = (
                        int(current[0])
                        if current is not None
                        else None
                    )
                    raise StoreConflictError(
                        f"stale session {session.id}: expected version "
                        f"{current_version}, got {expected_version}"
                    )

        session.version = next_version

    async def get_session(
        self,
        session_id: str,
    ) -> InterviewSession | None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT payload
                FROM nora_sessions
                WHERE id = %s
                """,
                (session_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return self._decode_session(row[0])

    async def list_sessions(
        self,
    ) -> list[InterviewSession]:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT payload
                FROM nora_sessions
                ORDER BY updated_at ASC, id ASC
                """
            )
            rows = await cursor.fetchall()

        return [
            self._decode_session(row[0])
            for row in rows
        ]

    async def delete_session(
        self,
        session_id: str,
    ) -> bool:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM nora_sessions
                WHERE id = %s
                RETURNING id
                """,
                (session_id,),
            )
            deleted = await cursor.fetchone()
        return deleted is not None

    async def ping(self) -> None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute("SELECT 1")
            row = await cursor.fetchone()
        if row is None or int(row[0]) != 1:
            raise RuntimeError("PostgreSQL readiness probe failed")

    async def close(self) -> None:
        if self._opened:
            await self._pool.close()
            self._opened = False
            self._schema_ready = False
