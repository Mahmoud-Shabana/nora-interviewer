from nora_interviewer.evidence import EvidenceGraph
from nora_interviewer.models import (
    Competency,
    EvidenceObservation,
    EvidenceState,
    InterviewSession,
    JobSpec,
    Speaker,
    Turn,
)


def test_claim_does_not_become_verified_without_evaluator():
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build systems",
        competencies=[Competency(id="debugging", description="debugging")],
    )
    q = Turn(id="q1", speaker=Speaker.INTERVIEWER, text="Tell me about debugging.")
    a = Turn(id="a1", speaker=Speaker.CANDIDATE, text="I used tracing.")
    session = InterviewSession(
        job_id="job",
        candidate_ref="c",
        locale="en",
        turns=[q, a],
    )
    EvidenceGraph.initialize(session, job)
    EvidenceGraph.record_candidate_claim(
        session,
        question_turn_id="q1",
        answer_turn_id="a1",
        competency_ids=["debugging"],
    )
    node = session.evidence_graph["debugging"]
    assert node.state is EvidenceState.CLAIMED
    assert node.confidence is None

    EvidenceGraph.apply_observation(
        session,
        job,
        EvidenceObservation(
            competency_id="debugging",
            turn_id="a1",
            state=EvidenceState.VERIFIED,
            confidence=0.86,
            note="Answer contains a concrete hypothesis and verification step.",
        ),
    )
    assert node.state is EvidenceState.VERIFIED
    assert node.confidence == 0.86


def test_contradiction_is_sticky():
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build systems",
        competencies=[Competency(id="x", description="x")],
    )
    turn = Turn(id="a", speaker=Speaker.CANDIDATE, text="answer")
    session = InterviewSession(job_id="job", candidate_ref="c", locale="en", turns=[turn])
    EvidenceGraph.initialize(session, job)

    EvidenceGraph.apply_observation(
        session, job,
        EvidenceObservation(
            competency_id="x", turn_id="a", state=EvidenceState.CONTRADICTED,
            confidence=0.9, note="Conflicts with an earlier claim."
        ),
    )
    EvidenceGraph.apply_observation(
        session, job,
        EvidenceObservation(
            competency_id="x", turn_id="a", state=EvidenceState.VERIFIED,
            confidence=0.7, note="Later positive evidence."
        ),
    )
    assert session.evidence_graph["x"].state is EvidenceState.CONTRADICTED
