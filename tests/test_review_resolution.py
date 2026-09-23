from nora_interviewer.models import (
    Competency,
    CompetencyEvidence,
    EvidenceState,
    IntegrityReviewStatus,
    IntegritySignal,
    InterviewSession,
    JobSpec,
)
from nora_interviewer.review import build_recruiter_report


def test_reviewed_integrity_signal_remains_visible_but_leaves_pending_count():
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build systems",
        competencies=[Competency(id="x", description="systems")],
    )
    session = InterviewSession(
        id="session",
        job_id="job",
        candidate_ref="candidate",
        locale="en",
        evidence_graph={
            "x": CompetencyEvidence(
                competency_id="x",
                state=EvidenceState.DEMONSTRATED,
                confidence=0.8,
            )
        },
        integrity_signals=[
            IntegritySignal(
                kind="possible_external_assistance",
                confidence=0.3,
                note="Review only.",
                review_status=IntegrityReviewStatus.REVIEWED,
                reviewed_by="reviewer",
                review_note="Reviewed with no automatic conclusion.",
            )
        ],
    )

    report = build_recruiter_report(session, job)

    assert report.integrity_signals == 0
    assert len(report.integrity) == 1
    assert report.integrity[0].review_status.value == "reviewed"
    assert "integrity_signal" not in {
        reason.code for reason in report.reasons
    }
    assert report.requires_human_review is False
