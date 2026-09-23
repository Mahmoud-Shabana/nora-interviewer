import asyncio

from nora_interviewer.models import (
    AppealStatus,
    CandidateAppeal,
    Competency,
    CompetencyEvidence,
    EvidenceItem,
    EvidenceState,
    IntegritySignal,
    InterviewSession,
    JobSpec,
    ToolEvaluation,
    ToolInvocation,
    ToolKind,
    ToolStatus,
)
from nora_interviewer.review import build_recruiter_report
from nora_interviewer.review_service import ReviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_recruiter_report_surfaces_review_reasons_without_hiring_verdict():
    job = JobSpec(
        id="job",
        title="Backend Engineer",
        description="Build reliable services",
        competencies=[
            Competency(id="python", description="Python engineering"),
            Competency(id="debugging", description="Production debugging"),
        ],
    )
    session = InterviewSession(
        id="session",
        job_id="job",
        candidate_ref="candidate",
        locale="en",
        evidence_graph={
            "python": CompetencyEvidence(
                competency_id="python",
                state=EvidenceState.DEMONSTRATED,
                confidence=0.9,
                evidence=[
                    EvidenceItem(
                        turn_id="a1",
                        state=EvidenceState.DEMONSTRATED,
                        confidence=0.9,
                        note="Concrete implementation evidence.",
                        source="semantic_judge:test",
                    )
                ],
            ),
            "debugging": CompetencyEvidence(
                competency_id="debugging",
                state=EvidenceState.CONTRADICTED,
                confidence=0.7,
            ),
        },
        appeals=[
            CandidateAppeal(
                message="Please review the transcript.",
                status=AppealStatus.PENDING,
            )
        ],
        integrity_signals=[
            IntegritySignal(
                kind="possible_external_assistance",
                confidence=0.4,
                note="Review only.",
            )
        ],
        tools=[
            ToolInvocation(
                id="tool",
                kind=ToolKind.CASE_STUDY,
                title="Case",
                instructions="Analyze the case.",
                status=ToolStatus.EVALUATED,
            )
        ],
        tool_evaluations=[
            ToolEvaluation(
                tool_id="tool",
                submission_id="sub",
                passed=None,
                score=None,
                summary="Manual review required.",
                evidence={"review_required": True},
            )
        ],
    )

    report = build_recruiter_report(session, job)

    assert report.requires_human_review is True
    assert report.pending_appeals == 1
    assert report.integrity_signals == 1
    assert report.unresolved_tools == 1
    codes = {reason.code for reason in report.reasons}
    assert "conflicting_evidence" in codes
    assert "pending_appeal" in codes
    assert "integrity_signal" in codes
    assert "tool_review_pending" in codes
    assert "hiring decision" in report.note
    assert not hasattr(report, "hire")
    assert not hasattr(report, "recommendation")


def test_review_queue_filters_clean_sessions():
    async def scenario():
        store = InMemoryStore()
        job = JobSpec(
            id="job",
            title="Engineer",
            description="Build systems",
            competencies=[Competency(id="x", description="Systems")],
        )
        await store.put_job(job)

        clean = InterviewSession(
            id="clean",
            job_id="job",
            candidate_ref="c1",
            locale="en",
            evidence_graph={
                "x": CompetencyEvidence(
                    competency_id="x",
                    state=EvidenceState.DEMONSTRATED,
                    confidence=0.8,
                )
            },
        )
        review = InterviewSession(
            id="review",
            job_id="job",
            candidate_ref="c2",
            locale="en",
            evidence_graph={
                "x": CompetencyEvidence(
                    competency_id="x",
                    state=EvidenceState.INSUFFICIENT,
                )
            },
        )
        await store.put_session(clean)
        await store.put_session(review)

        service = ReviewService(store)
        queue = await service.queue()
        assert [item.session_id for item in queue] == ["review"]

        all_items = await service.queue(requires_review_only=False)
        assert {item.session_id for item in all_items} == {"clean", "review"}

    run(scenario())
