import asyncio

from nora_interviewer.models import (
    Competency,
    EvidenceJudgeRun,
    InterviewSession,
    JobSpec,
    Speaker,
    TranscriptRevision,
    Turn,
)
from nora_interviewer.review_service import ReviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def make_session(
    *,
    session_id: str,
    candidate_ref: str,
    run_error: str | None = None,
    run_revision_count: int = 0,
    current_revision_count: int = 0,
):
    question = Turn(
        id=f"{session_id}-q",
        speaker=Speaker.INTERVIEWER,
        text="Describe a production incident.",
        competency_tags=["debugging"],
    )
    answer = Turn(
        id=f"{session_id}-a",
        speaker=Speaker.CANDIDATE,
        text="I compared traces.",
        parent_turn_id=question.id,
    )
    session = InterviewSession(
        id=session_id,
        job_id="job",
        candidate_ref=candidate_ref,
        locale="en",
        turns=[question, answer],
        evidence_judge_runs=[
            EvidenceJudgeRun(
                id=f"{session_id}-run",
                judge_id="judge-a",
                question_turn_id=question.id,
                answer_turn_id=answer.id,
                competency_ids=["debugging"],
                transcript_revision_count=run_revision_count,
                error_type=(
                    "EvidenceJudgeError"
                    if run_error
                    else None
                ),
                error=run_error,
            )
        ],
    )
    for index in range(current_revision_count):
        session.transcript_revisions.append(
            TranscriptRevision(
                id=f"{session_id}-rev-{index}",
                turn_id=answer.id,
                original_text="I compared traces.",
                corrected_text="I compared metrics.",
                reason="candidate correction",
            )
        )
    return session


def test_evidence_reevaluation_queue_prioritizes_failures_then_stale_runs():
    async def scenario():
        store = InMemoryStore()
        await store.put_job(
            JobSpec(
                id="job",
                title="Backend Engineer",
                description="Build reliable services",
                competencies=[
                    Competency(
                        id="debugging",
                        description="production debugging",
                    )
                ],
            )
        )

        failed = make_session(
            session_id="failed",
            candidate_ref="c1",
            run_error="provider timeout",
        )
        stale = make_session(
            session_id="stale",
            candidate_ref="c2",
            run_revision_count=0,
            current_revision_count=1,
        )
        clean = make_session(
            session_id="clean",
            candidate_ref="c3",
        )

        await store.put_session(stale)
        await store.put_session(clean)
        await store.put_session(failed)

        items = await ReviewService(
            store
        ).evidence_reevaluation_queue()

        assert [item.session_id for item in items] == [
            "failed",
            "stale",
        ]
        assert items[0].failed is True
        assert items[0].stale is False
        assert items[1].failed is False
        assert items[1].stale is True
        assert items[1].current_transcript_revision_count == 1

    run(scenario())


def test_evidence_reevaluation_queue_respects_job_filter():
    async def scenario():
        store = InMemoryStore()
        await store.put_job(
            JobSpec(
                id="job",
                title="Backend Engineer",
                description="Build reliable services",
                competencies=[
                    Competency(
                        id="debugging",
                        description="production debugging",
                    )
                ],
            )
        )
        session = make_session(
            session_id="stale",
            candidate_ref="c",
            run_revision_count=0,
            current_revision_count=1,
        )
        await store.put_session(session)

        service = ReviewService(store)
        assert len(
            await service.evidence_reevaluation_queue(
                job_id="job"
            )
        ) == 1
        assert (
            await service.evidence_reevaluation_queue(
                job_id="other"
            )
            == []
        )

    run(scenario())
