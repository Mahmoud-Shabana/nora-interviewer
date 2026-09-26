from __future__ import annotations

from ..models import (
    AgentDecision,
    InterviewSession,
    JobSpec,
    ToolEvaluation,
    ToolInvocation,
    ToolSubmission,
)
from .base import InterviewBrain


class FallbackBrain:
    """Use a deterministic backup and preserve degraded-mode provenance."""

    def __init__(
        self,
        primary: InterviewBrain,
        fallback: InterviewBrain,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    @staticmethod
    def _degraded(
        decision: AgentDecision,
        exc: Exception,
    ) -> AgentDecision:
        return decision.model_copy(
            update={
                "reason": (
                    "degraded_fallback:"
                    f"{type(exc).__name__}:"
                    f"{decision.reason}"
                )
            }
        )

    async def opening(
        self,
        session: InterviewSession,
        job: JobSpec,
    ) -> AgentDecision:
        try:
            return await self.primary.opening(
                session,
                job,
            )
        except Exception as exc:
            decision = await self.fallback.opening(
                session,
                job,
            )
            return self._degraded(
                decision,
                exc,
            )

    async def after_answer(
        self,
        session: InterviewSession,
        job: JobSpec,
    ) -> AgentDecision:
        try:
            return await self.primary.after_answer(
                session,
                job,
            )
        except Exception as exc:
            decision = await self.fallback.after_answer(
                session,
                job,
            )
            return self._degraded(
                decision,
                exc,
            )

    async def after_tool(
        self,
        session: InterviewSession,
        job: JobSpec,
        invocation: ToolInvocation,
        submission: ToolSubmission,
        evaluation: ToolEvaluation,
    ) -> AgentDecision:
        try:
            return await self.primary.after_tool(
                session,
                job,
                invocation,
                submission,
                evaluation,
            )
        except Exception as exc:
            decision = await self.fallback.after_tool(
                session,
                job,
                invocation,
                submission,
                evaluation,
            )
            return self._degraded(
                decision,
                exc,
            )
