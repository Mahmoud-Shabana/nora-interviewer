from nora_interviewer.models import EvidenceState, VoxRubricTrace
from nora_interviewer.review import (
    CompetencyReviewSummary,
    RecruiterSessionReport,
)
from nora_interviewer.review_bundle import build_review_bundle


def test_review_bundle_preserves_report_trace_and_audit_head():
    report = RecruiterSessionReport(
        session_id="session",
        job_id="job",
        role="Backend Engineer",
        candidate_ref="candidate",
        status="completed",
        competencies=[
            CompetencyReviewSummary(
                competency_id="debugging",
                description="Production debugging",
                state=EvidenceState.DEMONSTRATED,
                confidence=0.9,
                evidence_count=1,
                source_types=["semantic_judge:test"],
            )
        ],
        pending_appeals=0,
        integrity_signals=0,
        unresolved_tools=0,
        transcript_revisions=0,
        requires_human_review=False,
    )
    head_hash = "a" * 64
    trace = VoxRubricTrace(
        session_id="session",
        role="Backend Engineer",
        locale="en",
        turns=[],
        metadata={
            "event_count": 12,
            "audit_chain": {
                "verified": True,
                "head_hash": head_hash,
                "event_count": 12,
                "hash_version": 1,
            },
        },
    )

    bundle = build_review_bundle(
        report=report,
        trace=trace,
    )

    assert bundle.schema_version == "1.0"
    assert bundle.report.session_id == "session"
    assert bundle.trace.session_id == "session"
    assert bundle.audit.verified is True
    assert bundle.audit.head_hash == head_hash
    assert bundle.audit.event_count == 12
    assert bundle.audit.hash_version == 1
