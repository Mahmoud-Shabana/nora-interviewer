import asyncio

from nora_interviewer.counterfactual import CounterfactualReplayer
from nora_interviewer.models import (
    AgentDecision,
    Competency,
    InterviewSession,
    JobSpec,
    Speaker,
    Turn,
)


class AlternateBrain:
    async def opening(self, session, job):
        return AgentDecision(
            text="Alternate opening",
            competency_tags=["debugging"],
            reason="test",
        )

    async def after_answer(self, session, job):
        latest = next(
            turn for turn in reversed(session.turns)
            if turn.speaker is Speaker.CANDIDATE
        )
        return AgentDecision(
            text="What evidence verified your debugging hypothesis?",
            competency_tags=["debugging"],
            parent_turn_id=latest.id,
            reason="alternate_followup",
        )


def run(coro):
    return asyncio.run(coro)


def test_counterfactual_replay_compares_policy_without_mutating_session():
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build reliable systems",
        competencies=[
            Competency(id="python", description="Python engineering"),
            Competency(id="debugging", description="production debugging"),
        ],
    )
    q1 = Turn(
        id="q1",
        speaker=Speaker.INTERVIEWER,
        text="Tell me about Python.",
        competency_tags=["python"],
        metadata={"question_lane": "anchor"},
    )
    a1 = Turn(
        id="a1",
        speaker=Speaker.CANDIDATE,
        text="I built a service and measured it.",
        parent_turn_id="q1",
    )
    q2 = Turn(
        id="q2",
        speaker=Speaker.INTERVIEWER,
        text="Now describe a system design trade-off.",
        competency_tags=["python"],
        metadata={"question_lane": "adaptive"},
    )
    session = InterviewSession(
        id="session",
        job_id="job",
        candidate_ref="c",
        locale="en",
        turns=[q1, a1, q2],
        asked_questions=2,
    )
    original = session.model_dump()

    report = run(CounterfactualReplayer().compare(session, job, AlternateBrain()))

    assert len(report.comparisons) == 1
    item = report.comparisons[0]
    assert item.candidate_turn_id == "a1"
    assert item.original_followup is False
    assert item.alternate_followup is True
    assert item.competency_jaccard == 0.0
    assert report.followup_action_agreement == 0.0
    assert session.model_dump() == original
