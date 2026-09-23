import asyncio

from fastapi import HTTPException

from nora_interviewer.models import (
    CandidateControlKind,
    CandidateControlRequest,
    Competency,
    CreateSession,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_repeat_does_not_consume_question_budget_or_change_answer_parent():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="controls-job",
            title="Engineer",
            description="Build systems",
            competencies=[Competency(
                id="debugging",
                description="debugging",
                anchor_question="Describe a production incident.",
            )],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="c",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        first = await service.start(session.id)
        original_id = first.interviewer_turn.id

        repeat = await service.candidate_control(
            session.id,
            CandidateControlRequest(kind=CandidateControlKind.REPEAT),
        )
        current = await store.get_session(session.id)
        assert current.asked_questions == 1
        assert repeat.interviewer_turn.text == first.interviewer_turn.text

        await service.answer(
            session.id,
            "I reproduced the incident and compared traces before changing anything.",
        )
        current = await store.get_session(session.id)
        candidate = next(t for t in current.turns if t.speaker.value == "candidate")
        assert candidate.parent_turn_id == original_id

    run(scenario())


def test_thinking_time_pauses_until_resume():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="pause-job",
            title="Engineer",
            description="Build systems",
            competencies=[Competency(id="x", description="x")],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="c",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        await service.start(session.id)
        await service.candidate_control(
            session.id,
            CandidateControlRequest(kind=CandidateControlKind.THINKING_TIME),
        )
        try:
            await service.answer(session.id, "answer")
            assert False, "expected HTTPException while paused"
        except HTTPException as exc:
            assert exc.status_code == 409

        await service.candidate_control(
            session.id,
            CandidateControlRequest(kind=CandidateControlKind.RESUME),
        )
        step = await service.answer(session.id, "A sufficiently detailed answer for the interview.")
        assert step.interviewer_turn is not None

    run(scenario())
