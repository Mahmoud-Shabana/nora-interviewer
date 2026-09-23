import asyncio

from nora_interviewer.models import (
    Competency,
    CreateSession,
    EvidenceState,
    JobSpec,
    ToolEvaluation,
    ToolInvocation,
    ToolKind,
    ToolSubmissionRequest,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore
from nora_interviewer.tools import ToolRegistry


class PassingCaseTool:
    kind = ToolKind.CASE_STUDY

    async def evaluate(self, invocation, submission, session, job):
        return ToolEvaluation(
            tool_id=invocation.id,
            submission_id=submission.id,
            passed=True,
            score=0.8,
            summary="Artifact met the configured structural checks.",
            evidence={"check": "deterministic-fixture"},
        )


def run(coro):
    return asyncio.run(coro)


def test_passing_tool_adds_demonstrated_not_verified_evidence():
    async def scenario():
        registry = ToolRegistry()
        registry.register(PassingCaseTool())
        store = InMemoryStore()
        service = InterviewService(
            store,
            RuleBasedBrain(),
            tool_registry=registry,
        )
        job = await service.create_job(JobSpec(
            id="job",
            title="Analyst",
            description="Analyze systems",
            competencies=[
                Competency(id="analysis", description="structured analysis"),
            ],
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
                title="Case",
                instructions="Analyze the scenario.",
                competency_tags=["analysis"],
            ),
        )
        step = await service.submit_tool(
            session.id,
            invocation.id,
            ToolSubmissionRequest(content={"answer": "Evidence-based response"}),
        )
        assert step.evaluation.passed is True

        current = await store.get_session(session.id)
        node = current.evidence_graph["analysis"]
        assert node.state is EvidenceState.DEMONSTRATED
        assert node.state is not EvidenceState.VERIFIED
        tool_evidence = [
            item for item in node.evidence
            if item.source == "tool:case_study"
        ]
        assert len(tool_evidence) == 1
        assert any(
            turn.id == tool_evidence[0].turn_id
            and turn.metadata.get("artifact") is True
            for turn in current.turns
        )

    run(scenario())
