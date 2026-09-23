from nora_interviewer.models import Competency, InterviewSession, JobSpec, QuestionLane
from nora_interviewer.planner import DualLanePlanner


def test_dual_lane_planner_forces_standardized_anchors():
    planner = DualLanePlanner()
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build reliable systems",
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
                anchor_question="Design a rate-limited API.",
            ),
            Competency(id="communication", description="technical communication"),
        ],
    )
    session = InterviewSession(job_id="job", candidate_ref="c", locale="en")

    first = planner.next_anchor(session, job)
    assert first is not None
    assert first.competency_tags == ["debugging"]
    assert planner.lane_for(first) is QuestionLane.ANCHOR

    session.asked_questions = 1
    session.asked_anchor_competencies = ["debugging"]
    assert planner.next_anchor(session, job) is None

    session.asked_questions = 3
    second = planner.next_anchor(session, job)
    assert second is not None
    assert second.competency_tags == ["design"]
