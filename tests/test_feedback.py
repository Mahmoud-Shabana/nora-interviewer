from nora_interviewer.evidence import EvidenceGraph
from nora_interviewer.feedback import build_candidate_feedback
from nora_interviewer.models import (
    Competency,
    EvidenceObservation,
    EvidenceState,
    InterviewSession,
    JobSpec,
    Speaker,
    Turn,
)


def test_feedback_is_evidence_summary_not_final_decision():
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build reliable systems",
        competencies=[
            Competency(id="debugging", description="production debugging"),
            Competency(id="design", description="system design"),
        ],
    )
    answer = Turn(id="a1", speaker=Speaker.CANDIDATE, text="I profiled the incident.")
    session = InterviewSession(
        job_id="job",
        candidate_ref="c",
        locale="en",
        turns=[answer],
    )
    EvidenceGraph.initialize(session, job)
    EvidenceGraph.apply_observation(
        session,
        job,
        EvidenceObservation(
            competency_id="debugging",
            turn_id="a1",
            state=EvidenceState.VERIFIED,
            confidence=0.9,
            note="Concrete verification step.",
        ),
    )

    report = build_candidate_feedback(session, job)
    assert report.supported_evidence[0].competency_id == "debugging"
    assert report.supported_evidence[0].evidence_turn_ids == ["a1"]
    assert report.needs_more_evidence[0].competency_id == "design"
    assert "not a final hiring decision" in report.note
