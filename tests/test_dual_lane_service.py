import asyncio

from nora_interviewer.models import Competency, CreateSession, JobSpec, QuestionLane
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_service_starts_with_standardized_anchor_and_exports_lane_metadata():
    async def scenario():
        service = InterviewService(InMemoryStore(), RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="dual-job",
            title="Backend Engineer",
            description="Build backend systems",
            max_questions=6,
            anchor_ratio=0.5,
            competencies=[
                Competency(
                    id="debugging",
                    description="debugging",
                    anchor_question="Describe a production incident you debugged.",
                ),
                Competency(
                    id="design",
                    description="system design",
                    anchor_question="Design a service that handles bursts.",
                ),
            ],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="candidate",
            locale="en",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        step = await service.start(session.id)
        assert step.interviewer_turn.metadata["question_lane"] == QuestionLane.ANCHOR.value
        assert step.interviewer_turn.text == "Describe a production incident you debugged."

        trace = await service.export_voxrubric(session.id)
        assert trace.metadata["anchor_turns"] == 1
        assert trace.metadata["anchor_ratio_target"] == 0.5

    run(scenario())
