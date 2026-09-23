import asyncio

from nora_interviewer.evidence_judge import JudgeFinding, JudgeResponse
from nora_interviewer.models import (
    Competency,
    CreateSession,
    EvidenceState,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


class GoodJudge:
    @property
    def judge_id(self) -> str:
        return "good"

    async def evaluate(self, *, question, answer, job, competency_ids):
        return JudgeResponse(findings=[
            JudgeFinding(
                competency_id=competency_ids[0],
                state=EvidenceState.DEMONSTRATED,
                confidence=0.9,
                quote="compared traces",
                rationale="The candidate used direct diagnostic evidence.",
            )
        ])


class BadQuoteJudge:
    @property
    def judge_id(self) -> str:
        return "bad-quote"

    async def evaluate(self, *, question, answer, job, competency_ids):
        return JudgeResponse(findings=[
            JudgeFinding(
                competency_id=competency_ids[0],
                state=EvidenceState.DEMONSTRATED,
                confidence=0.9,
                quote="used a flame graph",
                rationale="Fabricated quote fixture.",
            )
        ])


def run(coro):
    return asyncio.run(coro)


async def build(judge):
    store = InMemoryStore()
    service = InterviewService(
        store,
        RuleBasedBrain(),
        evidence_judge=judge,
    )
    job = await service.create_job(JobSpec(
        id="job",
        title="Engineer",
        description="Build reliable systems",
        competencies=[
            Competency(
                id="debugging",
                description="production debugging",
                anchor_question="Describe a production issue you debugged.",
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
    return store, service, session


def test_service_applies_grounded_semantic_evidence():
    async def scenario():
        store, service, session = await build(GoodJudge())
        step = await service.answer(
            session.id,
            (
                "I reproduced the incident under load, compared traces, "
                "and isolated the failing dependency."
            ),
        )
        assert step.interviewer_turn is not None

        current = await store.get_session(session.id)
        node = current.evidence_graph["debugging"]
        semantic = [
            item for item in node.evidence
            if item.source == "semantic_judge:good"
        ]
        assert len(semantic) == 1
        assert semantic[0].state is EvidenceState.DEMONSTRATED
        assert semantic[0].quote == "compared traces"
        assert any(
            event.type.value == "evidence_observed"
            and event.payload.get("source") == "semantic_judge:good"
            for event in current.events
        )

    run(scenario())


def test_bad_judge_quote_is_audited_but_interview_continues():
    async def scenario():
        store, service, session = await build(BadQuoteJudge())
        step = await service.answer(
            session.id,
            (
                "I reproduced the incident under load, compared traces, "
                "and isolated the failing dependency."
            ),
        )
        assert step.interviewer_turn is not None

        current = await store.get_session(session.id)
        node = current.evidence_graph["debugging"]
        assert any(
            item.source == "candidate_response"
            for item in node.evidence
        )
        assert not any(
            item.source == "semantic_judge:bad-quote"
            for item in node.evidence
        )

        failures = [
            event for event in current.events
            if event.type.value == "evidence_judge_failed"
        ]
        assert len(failures) == 1
        assert failures[0].payload["judge_id"] == "bad-quote"
        assert "literal substring" in failures[0].payload["error"]

    run(scenario())
