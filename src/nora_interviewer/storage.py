from __future__ import annotations

import asyncio
from typing import Protocol

from .models import InterviewSession, JobSpec


class StoreConflictError(RuntimeError):
    """Raised when a stale session version attempts to overwrite newer state."""


class Store(Protocol):
    """Persistence contract used by Nora orchestration layers."""

    async def put_job(self, job: JobSpec) -> None: ...

    async def get_job(
        self,
        job_id: str,
    ) -> JobSpec | None: ...

    async def put_session(
        self,
        session: InterviewSession,
    ) -> None: ...

    async def get_session(
        self,
        session_id: str,
    ) -> InterviewSession | None: ...

    async def list_sessions(
        self,
    ) -> list[InterviewSession]: ...

    async def delete_session(
        self,
        session_id: str,
    ) -> bool: ...

    async def close(self) -> None: ...


class InMemoryStore:
    """Process-local store with optimistic session versioning."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobSpec] = {}
        self.sessions: dict[str, InterviewSession] = {}
        self._lock = asyncio.Lock()

    async def put_job(self, job: JobSpec) -> None:
        async with self._lock:
            self.jobs[job.id] = job.model_copy(deep=True)

    async def get_job(self, job_id: str) -> JobSpec | None:
        job = self.jobs.get(job_id)
        return job.model_copy(deep=True) if job else None

    async def put_session(
        self,
        session: InterviewSession,
    ) -> None:
        async with self._lock:
            existing = self.sessions.get(session.id)
            expected = session.version

            if existing is None:
                if expected != 0:
                    raise StoreConflictError(
                        f"new session {session.id} must start at version 0"
                    )
                next_version = 1
            else:
                if existing.version != expected:
                    raise StoreConflictError(
                        f"stale session {session.id}: expected version "
                        f"{existing.version}, got {expected}"
                    )
                next_version = expected + 1

            stored = session.model_copy(deep=True)
            stored.version = next_version
            self.sessions[session.id] = stored
            session.version = next_version

    async def get_session(
        self,
        session_id: str,
    ) -> InterviewSession | None:
        session = self.sessions.get(session_id)
        return session.model_copy(deep=True) if session else None

    async def list_sessions(
        self,
    ) -> list[InterviewSession]:
        return [
            session.model_copy(deep=True)
            for session in self.sessions.values()
        ]

    async def delete_session(
        self,
        session_id: str,
    ) -> bool:
        async with self._lock:
            return (
                self.sessions.pop(
                    session_id,
                    None,
                )
                is not None
            )

    async def close(self) -> None:
        return None
