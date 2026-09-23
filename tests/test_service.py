import asyncio

from nora_interviewer.models import Competency, CreateSession, JobSpec, SessionStatus
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_adaptive_followup_then_advances():
    async def scenario():
        service = InterviewService(InMemoryStore(), RuleBasedBrain())
        job = await service.create_job(JobSpec(
            id="job",
            title="Python Engineer",
            description="Build reliable APIs",
            competencies=[
                Competency(id="python", description="strong Python engineering"),
                Competency(id="debugging", description="structured production debugging"),
            ],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id, candidate_ref="candidate-001", locale="ar-SA",
            consent_to_ai_interview=True, consent_to_transcript=True,
        ))
        first = await service.start(session.id)
        assert first.status is SessionStatus.RUNNING
        assert first.interviewer_turn.competency_tags == ["python"]
        assert first.interviewer_turn.response_latency_ms is not None

        follow = await service.answer(session.id, "I used FastAPI.")
        assert follow.interviewer_turn.parent_turn_id is not None
        assert follow.interviewer_turn.competency_tags == ["python"]

        long_answer = "I profiled the service under load, isolated blocking calls, moved them to a worker pool, and measured p95 latency before and after the change."
        nxt = await service.answer(session.id, long_answer)
        assert nxt.interviewer_turn.competency_tags == ["debugging"]

        trace = await service.export_voxrubric(session.id)
        assert trace.role == "Python Engineer"
        assert any(t.get("parent_turn_id") for t in trace.turns)

    run(scenario())
