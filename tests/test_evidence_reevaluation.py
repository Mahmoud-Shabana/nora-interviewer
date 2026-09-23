import asyncio

from nora_interviewer.evidence_judge import JudgeFinding, JudgeResponse
from nora_interviewer.models import (
    Competency,
    CreateSession,
    EvidenceState,
    JobSpec,
    Speaker,
    TranscriptCorrectionRequest,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


class SequenceJudge:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    @property
    def judge_id(self) -> str:
        return "sequence"

    async def evaluate(self, *, question, answer, job, competency_ids):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def finding(quote: str) -> JudgeResponse:
    return JudgeResponse(
        findings=[
            JudgeFinding(
                competency_id="debugging",
                state=EvidenceState.DEMONSTRATED,
                confidence=0.9,
                quote=quote,
                rationale="Grounded diagnostic evidence.",
            )
        ]
    )


def run(coro):
    return asyncio.run(coro)


async def build(judge):
    store = InMemoryStore()
    service = InterviewService(
        store,
        RuleBasedBrain(),
        evidence_judge=judge,
    )
    job = await service.create_job(
        JobSpec(
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
        )
    )
    session = await service.create_session(
        CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        )
    )
    await service.start(session.id)
    await service.answer(
        session.id,
        "I reproduced the incident and compared traces before changing anything.",
    )
    current = await store.get_session(session.id)
    answer = next(
        turn
        for turn in current.turns
        if turn.speaker is Speaker.CANDIDATE
    )
    return store, service, session.id, answer.id


def test_transcript_correction_supersedes_old_semantic_evidence():
    async def scenario():
        store, service, session_id, answer_id = await build(
            SequenceJudge([finding("compared traces")])
        )

        before = await store.get_session(session_id)
        semantic = [
            item
            for item in before.evidence_graph["debugging"].evidence
            if item.source == "semantic_judge:sequence"
        ]
        assert len(semantic) == 1
        assert semantic[0].active is True
        assert before.evidence_graph["debugging"].state is EvidenceState.DEMONSTRATED

        await service.correct_transcript(
            session_id,
            TranscriptCorrectionRequest(
                turn_id=answer_id,
                corrected_text=(
                    "I reproduced the incident and compared metrics "
                    "before changing anything."
                ),
                reason="STT corrected by candidate",
            ),
        )

        after = await store.get_session(session_id)
        old = next(
            item
            for item in after.evidence_graph["debugging"].evidence
            if item.source == "semantic_judge:sequence"
        )
        assert old.active is False
        assert after.evidence_graph["debugging"].state is EvidenceState.CLAIMED
        assert any(
            event.type.value == "evidence_superseded"
            and event.payload["evidence_id"] == old.id
            for event in after.events
        )

    run(scenario())


def test_failed_reevaluation_keeps_existing_semantic_evidence_active():
    async def scenario():
        judge = SequenceJudge([
            finding("compared traces"),
            finding("fabricated quote"),
        ])
        store, service, session_id, answer_id = await build(judge)

        failed_run = await service.reevaluate_evidence(
            session_id,
            answer_id,
        )
        assert failed_run.error_type is not None

        current = await store.get_session(session_id)
        semantic = [
            item
            for item in current.evidence_graph["debugging"].evidence
            if item.source == "semantic_judge:sequence"
        ]
        assert len(semantic) == 1
        assert semantic[0].active is True
        assert current.evidence_graph["debugging"].state is EvidenceState.DEMONSTRATED
        assert len(current.evidence_judge_runs) == 2
        assert current.evidence_judge_runs[-1].error is not None

    run(scenario())


def test_successful_reevaluation_links_runs_and_replaces_active_semantic_evidence():
    async def scenario():
        judge = SequenceJudge([
            finding("compared traces"),
            finding("compared metrics"),
        ])
        store, service, session_id, answer_id = await build(judge)

        before = await store.get_session(session_id)
        first_run = before.evidence_judge_runs[0]

        await service.correct_transcript(
            session_id,
            TranscriptCorrectionRequest(
                turn_id=answer_id,
                corrected_text=(
                    "I reproduced the incident and compared metrics "
                    "before changing anything."
                ),
                reason="Candidate corrected transcript",
            ),
        )
        second_run = await service.reevaluate_evidence(
            session_id,
            answer_id,
        )

        assert second_run.error is None
        assert second_run.supersedes_run_id == first_run.id
        assert second_run.observation_ids

        current = await store.get_session(session_id)
        semantic = [
            item
            for item in current.evidence_graph["debugging"].evidence
            if item.source == "semantic_judge:sequence"
        ]
        assert len(semantic) == 2
        assert sum(item.active for item in semantic) == 1
        active = next(item for item in semantic if item.active)
        assert active.quote == "compared metrics"
        assert active.judge_run_id == second_run.id
        assert current.evidence_graph["debugging"].state is EvidenceState.DEMONSTRATED

    run(scenario())
