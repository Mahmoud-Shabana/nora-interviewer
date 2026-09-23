import asyncio

from nora_interviewer.models import (
    Competency,
    CreateSession,
    JobSpec,
    ToolInvocation,
    ToolKind,
    ToolSubmissionRequest,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_generic_tool_defaults_to_manual_review_not_fake_score():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="tool-job",
            title="Analyst",
            description="Analyze a business case",
            competencies=[Competency(id="analysis", description="structured analysis")],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="c",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        invocation = await service.open_tool(
            session.id,
            ToolInvocation(
                kind=ToolKind.CASE_STUDY,
                title="Expansion case",
                instructions="Recommend whether the company should expand.",
                competency_tags=["analysis"],
            ),
        )
        evaluation = await service.submit_tool(
            session.id,
            invocation.id,
            ToolSubmissionRequest(content={"answer": "Expand only after validating retention."}),
        )
        assert evaluation.passed is None
        assert evaluation.score is None
        assert evaluation.evidence["review_required"] is True

        current = await store.get_session(session.id)
        assert current.tools[0].status.value == "evaluated"
        assert current.tool_submissions[0].tool_id == invocation.id

    run(scenario())
