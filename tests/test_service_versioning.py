import asyncio

from nora_interviewer.models import (
    CandidateControlKind,
    CandidateControlRequest,
    Competency,
    CreateSession,
    JobSpec,
    Speaker,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_live_candidate_correction_uses_one_canonical_session_write():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(store, RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="job",
            title="Engineer",
            description="Build systems",
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
        await service.answer(
            session.id,
            "I reproduced the incident and inspected traces.",
        )

        before = await store.get_session(session.id)
        version_before = before.version

        result = await service.candidate_control(
            session.id,
            CandidateControlRequest(
                kind=CandidateControlKind.CORRECT_LAST_ANSWER,
                text=(
                    "I reproduced the incident under the same load and "
                    "inspected traces before changing one variable."
                ),
            ),
        )

        assert result.target_turn_id is not None

        after = await store.get_session(session.id)
        assert after.version == version_before + 1
        corrected = next(
            turn for turn in after.turns
            if turn.id == result.target_turn_id
            and turn.speaker is Speaker.CANDIDATE
        )
        assert "same load" in corrected.text
        assert len(after.transcript_revisions) == 1

    run(scenario())
