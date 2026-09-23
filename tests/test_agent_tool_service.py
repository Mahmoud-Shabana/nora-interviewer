import asyncio

from fastapi import HTTPException

from nora_interviewer.models import (
    AgentDecision,
    AgentToolRequest,
    Competency,
    CreateSession,
    JobSpec,
    JobToolTemplate,
    Speaker,
)
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


class ToolRequestingBrain:
    async def opening(self, session, job):
        return AgentDecision(
            text="Tell me about your Python experience.",
            competency_tags=["python"],
            reason="opening",
        )

    async def after_answer(self, session, job):
        latest = next(
            turn for turn in reversed(session.turns)
            if turn.speaker is Speaker.CANDIDATE
        )
        return AgentDecision(
            text="Let’s verify that with a coding exercise.",
            competency_tags=["python"],
            parent_turn_id=latest.id,
            tool_request=AgentToolRequest(
                template_id="python-dedupe-events-v1",
            ),
            reason="practical verification",
        )


def run(coro):
    return asyncio.run(coro)


def test_agent_tool_request_is_instantiated_from_server_template():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, ToolRequestingBrain())
        job = await service.create_job(JobSpec(
            id="job",
            title="Python Engineer",
            description="Build Python services",
            competencies=[Competency(id="python", description="Python engineering")],
            tool_templates=[JobToolTemplate(
                template_id="python-dedupe-events-v1",
                purpose="Practical Python verification",
                competency_ids=["python"],
            )],
            max_tools=1,
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="c",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        await service.start(session.id)
        step = await service.answer(
            session.id,
            "I build Python APIs and validate behavior with tests and profiling.",
        )
        assert step.tool_invocation is not None
        assert step.tool_invocation.kind.value == "coding"
        public = step.tool_invocation.model_dump_json()
        assert "hidden_tests" not in public
        assert step.tool_invocation.payload["hidden_test_count"] == 2

        current = await store.get_session(session.id)
        assert len(current.tools) == 1
        assert any(event.type.value == "tool_opened" for event in current.events)

    run(scenario())


def test_unknown_job_template_is_rejected_at_job_creation():
    async def scenario():
        service = InterviewService(InMemoryStore(), ToolRequestingBrain())
        try:
            await service.create_job(JobSpec(
                id="bad-job",
                title="Engineer",
                description="Build systems",
                competencies=[Competency(id="python", description="Python")],
                tool_templates=[JobToolTemplate(
                    template_id="does-not-exist",
                    purpose="Unknown tool",
                    competency_ids=["python"],
                )],
            ))
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "unknown tool template" in str(exc.detail)

    run(scenario())
