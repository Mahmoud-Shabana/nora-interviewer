import asyncio
import json

from nora_interviewer.evidence_judge import (
    EvidenceJudgeError,
    GroundedEvidenceGate,
    LLMEvidenceJudge,
)
from nora_interviewer.models import (
    Competency,
    EvidenceState,
    JobSpec,
    Speaker,
    Turn,
)


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(self.payload)


def run(coro):
    return asyncio.run(coro)


def fixture():
    job = JobSpec(
        id="job",
        title="Backend Engineer",
        description="Build reliable backend systems",
        competencies=[
            Competency(id="debugging", description="production debugging"),
        ],
    )
    question = Turn(
        id="q1",
        speaker=Speaker.INTERVIEWER,
        text="How did you verify the root cause?",
        competency_tags=["debugging"],
    )
    answer = Turn(
        id="a1",
        speaker=Speaker.CANDIDATE,
        text=(
            "I compared event-loop lag with database query duration, "
            "then reproduced the issue under the same load."
        ),
        parent_turn_id="q1",
    )
    return job, question, answer


def test_llm_evidence_judge_accepts_literal_grounded_quote():
    job, question, answer = fixture()
    judge = LLMEvidenceJudge(
        FakeProvider({
            "findings": [{
                "competency_id": "debugging",
                "state": "demonstrated",
                "confidence": 0.91,
                "quote": "compared event-loop lag with database query duration",
                "rationale": "The candidate compared competing hypotheses using measurements.",
            }]
        }),
        judge_id="test-judge",
    )

    response = run(judge.evaluate(
        question=question,
        answer=answer,
        job=job,
        competency_ids=["debugging"],
    ))
    observations = GroundedEvidenceGate.validate(
        answer=answer,
        response=response,
        judge_id=judge.judge_id,
    )

    assert len(observations) == 1
    assert observations[0].state is EvidenceState.DEMONSTRATED
    assert observations[0].source == "semantic_judge:test-judge"
    assert observations[0].quote in answer.text


def test_grounding_gate_rejects_fabricated_quote():
    job, question, answer = fixture()
    judge = LLMEvidenceJudge(
        FakeProvider({
            "findings": [{
                "competency_id": "debugging",
                "state": "demonstrated",
                "confidence": 0.8,
                "quote": "I used a flame graph and fixed the event loop",
                "rationale": "Specific debugging evidence.",
            }]
        }),
        judge_id="test-judge",
    )

    response = run(judge.evaluate(
        question=question,
        answer=answer,
        job=job,
        competency_ids=["debugging"],
    ))
    try:
        GroundedEvidenceGate.validate(
            answer=answer,
            response=response,
            judge_id=judge.judge_id,
        )
        assert False, "expected EvidenceJudgeError"
    except EvidenceJudgeError as exc:
        assert "literal substring" in str(exc)


def test_judge_rejects_unauthorized_competency():
    job, question, answer = fixture()
    judge = LLMEvidenceJudge(
        FakeProvider({
            "findings": [{
                "competency_id": "leadership",
                "state": "insufficient_evidence",
                "confidence": 0.4,
                "quote": None,
                "rationale": "No evidence.",
            }]
        }),
        judge_id="test-judge",
    )

    try:
        run(judge.evaluate(
            question=question,
            answer=answer,
            job=job,
            competency_ids=["debugging"],
        ))
        assert False, "expected EvidenceJudgeError"
    except EvidenceJudgeError as exc:
        assert "unauthorized competencies" in str(exc)


def test_transcript_judge_schema_rejects_verified_state():
    job, question, answer = fixture()
    judge = LLMEvidenceJudge(
        FakeProvider({
            "findings": [{
                "competency_id": "debugging",
                "state": "verified",
                "confidence": 0.99,
                "quote": "compared event-loop lag with database query duration",
                "rationale": "Strong answer.",
            }]
        }),
        judge_id="test-judge",
    )

    try:
        run(judge.evaluate(
            question=question,
            answer=answer,
            job=job,
            competency_ids=["debugging"],
        ))
        assert False, "expected validation failure"
    except ValueError as exc:
        assert "verified" in str(exc)
