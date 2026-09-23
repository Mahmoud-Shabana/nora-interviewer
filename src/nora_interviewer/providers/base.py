from __future__ import annotations

from typing import AsyncIterator, Protocol

from ..models import (
    AgentDecision,
    InterviewSession,
    JobSpec,
    ToolEvaluation,
    ToolInvocation,
    ToolSubmission,
)


class InterviewBrain(Protocol):
    async def opening(
        self,
        session: InterviewSession,
        job: JobSpec,
    ) -> AgentDecision: ...

    async def after_answer(
        self,
        session: InterviewSession,
        job: JobSpec,
    ) -> AgentDecision: ...

    async def after_tool(
        self,
        session: InterviewSession,
        job: JobSpec,
        invocation: ToolInvocation,
        submission: ToolSubmission,
        evaluation: ToolEvaluation,
    ) -> AgentDecision: ...


class SpeechToTextProvider(Protocol):
    async def transcribe_stream(
        self,
        audio: AsyncIterator[bytes],
        locale: str,
    ) -> AsyncIterator[str]: ...


class TextToSpeechProvider(Protocol):
    async def synthesize_stream(
        self,
        text: str,
        locale: str,
    ) -> AsyncIterator[bytes]: ...
