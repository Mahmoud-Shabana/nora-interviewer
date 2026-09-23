from __future__ import annotations

import asyncio
from typing import Protocol

from .models import InterviewSession, JobSpec


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


class InMemoryStore:
    """Process-local store for tests and zero-config demos."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobSpec] = {}
        self.sessions: dict[str, InterviewSession] = {}
        self._lock = asyncio.Lock()

    async def put_job(self, job: JobSpec) -> None:
        async with self._lock:
            self.jobs[job.id] = job

    async def get_job(self, job_id: str) -> JobSpec | None:
        return self.jobs.get(job_id)

    async def put_session(
        self,
        session: InterviewSession,
    ) -> None:
        async with self._lock:
            self.sessions[session.id] = session

    async def get_session(
        self,
        session_id: str,
    ) -> InterviewSession | None:
        return self.sessions.get(session_id)
