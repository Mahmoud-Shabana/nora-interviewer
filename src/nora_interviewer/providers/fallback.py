from __future__ import annotations

from ..models import AgentDecision, InterviewSession, JobSpec
from .base import InterviewBrain


class FallbackBrain:
    """Use a deterministic backup if the primary provider fails."""

    def __init__(self, primary: InterviewBrain, fallback: InterviewBrain) -> None:
        self.primary = primary
        self.fallback = fallback

    async def opening(self, session: InterviewSession, job: JobSpec) -> AgentDecision:
        try:
            return await self.primary.opening(session, job)
        except Exception:
            return await self.fallback.opening(session, job)

    async def after_answer(self, session: InterviewSession, job: JobSpec) -> AgentDecision:
        try:
            return await self.primary.after_answer(session, job)
        except Exception:
            return await self.fallback.after_answer(session, job)
