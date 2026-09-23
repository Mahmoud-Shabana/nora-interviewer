import asyncio

from fastapi import HTTPException

from nora_interviewer.models import (
    CancelSessionRequest,
    CandidateControlKind,
    CandidateControlRequest,
    Competency,
    CreateSession,
    JobSpec,
    SessionStatus,
    ToolInvocation,
    ToolKind,
    ToolStatus,
    ToolSubmissionRequest,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_session_cancellation_closes_tools_and_blocks_interview_mutations():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="cancel-job",
            title="Engineer",
            description="Build reliable systems",
            competencies=[
                Competency(
                    id="debugging",
                    description="production debugging",
                    anchor_question="Describe a production incident.",
                )
            ],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        await service.start(session.id)

        tool = await service.open_tool(
            session.id,
            ToolInvocation(
                kind=ToolKind.CASE_STUDY,
                title="Incident case",
                instructions="Analyze the incident.",
                competency_tags=["debugging"],
            ),
        )
        assert tool.status is ToolStatus.OPEN

        cancelled = await service.cancel_session(
            session.id,
            CancelSessionRequest(reason="Candidate withdrew."),
        )

        assert cancelled.status is SessionStatus.CANCELLED
        assert cancelled.cancelled_at is not None
        assert cancelled.cancellation_reason == "Candidate withdrew."
        assert cancelled.paused is False
        assert cancelled.tools[0].status is ToolStatus.CANCELLED

        event_types = [event.type.value for event in cancelled.events]
        assert "tool_cancelled" in event_types
        assert event_types[-1] == "session_cancelled"

        replay = await service.replay(session.id)
        assert replay.status is SessionStatus.CANCELLED
        assert replay.cancelled_tool_ids == [tool.id]

        terminal_start = await service.start(session.id)
        assert terminal_start.status is SessionStatus.CANCELLED
        assert terminal_start.interviewer_turn is None

        for operation in [
            lambda: service.answer(session.id, "A late answer."),
            lambda: service.candidate_control(
                session.id,
                CandidateControlRequest(kind=CandidateControlKind.REPEAT),
            ),
            lambda: service.open_tool(
                session.id,
                ToolInvocation(
                    kind=ToolKind.DOCUMENT,
                    title="Late document",
                    instructions="Should not open.",
                    competency_tags=["debugging"],
                ),
            ),
            lambda: service.submit_tool(
                session.id,
                tool.id,
                ToolSubmissionRequest(content={"answer": "late"}),
            ),
        ]:
            try:
                await operation()
                assert False, "expected cancelled-session conflict"
            except HTTPException as exc:
                assert exc.status_code == 409
                assert "cancel" in str(exc.detail).lower()

    run(scenario())


def test_cancellation_is_idempotent_but_completed_session_cannot_be_cancelled():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="terminal-job",
            title="Engineer",
            description="Build systems",
            max_questions=1,
            competencies=[Competency(id="x", description="systems")],
        ))

        cancelled_session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="c1",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        first = await service.cancel_session(
            cancelled_session.id,
            CancelSessionRequest(reason="Stopped."),
        )
        second = await service.cancel_session(
            cancelled_session.id,
            CancelSessionRequest(reason="Different reason must not rewrite history."),
        )
        assert second.version == first.version
        assert second.cancellation_reason == "Stopped."

        completed_session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="c2",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        await service.start(completed_session.id)
        await service.answer(
            completed_session.id,
            "I measure the system and validate trade-offs with production data.",
        )
        current = await store.get_session(completed_session.id)
        assert current.status is SessionStatus.COMPLETED

        try:
            await service.cancel_session(
                completed_session.id,
                CancelSessionRequest(reason="Too late."),
            )
            assert False, "expected completed-session conflict"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "completed" in str(exc.detail).lower()

    run(scenario())
