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


def setup():
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build systems",
        competencies=[Competency(id="debugging", description="debugging")],
    )
    answer = Turn(
        id="a1",
        speaker=Speaker.CANDIDATE,
        text="I reproduced the issue and compared traces.",
    )
    session = InterviewSession(
        job_id=job.id,
        candidate_ref="c",
        locale="en",
        turns=[answer],
    )
    EvidenceGraph.initialize(session, job)
    return job, session, answer


def test_domain_layer_rejects_non_literal_evidence_quote():
    job, session, answer = setup()
    try:
        EvidenceGraph.apply_observation(
            session,
            job,
            EvidenceObservation(
                competency_id="debugging",
                turn_id=answer.id,
                state=EvidenceState.DEMONSTRATED,
                confidence=0.8,
                quote="I used distributed tracing",
                note="Fabricated quote fixture",
                source="semantic_judge:test",
            ),
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "literal substring" in str(exc)


def test_domain_layer_rejects_semantic_verified_evidence():
    job, session, answer = setup()
    try:
        EvidenceGraph.apply_observation(
            session,
            job,
            EvidenceObservation(
                competency_id="debugging",
                turn_id=answer.id,
                state=EvidenceState.VERIFIED,
                confidence=0.9,
                quote="reproduced the issue",
                note="Transcript-only semantic judgment",
                source="semantic_judge:test",
            ),
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "may not emit verified" in str(exc)
